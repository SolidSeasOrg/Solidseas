# STEP

STEP files are ISO 10303-21 exchange structures ("Part 21") of an application
protocol: AP203 (configuration controlled design), AP214 (automotive design) or
AP242 (managed model based 3D engineering). SolidSeas reads them with
`solidseas.formats.step` (`docs/API.md` 3.20.7): `.step`, `.stp` and `.p21`
files, and a zip archive holding one of them.

Every claim below carries a label (`README.md` in this folder): **verified**
with its source, **hypothesis** or **unknown**. Synthetic tests are in
`tests/test_formats_step.py` and `tests/test_formats_step_hostile.py`, their
files written by `tests/p21_writers.py`. Corpus measurements are counts over
the STEP files in the folders of the private development corpus
(`tests/test_formats_step_corpus.py`); no name or value from those files is
recorded.

Sources: ISO 10303-21:2016 (the exchange structure), ISO 10303-41 (product
structure, units), ISO 10303-42 (geometry and topology), ISO 10303-43
(representations and their relationships), ISO 10303-46 (presentation), the
AP203, AP214 and AP242 schemas, and the CAx Implementor Forum's recommended
practices for assembly structure, colours and user-defined attributes. No code
was adapted from another reader.

## 1. The exchange structure

**Verified (ISO 10303-21; synthetic tests).** A file is `ISO-10303-21;`, a
`HEADER;` section of `FILE_DESCRIPTION`, `FILE_NAME` and `FILE_SCHEMA`, one or
more `DATA;` sections (edition 3 names them, `DATA('name',('schema'));`), and
`END-ISO-10303-21;`. Edition 3's `ANCHOR`, `REFERENCE` and `SIGNATURE` sections
are skipped. Each data instance is `#id = NAME(parameters);`, or a complex
instance `#id = (A(...) B(...) ...);` whose records list the attributes each
entity declares, in the order stored. Comments `/* ... */` may stand wherever
white space may. Instance ids need not be in order (a writer may store them in
any order; the reader sorts its index) and must not repeat.

Parameter values: integers, reals (`1.`, `-2.5E-3`), strings, enumerations and
logicals (`.T.`, `.MILLI.`), references (`#12`), `$` (unset), `*` (derived),
typed parameters (`LENGTH_MEASURE(25.4)`), binaries (`"0FF"`) and lists.

