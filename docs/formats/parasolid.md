# Parasolid transmit files

A Parasolid transmit file holds the exact B-rep of a part, or of an assembly of
parts, as the Parasolid kernel writes it for exchange: `.x_t` and `.xmt_txt` in
text, `.x_b` and `.xmt_bin` in binary. SolidSeas reads them with
`solidseas.formats.xt` (registry id `parasolid`), using the transmit reader it
already has for the bodies inside SOLIDWORKS documents
(`solidseas.formats.solidworks.parasolid`, `docs/FORMAT.md` section 10, which
describes the transmit format itself) and draws them with
`solidseas.tessellate`. Labels as in [README.md](README.md). The public source is
the Parasolid XT Format Reference (October 2006 edition, the one `FORMAT.md`
cites; "the reference" below).

## Telling it apart

The registry's content test (verified: the reference, and the fixtures) accepts
the common header's first line (`**ABCDEFGHIJ`), a text transmit's flag and
modeller string (`T<n> : TRANSMIT FILE`) or a neutral binary transmit's flag
`PS\0\0`. A bare (platform) binary transmit, flag `B`, is told apart only by its
extension, and refused (below).

## The common header

- **Layout** (verified: the reference's "Physical Layout"; the SOLIDWORKS-written
  fixtures `o02_boxA.x_t`, `o02_boxA.x_b` and the others; files SolidSeas writes).
  Two preamble lines of every printable character, `**PART1;` and its keywords,
  `**PART2;` (`SCH`, `USFLD_SIZE`), `**PART3;` (the writer's own keywords), then a
  line starting `**END_OF_HEADER`. The transmit starts on the next line.
- **Keywords** are `NAME=value;`, the name 1 to 80 upper case letters, digits or
  underscores. Record breaks are not significant: a value may run on to the next
  line, and an escape may be split by one. The reference's escapes are `^n` (a
  new line), `^_` (a space), `^;` and `^^`. SOLIDWORKS writes spaces as they are
  (verified: fixtures); both read the same.
- **What a document makes of it.** Every keyword of the three parts, in order,
  is a file property named as the keyword (text); the transmit's modeller
  version follows as `modeller_version` (a number). `APPL` is the `application`:
  split at its last space when the last word starts with a digit
  (`SOLIDWORKS 2024-2024016` gives the name `SOLIDWORKS` and the version
  `2024-2024016`), otherwise all name. `USER`, unless `unknown`, is
  `fields.last_saved_by`. `DATE` stays a property only: it is the writing
  machine's local time with no zone (SOLIDWORKS writes the C `ctime` form; the
  reference shows `dd-mmm-yyyy`), so it cannot be stated as UTC and
  `fields.last_saved_utc` is null.
- **Bounds.** A header longer than `xt_header_bytes` (64 KiB) is refused with
  `limit_exceeded`; one with no end line is `damaged_file`. A record that is not
  `keyword=value` is skipped with the warning `header_unreadable`, and a value
  longer than `text_bytes` is cut (`text_truncated`).

## The transmit

- **Encodings** (verified: `docs/FORMAT.md` 10.2, the fixtures, and
  `tests/test_formats_xt.py` writing synthetic bodies in both): text, a stream of
  tokens in records of about 80 characters whose breaks are not significant, and
  neutral binary, big-endian. Both start with the transmit's own header: the
  modeller string (`: TRANSMIT FILE created by modeller version 3501251`), the
  schema key (`SCH_<modeller>_<schema>_<base>`), the highest node type and the
  user-field size. The node stream follows; its first node, index 1, is the root.