Strings (ISO 10303-21:2016 clause 6.4.3): `''` is one apostrophe and `\\` one
backslash; `\S\c` is the character `c` plus 128 in the current ISO 8859 page,
`\PA\` to `\PI\` choose the page (ISO 8859-1 to -9, -1 by default); `\X\hh` is
an ISO 8859-1 character; `\X2\` and `\X4\` start runs of UTF-16 and UTF-32
hexadecimal code units ended by `\X0\`; `\N\` and `\F\` are print controls,
not part of the value. Carriage returns and line feeds inside a string are not
part of its value, so a string wrapped across lines reads whole. **Verified
(corpus):** writers also store raw non-ASCII bytes, which the reader decodes as
UTF-8 and, failing that, as ISO 8859-1.

**Compressed form (verified, corpus):** 8 of the 443 STEP-named files in the
corpus folders are zip archives holding one STEP file. The reader inflates the
archive's one member named `.step`, `.stp` or `.p21` (or, failing that, its one
member that starts as a Part 21 file) within the zip bounds and
`whole_read_bytes`, and reads it; anything else is refused, rule `archive`.

### How the reader reads it

The header section is read alone for a listing. A full read indexes the data
sections in one pass: a regular expression finds each instance's end (a
semicolon outside strings and comments) and its id and entity name; complex
instances are parsed for their names. The index is four arrays (ids, starts,
ends, entity codes) over a name table, about 28 bytes an instance. Parameters
are parsed only when an instance is read, and a bounded number of parsed
records are kept.

## 2. Which STEP a file is

**Verified (schemas; corpus):** `FILE_SCHEMA` names the schema. The variant is
`AP203` for `CONFIG_CONTROL_DESIGN` and AP203's second edition
(`AP203_CONFIGURATION_CONTROLLED_3D_DESIGN_OF_MECHANICAL_PARTS_AND_ASSEMBLIES_MIM_LF`),
`AP214` for `AUTOMOTIVE_DESIGN`, `AP242` for
`AP242_MANAGED_MODEL_BASED_3D_ENGINEERING`, whatever object identifier
follows the name, and `other` for anything else, read by the same rules.

**Verified (Alibre Design samples, by the design's research):** Alibre Design
stores its design history as Part 21 under `('ALIBRE_SCHEMA',
'CONFIG_CONTROL_DESIGN')`. It holds no geometry and would otherwise pass as
AP203, so a schema list naming `ALIBRE_SCHEMA` is refused, rule
`private_schema`.

## 3. Product structure and assemblies

**Verified (ISO 10303-41, -43, -44; synthetic tests; corpus):**

- A `PRODUCT_DEFINITION` (or `PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS`) of a
  `PRODUCT_DEFINITION_FORMATION` of a `PRODUCT` is one product version. Its
  `PRODUCT_DEFINITION_SHAPE` is linked by a `SHAPE_DEFINITION_REPRESENTATION` to
  its shape representation.
- Representations related by a `SHAPE_REPRESENTATION_RELATIONSHIP` (or a plain
  `REPRESENTATION_RELATIONSHIP`) without a transformation share one coordinate
  space; with a `REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION`, or through a
  `MAPPED_ITEM` (its `REPRESENTATION_MAP`'s origin onto its target), one is
  placed in the other. A product's geometry is every item reachable that way
  without entering another product's representation. Each representation is
  walked once for each placement it is reached at, so a dense graph of
  relationships costs its links rather than its paths.
- An assembly is a `NEXT_ASSEMBLY_USAGE_OCCURRENCE` from the parent product
  definition (`relating_product_definition`) to the child's. Its placement is
  the `CONTEXT_DEPENDENT_SHAPE_REPRESENTATION` whose
  `represented_product_relation` is the occurrence's product definition shape,
  and whose relationship maps `transform_item_1` of `rep_1` onto
  `transform_item_2` of `rep_2` (an `ITEM_DEFINED_TRANSFORMATION`, or a
  `CARTESIAN_TRANSFORMATION_OPERATOR_3D`).
- **The placement rule.** Writers store `rep_1` and `rep_2` in both orders. The
  reader finds which of the two belongs to the child product definition (its
  shape representations and those sharing their space), never by position, and
  places the child at `T(parent item) * inverse(T(child item))`, each `T` from
  its axis placement (location, axis and ref_direction, with ISO 10303-42's
  defaults: axis z, ref_direction x, or y when the axis is along x; the
  ref_direction made perpendicular to the axis). Each location is scaled by its
  own representation's length unit. Synthetic tests place both orders, nested
  sub-assemblies and mapped items.
- A context-dependent shape representation whose relationship has no
  transformation places nothing by itself: the occurrence takes the mapped item
  of the child held by the relationship's other representation (one that is
  neither the parent's nor the child's), else a mapped item of the parent's
  shape that maps the same child, else the parent's origin, where a
  relationship without a transformation puts it. An occurrence with no
  relationship of its own takes such a mapped item too; failing that it is
  placed at the origin (`placement_unresolved`). A mapped item left over that
  places the child where one of the pair's occurrences already sits by its own
  relationship is the same occurrence, written twice; one elsewhere is kept as
  a further occurrence and the file is warned `placement_ambiguous`. Synthetic
  tests place both mapped-item forms, and an occurrence placed both ways.
- A component is named by its occurrence's `name`, else by the child product
  (its name, else its id), else by the occurrence's `id`. **Corpus:** 5,086 of
  the 5,835 occurrences, in 26 of the 68 assemblies, leave the name blank and
  number the id (`NAUO1`, `NAUO2`...), so the product name is what the tree
  shows for them.
- Products and representations are followed with the path kept, so a product
  inside itself, or a mapped item of its own representation, is not followed
  again (`assembly_cycle`). The root products are those no occurrence places
  (when every product is inside another, the first one); the tree is at most
  `depth` deep.
- A file with no product structure at all (geometry in a representation no
  product names) is read as one product holding every shape representation's
  geometry.

**Corpus (verified, numbers only):** of the 443 files, 68 are assemblies with
5,835 occurrences, every one placed by a context-dependent shape
representation over an item-defined transformation; none was left without a
placement. 442 files have one root product and one has five.

## 4. Units

**Verified (ISO 10303-41; synthetic tests; corpus):** each representation's
context (`GEOMETRIC_REPRESENTATION_CONTEXT` with `GLOBAL_UNIT_ASSIGNED_CONTEXT`
and usually `GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT`) names its units. A unit is an
`SI_UNIT` with an optional prefix (`.MILLI.`, `.CENTI.`...) or a
`CONVERSION_BASED_UNIT` whose `MEASURE_WITH_UNIT` (or a typed subtype) gives
its size in another unit: an inch is `LENGTH_MEASURE(25.4)` millimetres, a
degree about 0.01745 radians. Lengths and positions are in the context's
length unit and every angle (a cone's semi-angle, a trimming parameter on a
circle, a pcurve's angular parameter) in its plane angle unit. With no length
unit, millimetres are assumed (`units_assumed`); with no plane angle unit,
radians. The document's `units` are the root product's representation's.

**Corpus (verified):** 419 files in millimetres, 21 in inches, 2 in
centimetres and 1 in metres, every one stated by the file.

## 5. Geometry and topology

**Verified (ISO 10303-42; synthetic tests; corpus; the tessellator's
conventions in `docs/FORMAT.md` 10.8):** each solid and shell becomes one
Parasolid body built in memory (`solidseas.formats.step.builder`) and drawn by
SolidSeas' tessellator, so a solid comes out closed wherever its faces are
read. What maps to what:

| STEP | Body |
|---|---|
| `MANIFOLD_SOLID_BREP`, `BREP_WITH_VOIDS` (void shells added), a `CLOSED_SHELL` on its own | a solid |
| each shell of a `SHELL_BASED_SURFACE_MODEL`, an `OPEN_SHELL` on its own | a sheet |
| `ADVANCED_FACE`, `FACE_SURFACE` | a face, its sense from `same_sense` |
| `ORIENTED_FACE`, `ORIENTED_CLOSED_SHELL`, `ORIENTED_OPEN_SHELL` with orientation false | the faces turned round: normal and bounds |
| `FACE_OUTER_BOUND`, `FACE_BOUND` | a loop; orientation false runs it backwards (its edges in reverse order, each the other way) |
| `EDGE_LOOP` of `ORIENTED_EDGE` | fins, each along its edge when its orientation is true |
| `EDGE_CURVE` | an edge from `edge_start` to `edge_end`, along its curve when `same_sense` is true |
| `VERTEX_LOOP` | a loop of one vertex (an apex, a pole) |
| `POLY_LOOP` | line edges, shared by every face that names the same two points |
| `VERTEX_POINT` | a vertex |

The face's topological normal is its surface's normal when `same_sense` is
true, and its bounds run with the face on their left seen from that normal;
this is XT's convention too (verified: every synthetic solid comes out closed
with a positive volume, and so do 1,922 of the 2,342 corpus solids
tessellated; section 10 has the others).

Surfaces:

| STEP | XT | Notes |
|---|---|---|
| `PLANE` | plane | |
| `CYLINDRICAL_SURFACE` | cylinder | |
| `CONICAL_SURFACE` | cone | radius at the placement, semi-angle in the context's angle unit |
| `SPHERICAL_SURFACE` | sphere | |
| `TOROIDAL_SURFACE`, `DEGENERATE_TOROIDAL_SURFACE` | torus | |
| `B_SPLINE_SURFACE_WITH_KNOTS`, `BEZIER_SURFACE`, `UNIFORM_SURFACE`, `QUASI_UNIFORM_SURFACE`, each rational (a complex instance with `RATIONAL_B_SPLINE_SURFACE`) or not | B-spline surface | control points `[u][v]`, which XT stores with v varying fastest; knots generated for the forms that store none; equal weights read as non-rational |
| `SURFACE_OF_LINEAR_EXTRUSION` | swept surface | the sweep is the extrusion vector with its magnitude; turned round when its curve is a trimmed curve running against its basis (below) |
| `SURFACE_OF_REVOLUTION` | spun surface, turned round | STEP's u is the turn and v the curve's parameter, XT's the other way, so their natural normals are opposite; not turned when its curve runs against its basis; a curve that is an unbounded `LINE` is trimmed to cover the body once the body is built (a spun surface over an unbounded line cannot be inverted); a closed curve (a whole `CIRCLE`, as OCCT writes a revolved arc) has a pole wherever it crosses the axis |
| `OFFSET_SURFACE` | offset surface | an XT offset surface takes its basis's own normal, so the offset of a basis that was turned round is the offset of the basis as built, by minus the distance, turned round |
| `RECTANGULAR_TRIMMED_SURFACE`, `CURVE_BOUNDED_SURFACE` | their basis surface | the face's bounds trim it; a rectangular trim with exactly one sense false turns the normal round |

Curves:

| STEP | XT |
|---|---|
| `LINE` | line (its vector's direction) |
| `CIRCLE`, `ELLIPSE` | circle, ellipse |
| `HYPERBOLA`, `PARABOLA` | in an edge, the arc between the edge's vertices as the exact rational quadratic B-spline it is (Bezier pieces of at most one unit of the hyperbola's parameter; one polynomial piece for a parabola), running the way the conic does; trimmed in a composite curve, sampled as the other pieces are. An XT body has neither curve. As a swept or spun surface's curve, not read |
| `B_SPLINE_CURVE_WITH_KNOTS`, `BEZIER_CURVE`, `UNIFORM_CURVE`, `QUASI_UNIFORM_CURVE`, rational or not | B-spline curve |
| `POLYLINE` | a B-spline of degree 1 |
| `SURFACE_CURVE`, `SEAM_CURVE`, `INTERSECTION_CURVE`, `BOUNDED_SURFACE_CURVE` | their 3D curve |
| `TRIMMED_CURVE` | in an edge, its basis curve (the edge's vertices trim it; `sense_agreement` false reverses it); in a swept or spun surface, an XT trimmed curve with its parameters in XT's units, running along its basis, so a `sense_agreement` false (an odd number of them, through wrappers and nested trims) turns the surface round; a B-spline basis is its own range |
| `PCURVE` alone as an edge's geometry | an SP-curve when its 2D curve is a B-spline or a polyline on a plane, cylinder, cone, sphere, torus or B-spline surface (whose (u, v) are XT's, lengths to metres and angles to radians) |
| `COMPOSITE_CURVE` (and `COMPOSITE_CURVE_ON_SURFACE`, `BOUNDARY_CURVE`) as an edge's geometry | a B-spline of degree 1 through its segments (lines, conics, B-splines and polylines, trimmed or not, each the way its `same_sense` says), sampled to within a ten-thousandth of its size: an XT body has no composite curve. Each curve record is sampled once a body, and a composite curve, or any piece of it, of more than 20,000 points leaves its face out (`edge_too_long`) |

Other pcurves are not read: the tessellator places each edge's points on each
face's surface itself. A knot vector whose end multiplicities are one short
(as some writers store them) is completed.

**A full sphere bounded by its seam (verified, synthetic tests).** A
`SPHERICAL_SURFACE` face whose bound is an `EDGE_LOOP` that only runs up and
down its seam (every edge in it once each way, every vertex at a pole) is a
whole sphere, but its loop has no area in (u, v) and the tessellator leaves
such a face out (`degenerate`). The reader makes it a vertex loop at each
pole instead, as a sphere bounded by vertex loops is drawn. **Corpus:** no
face is bounded so.

**Void shells (verified, synthetic tests and corpus, section 10).** A
`BREP_WITH_VOIDS` lists its voids as `ORIENTED_CLOSED_SHELL`s, every one in the
corpus with orientation `.F.`. By the letter of ISO 10303-42 that turns the
closed shell's faces round, which is right for a writer whose closed shell
faces out of the void as a solid's would, and wrong for one whose closed shell
already faces into it: read so, that void faced out of itself and its volume
was added to the solid's, not taken from it. The reader keeps the file's
orientation in `bodies()`, and a scene turns each closed shell of a solid by
its signed volume instead, the outer shell positive and each void negative
(`void_reoriented`; an outer shell that faced in, `solid_reoriented`). A shell
that is not closed is left as it is.

**Faces whose loops all run against them (verified, synthetic tests and
corpus).** Some writers store a face's `same_sense` false with its loops
written as if it were true, so no loop runs the way of the face. The
tessellator used to leave such a face out (`seam_configuration`, which says
nothing of a plane); every face of eight small corpus files is stored so, and
they drew nothing. On a surface that does not close the face now keeps the
sense the file gives it and its loops are read the other way round, its
largest loop the outer one (`loops_reversed`), as OCCT reads it. In those
files the faces' sense is the right one: each of their solids is faces that
share no edge, so no check of neighbours or shells can turn them, and turned
round to follow their loops (as a first version of this repair did) every one
faced in. Where such a face meets neighbours that disagree with it, its sense
was the wrong one, and the solid's check turns it to agree with them
(`faces_reoriented`, below); a closed solid that came out inside out as a
whole is turned by its shell check (`solid_reoriented`). In such a solid,
faces whose points lie at the same place count as neighbours even when they
share no edge: a face thinner than the chord tolerance follows its loop
whichever way it runs (its sampled sides may cross), and in two more files
stored the same way (88 faces each, 16 of them left out as `bad_reference`)
eight such faces faced in until they were turned so. These ten files now draw
every face they can, facing out (their signed volumes are OCCT's); each solid
of theirs is open and says so (`solids_not_closed`).

**A CadQuery model rocket (verified, `tests/generated/rocket.step`,
synthetic tests, the OCCT oracle).** A rocket made with CadQuery and exported
by OCCT drew with holes in three places, and the 3D view said nothing of them:

- Its nose, an arc turned about the axis with its centre off the axis, is a
  `SURFACE_OF_REVOLUTION` of the arc's whole `CIRCLE`, which crosses the axis at
  the tip. A spun surface over a closed curve was taken as periodic both ways
  with no pole, so the face's one loop (round the base, up the seam to the tip
  and back) had nowhere to close (`seam_configuration`). The crossings of a
  closed profile are now its poles, and the cap closes on the first one beyond
  the loop.
- Its fins meet the skirt's cone along `HYPERBOLA` edges, and the fins and the
  cone were left out (`unsupported_curve`). Those edges are now exact rational
  B-splines (Curves, above).
- Its base's fillet is a torus band bounded by one loop, round both rims and up
  and down the seam, which OCCT writes running against the face (its rims run
  the same way as in the neighbouring cone and base). On a torus a loop that
  runs against its face is read as a hole in the whole surface, and this one
  reaches all the way round it, so the face was left out (`seam_configuration`).
  When the loops of a face on a closed surface leave no surface outside them,
  the face is read as one whose loops all run against it (`loops_reversed`).

The rocket now draws all 20 faces, closed, within 0.02 % of OCCT's area and
0.08 % of its volume at a 10 micrometre chord, and the oracle agrees with it
face by face.

**Closed B-splines (verified, synthetic tests).** A B-spline curve or surface
is marked closed when it is, evaluated: its two ends, or its boundary curves
at the two ends of a parameter range, meet within a billionth of its control
net's size, whatever the file's `closed_curve`, `u_closed` or `v_closed` says.
A closed edge of one vertex on such a curve then goes all the way round, and a
periodic surface (uniform knots, its control rows not repeated as a clamped
surface's are) is known to close; without this both come out with no area
(`tests/test_formats_step.py`, the periodic hoop).

A face whose surface or one of whose curves is not read, or that holds values
the builder refuses (a direction of no length, a value that is not finite, a
B-spline whose counts disagree), is left out with a reason, as the tessellator
leaves faces out: `unsupported_surface`, `unsupported_curve`, `bad_geometry`,
`non_finite`, `bad_reference`. Records are parsed when they are read, so a
record that cannot be parsed is found while the face that needs it is mapped:
that face (or the shell, or the body, whose own record it is) is left out with
`bad_reference`, and an item of a representation that cannot be parsed is not
drawn (`representation_skipped`, `damaged`); the rest of the file reads. Not
read (unknown whether any corpus file needs them): `OFFSET_CURVE_3D`,
`SURFACE_REPLICA`, `CURVE_REPLICA`, and a `HYPERBOLA` or `PARABOLA` as the curve
of a swept or spun surface.

**The chord tolerance** of a scene is one for the whole model: the caller's
`chord_m`, else `chord_fraction` (0.1 percent by default) of the diagonal of a
box over every body's vertices, conics' and closed surfaces' extents and
B-spline control points, kept from 1e-6 m to `max_chord_m`.

## 6. Faceted and tessellated geometry

**Verified (ISO 10303-42; synthetic tests):**

- `FACETED_BREP`: a closed shell of planar faces bounded by `POLY_LOOP`s. Each
  face's polygon, holes included, is projected onto the plane of its outer
  loop's Newell normal and triangulated with the tessellator's earcut (concave
  polygons included), keeping the loop's direction. Faces share a vertex
  wherever they name the same point, so a closed shell gives a closed mesh.
  **Corpus:** one file holds a faceted B-rep.
- AP242: `TRIANGULATED_FACE`, `COMPLEX_TRIANGULATED_FACE` (strips, whose
  winding alternates, and fans about their first point),
  `TRIANGULATED_SURFACE_SET`, `COMPLEX_TRIANGULATED_SURFACE_SET`, grouped by
  `TESSELLATED_SHELL` and `TESSELLATED_SOLID`, over a `COORDINATES_LIST`.
  Indices count from 1; a face's `pnindex`, when it has one, maps them to the
  coordinates. Normals are not read. **Corpus:** none.

Both are meshes as stored (`source` `mesh`), in the representation's length
unit scaled to metres.

## 7. Colours

**Verified (ISO 10303-46; CAx-IF recommended practice; synthetic tests;
corpus):** a `STYLED_ITEM` gives its item (a solid, a shell, a face, a surface
model) a list of `PRESENTATION_STYLE_ASSIGNMENT`s; an
`OVER_RIDING_STYLED_ITEM` wins over it. A surface colour is reached through
`SURFACE_STYLE_USAGE`, `SURFACE_SIDE_STYLE` and either
`SURFACE_STYLE_FILL_AREA`, `FILL_AREA_STYLE` and `FILL_AREA_STYLE_COLOUR`, or
`SURFACE_STYLE_RENDERING` (with properties: `SURFACE_STYLE_TRANSPARENT` sets
the alpha), down to a `COLOUR_RGB` (0 to 1) or a
`DRAUGHTING_PRE_DEFINED_COLOUR` (red, green, blue, yellow, magenta, cyan,
black, white). Curve styles are not read, and neither are styles that depend on
an assembly context.

A body takes its own colour, else its shell's or its surface model's, else the
most common colour of its faces; a body whose faces have several colours is
drawn in the most common one and the file is warned `colors_ignored`. A body
is one mesh object, so that a printed solid stays closed.

**Corpus (verified):** 408 of the 443 files style items, and every one of
them gives at least one body a colour; 26 bodies in 11 files have faces of
several colours.

## 8. What a file says about itself

**Verified (ISO 10303-21 clause 8; CAx-IF recommended practice for
user-defined attributes; synthetic tests):**

- `FILE_NAME`'s time stamp (ISO 8601) is `fields.last_saved_utc`: aware UTC
  when it has a zone, else naive as stored (ISO 8601 text without a designator
  is local time where it was written, zone unknown); its authors are
  `fields.author`; its originating system is `application.name` (the version is
  not split off: writers word it in too many ways). Every header field is also
  a property.
- The root product's id, name and description are properties, and its name is
  `fields.title`.
- User-defined properties: a `PROPERTY_DEFINITION` of the root product
  definition (or of its product definition shape) with a
  `PROPERTY_DEFINITION_REPRESENTATION` whose representation holds
  `DESCRIPTIVE_REPRESENTATION_ITEM`s (text), `MEASURE_REPRESENTATION_ITEM`s or
  `VALUE_REPRESENTATION_ITEM`s (numbers, text, logicals). A property is named by
  its item, else by its property definition. **Corpus:** 26 files have them.
- External document references (`DOCUMENT_FILE`) are reported by
  `references()` and never opened.

## 9. Bounds and hostile files

Every bound is a field of `Limits` (`docs/API.md` 3.20.2): the header
(`p21_header_bytes`), one instance (`p21_record_bytes`), the instances
(`p21_records`), one list (`p21_list_items`), list nesting
(`p21_list_depth`), one string (`p21_string_bytes`), the records of a complex
instance (`p21_complex_parts`), the nodes of one body (`brep_nodes`), the
distinct knots of a B-spline (`bspline_knots`), products (`step_products`),
assembly occurrences (`step_occurrences`), styled items
(`step_styled_items`), the tree (`depth`, `tree_nodes`), placed items
(`items`), triangles, time (`seconds` for a head or a tree, the scene's own
`max_seconds`), the file in memory (`whole_read_bytes`) and, for an archive,
the zip fields. The tessellator keeps its own. `tests/test_formats_step_hostile.py`
has a file for each, and for unterminated strings, comments, lists and
records, references to missing instances, references that loop, numbers that
are not finite, directions of no length, B-splines whose counts disagree, a
zip that inflates past its bounds, and entity names inside strings.

The time bound holds through the whole read: the clock is ticked for every
instance indexed, every product, every representation visited and every
relationship followed, every occurrence path planned, and every control point,
curve sample and composite segment mapped, as well as by the builder and the
tessellator. A head, a tree or `bodies()` past its time ends in
`SldLimitError` (`seconds`). A scene past its `max_seconds` while it maps or
tessellates bodies keeps what it finished: the bodies not done are skipped
items (`max_seconds`) and the scene is warned `faces_left_out`. The tree keeps
its first `tree_nodes` nodes and is truncated; the occurrence paths are
counted, not kept, and the scene walks them again to place its items, so a
small file that fans out into many paths costs time, bounded, rather than
memory. Past `items` placed items, or past `items` plus `tree_nodes` products
reached, the scene ends in `SldLimitError` (`items`). Hostile tests cover a
dense graph of relationships, one whose paths all give new placements, an
assembly of a million paths in 50 KB, composite curves nested a million
leaves deep, a large control net, and damaged records.

## 10. The corpus

Measured read-only on the 443 STEP files in the corpus folders, in worker
processes below normal priority, numbers only, each scene within 300 s
(`tests/test_formats_step_corpus.py`); no file changed while read:

- **Read:** 443 of 443 (8 of them zip archives). Variants: AP214 414, AP203
  27, AP242 2. Head (header and census): median 0.02 s, largest 3.1 s; full
  read (index, product structure, plan): median 0.07 s, 90th percentile
  0.96 s, largest 17.3 s.
- **Structure:** 68 assemblies, 5,835 occurrences placed, none at the origin
  for want of a placement, none by a mapped item and none warned
  `placement_ambiguous`; no component is named by an occurrence id
  (`NAUO<n>`) any more; 3 files hold no geometry and read with no bodies;
  6 files hold wireframe items (`GEOMETRIC_SET`) that are not drawn
  (`representation_skipped`).
- **Objects:** 2,342 solids, 2,221 surface-model shells, 1 faceted B-rep.
- **Faces:** 447,052 of the 449,946 faces of the bodies were tessellated
  (99.36 percent); every face was done in 394 files. No file reaches its
  300 s bound: the largest, which reached it with 191 bodies not started
  before its folded faces were fixed (`docs/API.md` 3.15), now takes 88 s.
- **Faces left out**, by the tessellator's reason and surface: `degenerate` on
  B-spline surfaces 2,268, `seam_configuration` on B-spline surfaces 438,
  `degenerate` on planes 118, `triangulation_failed` 45 (40 on B-spline
  surfaces, 5 on planes), `degenerate` on cylinders 14, on tori 4,
  `seam_configuration` on tori 6, `inversion_failed` 1; more than before
  because the largest file's bodies are all reached now. `edge_too_long` no
  longer occurs: an edge whose curve stops dead at a knot is no longer sampled
  into a pile of points. Mapping left out no face: every surface and curve met
  was read. **Hypothesis**, from looking at the faces (numbers only): most
  `degenerate` B-spline faces are slivers, a long strip whose short sides are
  less than a tenth of the chord tolerance, which the tessellator takes for a
  surface closed on itself with two poles; the `seam_configuration` ones are
  faces of rational quintic surfaces, and of tori, whose single loop winds
  round the surface in a way the tessellator's domain cases do not take.
  Both are the tessellator's to settle.
- **Closed:** 1,924 of the 2,342 solids tessellated are closed (oriented, every
  edge used once each way), some of them because faces were turned to agree
  (below). The scene now says when one is not: `solids_not_closed` in 88
  files, and `faces_folded` in 74 (a face whose triangles cover its (u, v)
  polygon more than once, lie on one another or stretch across it; the
  causes in `docs/API.md` 3.15 are fixed, others remain). Counted per file,
  not only per solid (a file whose solids were open already can still get
  worse): the open solids hold 90,733 directed mesh edges with no partner, in
  67 files, and 33,613 used twice the same way, in 65 files, at most 12,980 in
  one. Over all 1,328 distinct STEP files of the corpus folders, against the
  reader before its folds were fixed, 4 files have a few more edges with no
  partner (2 to 46 more, beside 10 files that drew nothing before), 13 have
  more edges used twice the same way (2 to 595 more, in files that had 2 to
  12,964), and 2 have one face more left out; open solids went from 1,057 to
  997 and edges with no partner from 191,128 to 154,673. In an earlier run,
  before those fixes, every open solid with every face done had mesh edges
  used once or used twice the same way, and the review's census of faces
  found no face but those of the 2 solids below whose triangles run against
  its neighbours.
  **Unknown:** what keeps the rest open. 960 of the 2,221 surface-model
  shells are closed surfaces.
- **Void shells (verified, section 5):** in 4 files a solid's void shells
  faced out of their voids, and the scene turns them (`void_reoriented`); in
  2, a solid that came out inside out as a whole is turned
  (`solid_reoriented`). Faces whose loops all run against them are read with
  their loops the other way round in 5 files (`loops_reversed`); where they
  meet neighbours that disagree they are turned to agree (`faces_reoriented`,
  now in 7 files with the 2 below).
- **Holes stored inside out (verified, the review's census and synthetic
  tests).** In 2 files, 4 plate faces have 82 bounds each, all `FACE_BOUND`:
  the outer one runs counter-clockwise about the face's normal, and so do the
  81 holes, which should run the other way. The 158 seam cylinders lining the
  holes have a `same_sense` that agrees with those loops, so the topology is
  consistent with itself and inside out at every hole. The tessellator takes
  a face's holes by where they lie, so the plates come out right and the
  walls turned against them. A scene now turns round, in a solid whose mesh
  does not close, the faces whose triangles run against their neighbours'
  (the smaller part of each group's area) and warns `faces_reoriented`: 234
  faces in those 2 solids, both now closed with a positive volume.
  `bodies()` keeps the file's orientation; healing the loops of the B-rep
  itself is not done.
- **Colours:** 408 files style items, all 408 give a body a colour.
- **Scene times:** median 0.9 s, 90th percentile 13 s, largest 115 s.

## 11. The OCCT oracle

**Verified (OCCT 7.9.3 through `cadquery-ocp` 7.9.3.1.1;
`tests/test_occt_oracle.py`, `tests/test_occt_corpus.py`; `tests/README.md`
says how to run them):** Open CASCADE reads the same files with its basic
`STEPControl_Reader`, in a child process with a memory cap, a timeout and no
crash dumps. It measures them exactly:

- volume by Gauss-Kronrod integration, once per shell, so a void's comes out
  negative;
- area by adaptive integration, face by face;
- a fine mesh of its own, to check both.

The reader's tessellation is compared with OCCT's reading at three levels:

- **face by face:** faces paired by centroid and area. On a cylinder, sphere or
  torus a face may also fall short by its tessellation's own error: one and a
  half times a third of the chord over the surface's smallest radius, for each
  direction in which the surface curves. Never larger: a polygon does not
  exceed its surface;
- **shell by shell:** the connected pieces of the scene's mesh against OCCT's
  shells, paired by centroid and then size, by signed volume;
- **in total**, and for the mesh's own soundness: no edge of a solid open or
  used twice the same way, no face skipped.

**Agrees.** At a 2 micrometre chord, within 3e-3 per face (the worst 1.19e-3,
the plane cap of the elliptic prism, short), on:

- every synthetic file of `tests/occt_shapes.py`;
- SolidSeas' STEP of every fixture, and of a cube with a cavity and a part of
  one sheet, built by code (`tests/xt_bodies.py`);
- SOLIDWORKS' STEP of o02.

The synthetic files cover every surface and edge form the tests write, a sheet,
two solids, a hollow cylinder whose two walls share a centroid, and assemblies.

**As drawn.** What the user sees and prints is not that tessellation: the
viewer draws a STEP at 1e-3 of its box diagonal, and 3D Print tessellates it at
2.5e-4 of the diagonal, at most 10 micrometres. Whether a solid comes out open,
or a face folded, depends on the chord. So the same files are also read as each
draws them, and checked for what no chord excuses: a face larger than its whole
surface, a shell inside out, an edge of a solid open or used twice the same way,
a face skipped. All of them pass.

**Voids SolidSeas writes.** OCCT orients a void shell by its geometry whatever
the file says, so it cannot see a cavity written inside out. SolidSeas writes a
cavity as Parasolid holds it, its faces already looking into it, under
`ORIENTED_CLOSED_SHELL .T.` (none of the corpus writers does: theirs are all
`.F.`). Two checks see that convention: `tests/test_step.py` reads the void's
signed volume from the file itself as ISO 10303-42 does, and the oracle has
SolidSeas' reader read its own export back and pairs each shell with OCCT's.

**Defects, each reproduced in a synthetic file** (`occt_shapes.DEFECTS`, an
expected failure until its fix lands). The reader now reads the voids and the
faces whose loops run against them right (sections 5 and 10): OCCT and the
reader agree on those synthetic files, and the marks are off. What follows
describes the reader before those fixes, and the corpus figures below were
measured then:

- **Voids inside out.** A `BREP_WITH_VOIDS` whose void shell already faces
  into the void and is still marked `ORIENTED_CLOSED_SHELL .F.`, as some
  writers store it. Turned round as ISO 10303-42 says, the void faces into the
  material and adds its volume.
  - Synthetic file: 28,000 cubic millimetres where OCCT, orienting by geometry,
    gives the true 26,000; the void's piece measures +1,000 against OCCT's
    -1,000.
  - Corpus: 21 STEP files have voids, every one `ORIENTED_CLOSED_SHELL .F.`.
    Of the 20 OCCT reads within its memory cap (not step#426, of 76 MB), 14
    have at least one void inside out: step#32, #38, #182, #885, #889, #1022,
    #1098, #1099, #1104, #1245, #1249, #1269, #1270 and #1389. Each such void
    measures OCCT's volume with the sign turned (step#1245: +4.3 against -4.3
    cubic millimetres; step#32: 19 of its 22 voids).
  - The whole file's volume hides most of them: +24.6 % on step#38 and +78 % on
    step#1389, but 4.8e-4 on step#1245 and 2.2e-4 on step#1249. Shell by shell
    is the check that sees them.
  - The other 6 read right: step#283, #896, #898, #1033, #1076 and #1100. The
    reader tier reads all 20 on every run.
  - An STL or 3MF made from such a body has an inside-out cavity.
- **Faces whose loops all run against them.**
  - One face of a box: skipped as `seam_configuration`, so the solid is open
    (4,000 against 6,000 cubic millimetres).
  - Every face: nothing is drawn.
  - Corpus: step#12 to step#20 except step#16.
- **Folded triangles** (step#903, step#1023, step#1175, step#1250, step#1271,
  and also in step#885, #1022, #1104, #1269 and #1270, which have voids inside
  out too). Faces on B-spline and sphere surfaces whose triangles cover more
  than the whole surface they lie on.
- **Torus faces drawn over the wrong part of their surface.** step#48's two
  torus faces at three and a half times their area, its mesh still closed; two
  small faces of step#1146, 10 to 16 % larger than OCCT's and centred up to
  0.36 mm away, on a torus of 3 mm minor radius, where the chord explains
  nothing; one torus face of step#569, 1.1 % larger than both of OCCT's
  measures (which agree within 0.09 %) on a torus whose smallest radius is
  2.5 micrometres. A polygon cannot be larger than its surface, so no chord
  explains that either; an allowance that also forgave faces too large took
  it for the chord's error.

No synthetic file reproduces the last two yet. The oracle's comparison catches
them (`tests/test_occt_support.py`).

**What OCCT cannot referee.** Some synthetic files SolidSeas reads are not
compared:

- edges stored only as pcurves (OCCT removes them);
- `COMPOSITE_CURVE` edges (OCCT converts none);
- a `SEAM_CURVE` without its pcurves (OCCT translates nothing);
- an assembly placed by `MAPPED_ITEM`s (OCCT transfers one of the two).

**OCCT's own integrators.**

- Its default `VolumeProperties` and `SurfaceProperties` were off by up to
  8.6 % and 4.5 % on B-spline-heavy corpus files.
- Even its adaptive area at eps 1e-9 is 1.2 % high on the side of an elliptic
  prism, a `SURFACE_OF_LINEAR_EXTRUSION`. Its mesh and SolidSeas' agree there
  with the exact area.
- A face of the reader therefore agrees with OCCT when it agrees with either of
  OCCT's measures, the adaptive area or its mesh's. A mesh set by the part's
  size is the one that is off beside a small fillet. The reader's defects put a
  face far from both.

**Corpus.** `test_occt_corpus_step_reader` ran read-only at below-normal
priority, no file changed, in 31 minutes on 4 workers. It read 82 of the 1,405
STEP files below the manifest's folders:

- `random.Random(20261004).sample` of 40 files of at most 5 MB;
- the files of `KNOWN_KEYS`, where the oracle has found the reader wrong, and
  the 6 files with voids it reads right;
- step#302, #637 and #1247, which the oracle's review looked at.

These keys number the files of those folders and their subfolders, as the
evaluation did. `tests/test_formats_step_corpus.py` reads the folders alone.
SolidSeas tessellated each file at 2e-5 of OCCT's box diagonal, and every face,
shell and total had to agree within 1 %. Each file was read twice more, as the
viewer draws it and as 3D Print tessellates it, for what no chord excuses.

- **Known files.** Every one still disagrees, as listed in `KNOWN_KEYS`:
  - voids inside out (bead 1): the 14 above, at every chord;
  - faces larger than their whole surface or torus faces off (bead 2):
    step#48, #569, #903, #1023, #1146, #1175, #1250, #1271;
  - every planar face skipped (bead 3): step#12 to step#20 except step#16;
  - faces skipped and solids left open, at the oracle's chord and as drawn,
    the cause not yet known: step#239, #611, #989, #1305; step#779 skips a
    face (`inversion_failed`) at the oracle's chord only;
  - sound at the oracle's chord but not as the viewer draws them: step#879,
    #898 and #163 (3, 6 and 7 open edges), step#412 (folded faces, 633 open
    edges and skipped faces), step#1116 (a face larger than its surface, also
    as 3D Print tessellates it).
- **As drawn.** At the viewer's chord 24 of the 82 files have an open solid, 16
  a face larger than its surface and 25 a face skipped; at 3D Print's, 14, 13
  and 20. The viewer's chord is 1e-3 of the box of the bodies in their own
  frames, not of the placed model: step#1116 is drawn at 398 micrometres, six
  times 1e-3 of OCCT's box diagonal.
- **The sample.** 36 of the 40 agree at the oracle's chord, 34 as drawn too.
  The 6 that do not are in `KNOWN_KEYS`: step#611, #1146 and #1305, found
  before; step#569, which the old allowance passed; step#163 and #412, open or
  folded only as drawn.
- **Not settled.** step#637 and step#1247 have faces off by more than 1 %, in
  files where OCCT's own two measures disagree on 4 and 7 faces; step#637 also
  skips a face as the viewer draws it, and step#1247 folds triangles at every
  chord. OCCT cannot read step#302 (`Standard_NullObject`).
- **OCCT's own measures** disagreed with each other by more than 1 % on 220
  faces or volumes. There SolidSeas was held to the nearer of the two.