- **The head** of a document is the common header and the first 4 KiB of the
  transmit: its own header and the type of the root node. Nothing else is read
  until a tree, a scene or the bodies are asked for. Then the whole transmit is
  parsed once, at most `xt_transmit_bytes` (64 MiB) and `xt_nodes` (20 million
  nodes), and kept for the document's other reads, even when the call's time
  ran out just after the parse ended. The parse keeps the call's deadline
  (`limit_exceeded`, `seconds`): in pure Python, text parses at about 3 MB/s
  and binary at about 3.5 MB/s on real and realistic files on an idle machine,
  and a transmit of minimal nodes at 1.7 and 2.5 MB/s (see "Measured"), so a
  transmit near the byte bound can need more than the default 30 s. Once a
  parse has run out of time, a later read whose time bound is no larger is
  refused at once with the same error rather than parsing again; one with more
  time parses.
- **Units** are metres (verified: the reference; the fixtures' boxes), so
  `units.source` is `format`.
- **Refused** with `format_not_supported`, each with its `detail.rule`:
  - `schema_not_embedded`: the schema key has no base, or a base other than
    13006 (verified: the reference, "Embedded schemas"). Such a transmit's node
    layouts are in the schema file Parasolid ships, which is not public.
  - `bare_binary`: the flag `B`. The reference: data in the byte order and number
    format of the machine that wrote it.
  - `user_fields`: a `USFLD_SIZE` other than 0. The reference allows up to 16
    integer words a node; the transmit reader does not read them.
  - `unsupported_variant` (`detail.value` `deltas`): a deltas transmit, which
    holds changes to a partition rather than a model.
- **Warnings** from the parse: `layout_inferred` when a node type has a layout
  inferred from files rather than published (type 150, `docs/FORMAT.md` 10.3),
  and `trailing_data` when bytes follow the terminator. In text, record breaks
  are not significant, so bytes on a line after the terminator (a DOS
  end-of-file byte `1A`, zero padding, text) join its `0`: they are counted as
  trailing data, not read as a damaged terminator (verified: synthetic files in
  `tests/test_formats_xt.py`). A `0` followed by another digit is no
  terminator and stays `damaged_file`.

## Parts, assemblies and partitions

- **The root decides** (verified: the reference, "Assembly" and "Instance"; the
  fixtures). A BODY root is a part. An ASSEMBLY root is an assembly
  (`doc_type` `assembly`): its instances, chained from `sub_instance` by
  `next_in_part`, each place a BODY or an ASSEMBLY by a TRANSFORM, or at the
  identity when the transform is null. A WORLD root is a partition: every body or
  assembly that no instance places is a part of its own, and the document is a
  `part` (a partition holding assemblies is not seen in any file yet).
- **SOLIDWORKS writes a multi-body part as an assembly** of its bodies, each
  placed once at the identity (verified: `o12_multibody.x_b`, whose assembly
  carries SOLIDWORKS' attribute `MULTI_BODY_ID_2001`). Such a file is read as
  what it holds: an assembly whose components are the bodies.
- **The transform** (verified for the order of the operations, the reference:
  `x' = (rotation_matrix . x + translation_vector) * scale`; verified on one
  corpus assembly for the order of the nine stored numbers, rows first, as C
  stores `double[3][3]`, see "Measured"; no fixture holds a turned instance). A
  scale is kept, and a scale or a mirror is warned `non_rigid_transform`. The
  perspective vector (always null, the reference says) and the flags are not
  used.
- **What cannot be placed** is left out of the scene (`Scene.skipped`, so an
  export warns `instances_left_out`): an instance whose part is not a body or an
  assembly (`bad_reference`), a negative instance (`negative_instance`), a
  transform holding an unset value or one that is not a number
  (`non_finite_placement`), and a transform that flattens what it places to a
  plane, a line or a point (`degenerate_placement`: the determinant of the
  scaled rotation is at most 1e-9 times the cube of its size, its Frobenius norm
  over the square root of 3, a ratio that is 1 for any turn, mirror or uniform
  scale; a solid placed so has collapsed and is not closed, whatever its own
  mesh says). An assembly that contains itself, and an instance in the
  instance chains of two assemblies, are `damaged_file`.
- **Instance paths are never stored.** A few instances can place a part
  billions of times (ten levels of ten instances place 10^10 boxes in a file of
  22 KB), so the reader keeps each assembly's instances once and walks the paths
  as they are needed. The tree stops at `tree_nodes` (`truncated`) and at
  `depth` (32) levels. A scene first counts, assembly by assembly, the items it
  would place and the instances it would leave out, and refuses before placing
  any (`limit_exceeded`) when either is more than `items` (1,000,000), or when
  the nesting is deeper than `depth`. The bodies need no paths. The tree, the
  summary and the bodies of a file like that therefore come in well under a
  second, and a scene past `items` is refused as fast, however often they are
  asked; a scene within `items` costs what its items cost (see "Measured").
- **The tree** has a node per top-level part (id `1` when there is one, else `1`,
  `2`...) and a `component` node per instance path (`1.1`, `1.3.2`...), depth
  first, with the instance's placement relative to its parent and, for a body,
  its scene object. A top-level body is a `body` node, a top-level assembly an
  `assembly` node. A scene's items come in the same order.

## Names and colours

- **`SDL/TYSA_COLOUR`** (type 8001; verified: the reference's system attribute
  definitions, three reals from 0 to 1, on faces and edges; the fixtures, where
  SOLIDWORKS writes it on every face, `(202, 209, 238) / 255`). Each face shows
  its own colour, else its body's (hypothesis: the face's attribute is the more
  specific, as in the CAD systems that write both; no fixture or corpus file
  colours a body itself, so a file that does, read by a Parasolid viewer, would
  settle it). A body is drawn in the colour most of its faces show, the first
  met on a tie, and with no colour when most show none; when its faces do not
  all show one colour, uncoloured faces included, `colors_ignored` says so
  (verified: `tests/test_formats_xt.py`). A body with no faces takes its own
  colour. Edge colours, and values out of range, are not used. Per-face colours
  are not kept (a body is one object of one colour).
- **`SDL/TYSA_NAME`** (type 8017; verified: the reference, a string on
  assemblies, bodies, instances and other entities) names assemblies, bodies
  and instances. SOLIDWORKS writes it empty on a multi-body part's bodies
  (verified: `o12_multibody.x_b`).
- **`SWIMPLICITBODYNAME_ID_U`**, SOLIDWORKS' own attribute, names a body when it
  has no `SDL/TYSA_NAME` (verified: its first field, unicode, equals the body
  name SOLIDWORKS reported for every fixture body, `ground_truth.json`).
- Names longer than `text_bytes` are cut (`text_truncated`). No other attribute
  is read.

## What a document gives

- `doc_type` (above), `kind` `brep`, `variant` `text` or `binary`, units metres.
  Head counts: `bodies` 1 for a BODY root, everything else null.
- `scene()` tessellates every body of the asked types once
  (`tessellate_transmit`, the call's chord, angle and time) and places each by
  every instance path that reaches it. Every body reached is one object, in node
  order, so a tree node's object index holds whatever types are asked; a body of
  another type gets an empty object and no item (`bodies_left_out`, with the
  types counted). `prefer="bodies"` (the export) gives each body's triangles
  over shared vertices, so a solid stays closed; `prefer="display"` (the 3D view
  and thumbnails) gives each face's own vertices with the surface normals. Faces
  the tessellator could not draw are in `Scene.skipped`. For an export the
  tessellator's time running out is `limit_exceeded` (`seconds`) and its
  200,000-face bound `limit_exceeded` (`max_faces`): a solid with faces missing
  is not printed. A display scene keeps the faces done instead and names the
  bound in `truncated` (`max_seconds` or `max_faces`), so a large model still
  shows, in part, and its thumbnail is marked partial; its tessellation stops 15
  percent of its time (at most 2 s) before the deadline so that the faces done
  can still be made into meshes. `max_triangles` cuts either kind short.
  Rolling blends (`BLENDED_EDGE`) are the exception to the time rule
  (`docs/API.md` 3.15): the tessellator draws them after every other face,
  leaves out those the time runs out on (reason `max_seconds`) rather than
  stop. An export's scene has their pass end a tenth of its time (at most 2 s)
  before its deadline, so that its meshes can still be made, and keeps them out
  as faces not drawn: a 3D print is made with a hole there, as for a SOLIDWORKS
  part. A display scene names `max_seconds` in `truncated`, so its thumbnail is
  marked partial.
- `bodies()`: a part transmit's body is the parsed transmit itself. The
  bodies of an assembly or a partition are copied out with `extract_body`, the
  closure `partition_to_parts` makes (`docs/FORMAT.md` 10.4) that also cuts
  assemblies, instances and transforms, under the call's clock (verified: the
  two bodies of `o12_multibody.x_b` pass `validate()` and tessellate to the
  volumes they have in the assembly; those of the fixture partition are node
  for node what `partition_to_parts` gives). Bodies share only attribute
  definitions, so the copies hold about the transmit's own nodes: more than
  twice those and 100,000 more in all (or `xt_nodes`) is refused
  `limit_exceeded` (`xt_nodes`), so a small file whose bodies all lead into one
  long chain of nodes cannot multiply it. Whether the copies load in a
  Parasolid kernel is unknown.
- No stored preview: a thumbnail is drawn from a coarse tessellation
  (`docs/API.md` 3.21). No external references.
- STEP (`docs/API.md` 3.19): a part transmit's bodies go through the same STEP
  mapper as a SOLIDWORKS part's (`step_model` takes the document), so the viewer's
  3D Print and File > Export STEP, and `export --format step`, write it exactly
  (verified: the four fixture parts above give the solids, faces, edges and
  vertices the SLDPRT gives, and the tests' own STEP checker passes the files,
  `tests/test_viewer_formats_wiring.py`). A transmit with an assembly or
  instances, `o12_multibody.x_b` among them, is not written as STEP yet.

## Measured

- **SOLIDWORKS' exports** (verified, `tests/test_formats_xt.py`): `o02_boxA.x_t`
  and `.x_b`, `o07_boxB_h31.x_b`, `o11_curved.x_b` and `o12_multibody.x_b` read to
  the volume, area, bounding box, body count, face count and body names and
  boxes SOLIDWORKS reported (planar parts to 1e-9; `o11`, with cylinders and a
  torus, within the chord), and to exactly the triangles of the same bodies
  tessellated from the SLDPRT.
- **SolidSeas' own files** (verified, the same tests): every body of every
  fixture part, written by `solidseas parasolid` as `.x_b` and `.x_t`, reads back
  to the volume and area of the body it was written from (binary bit for bit;
  text within 1e-5, since text keeps 15 significant digits) and to the volume
  SOLIDWORKS reported per configuration.
- **Synthetic** (verified, the same tests): planes, cylinders, cones, spheres,
  tori and rational B-spline faces, written in text and binary with and without
  the common header; assemblies with nested, turned, moved, scaled and mirrored
  instances; every refusal, bound and warning above; transmits cut short at 150
  points each, and 240 with bytes changed at random, all ending in
  `damaged_file`, `limit_exceeded` or `format_not_supported` within seconds.
- **Many paths from few instances** (verified, the same tests, at the default
  bounds). Ten levels of ten instances (10^10 boxes, 21,763 bytes), 31 levels
  of two (2^31, 15,702 bytes) and two of 1,000 (10^6, 346,042 bytes): the
  summary, the tree (10,000 nodes, `truncated`) and the bodies each take under
  a second, and a scene of the first two is refused `items` at once, however
  often it is asked. Measured on the first, on a machine busy with other work:
  the summary 0.45 s and the tree 0.09 s at a peak of 54 MB, where storing the
  paths had cost the full 30 s and 1.5 GB on every read. The third places
  exactly `items` boxes, so its scene is read: its export at `print_model`'s
  300 s took 54 s at a peak of 1.07 GB (137 s and 1.9 GB when the paths were
  stored), and its scene at the default 30 s still runs out of time, the core's
  check of every placement being most of the cost.
- **Bodies sharing nodes** (verified, the same tests): a partition of 806,820
  bytes whose 100 bodies all lead into one chain of 20,000 points is refused
  `xt_nodes` in 1.9 s at a peak of 87 MB, where copying 2,000,100 nodes had taken
  12 to 17 s past a 2 s bound and 474 MB.
- **Parse time.** On an idle machine text parsed at 2.9 MB/s on a realistic
  synthetic file of 3,400 bodies (21 MB), and the corpus' text files at 3.1 to
  4.0 MB/s; binary at 3.5 MB/s. A transmit of minimal nodes is the slowest per
  byte: 66,892,984 bytes of text took 39.6 s (1.7 MB/s) and 66,060,293 of
  binary 26.7 s (2.5 MB/s), at peaks of 1.8 and 1.9 GB. With the parse keeping
  the deadline, both now stop at 30.3 and 30.4 s (peaks 0.8 and 0.9 GB), and
  the next read with the same bound is refused at once. The clock's tick costs
  0.1 to 0.2 microseconds a node, under 1 percent of a realistic parse and
  about 3 percent of a parse of minimal nodes.
- **The corpus** (verified, `tests/test_formats_xt_corpus.py`, numbers only).
  The 299 folders of the development corpus hold 5 Parasolid files, all `.x_t`
  with a common header. 4 heads read (2 parts, 2 assemblies) in 0.02 s at most,
  the largest file's included. 3 read and tessellated: 31 bodies, 6,125 of 6,282
  faces done (the 157 left out are surface types the tessellator does not draw
  yet: blend surfaces, `BLENDED_EDGE`, and one torus form), 78 placed
  instances, 360,217 triangles; every body extracted by `bodies()` passes `validate()`. Over three
  runs, two files read at a time, a scene took about 2 s, 3 to 4 s and 28 to
  35 s: the slowest, 29 bodies in 78 instances, is at the default 30 s, and its
  export at the print chord took 45 to 60 s, past `print_model`'s default.
  None of the three exports is closed, because of the faces left out. Their
  thumbnails are drawn in 14 s at most, the slowest one partial. One file is
  refused `schema_not_embedded`, and one larger than `xt_transmit_bytes` lists
  but is refused `limit_exceeded` when read. No file changed while it was read.
  Read again once instance paths were no longer stored, the three give the
  same trees, body colours, placed items, counts and bodies, node for node;
  only the order of the items changed, to the tree's. Their colour attributes
  sit on faces (every face) and edges, never on a body, and `bodies()` copies
  1.001 times the transmit's nodes. Read again once rolling blends were drawn
  (`docs/API.md` 3.15), on a machine busy with other work: 6,280 of the 6,282
  faces are done, the 2 left out blend faces whose fit failed (`fit_failed`);
  369,648 triangles, and 2 of the 3 exports closed. The part with
  blends took 38 s for its scene (3 to 4 s before, drawing no blend), the
  assembly 38 s, and the exports 50 to 66 s. Read again once a blend's share of
  the time was capped at 15 s: the same faces and triangles, the scenes in 28
  and 26 s, the exports in 37 to 47 s, and 2 of the 3 thumbnails partial, the
  part with blends' now too (a thumbnail's 15 s leave some of its blends out,
  which it did not say before). At the default 30 s that part's export
  scene, which had raised `limit_exceeded` at its deadline, gives 746 of its 749
  faces in 28 s, 2 blends left out for time.
- **The rotation order** (verified on one corpus assembly, 75 of its 78
  instances turned, 69 of them by a rotation that is not symmetric, so the two
  orders differ): read rows first, every placed body's box touches or overlaps
  another's; read transposed, 13 of the 76 drawn lie more than 0.5 mm from every
  other and the assembly's box diagonal grows tenfold.
