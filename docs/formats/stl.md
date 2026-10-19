# STL

STL describes a surface as a list of triangles, each three corners and a
normal, with no unit, no shared vertices and no structure. SolidSeas reads both
of its encodings with `solidseas.formats.stl` (registry id `stl`, extension
`.stl`), the reference reader of the model-file interface (`docs/API.md`
3.20.4). Labels as in [README.md](README.md).

## Binary

- **Layout** (verified: the de facto specification, as 3D Systems published
  it with the StereoLithography Interface Specification, and the fixture
  `tests/fixtures/o02_boxA.STL` that SOLIDWORKS wrote): an 80-byte header, a
  little-endian unsigned 32-bit triangle count `n`, then `n` records of 50
  bytes: the normal and the three corners as twelve little-endian float32,
  then a 16-bit attribute.
- **Telling it apart from ASCII** (verified on the development corpus): a file
  of exactly `84 + 50 n` bytes is binary whatever its header says. 323 of the
  376 binary STL files in the corpus folders begin their header with `solid`,
  the word an ASCII file starts with, so the size rule comes first. A file
  longer than `84 + 50 n` that does not start with `solid` is read as binary,
  the bytes after the last record ignored; one shorter than its count says is
  refused (`damaged_file`).
- **The header** is free text. Its printable part (up to the first NUL)
  becomes the file property `header`.
- **Colours** (hypothesis: two conventions exist and neither is read). Some
  writers set bit 15 of the attribute and keep a 15-bit colour in the rest;
  others write `COLOR=` and four bytes into the header. Either is reported with
  the warning `colors_ignored`, and the triangles are drawn in the neutral
  colour.

## ASCII

- **Grammar** (verified: the same specification, and synthetic tests in
  `tests/test_formats_stl.py`): `solid name`, then for each triangle `facet
  normal nx ny nz`, `outer loop`, three `vertex x y z` lines, `endloop`,
  `endfacet`, and `endsolid name`. Keywords are read case-insensitively and
  lines may end in LF or CR LF.
- **Several solids** in one file each become an object, named by their `solid`
  line, placed once; the first one's name is the file property `solid`.
- **Damage**: a coordinate that is not a number, a `vertex` without three, or
  a statement STL does not have raises `damaged_file` with the line number. A
  facet with other than three corners is left out with the warning
  `degenerate_triangles_dropped`. A line longer than `stl_line_bytes` (4 KiB)
  is refused with `limit_exceeded`.

## What a document gives

- `doc_type` is `part` and `kind` `mesh`. Units are millimetres, assumed
  (`units.source` `assumed`, warning `units_assumed`): STL states none, and
  every program the corpus files came from wrote millimetres.
- `counts` from the head: a binary file's `triangles` (its count),
  `vertices` (three a triangle), one object and one item; an ASCII file's head
  says nothing, so they are null.
- The scene holds one mesh object per solid, its triangles a soup (three
  vertices of their own each), `source` `mesh`. Normals are not kept: the
  export and the renderer compute them from the corners. A corner that is not
  a finite number drops its triangle (`degenerate_triangles_dropped`).
- No stored preview: `preview.renderable` is true, and a thumbnail is drawn
  from the triangles (`docs/API.md` 3.21).
- The export welds the soup by exact coordinates before it checks that each
  object is closed, so an STL that SOLIDWORKS wrote of a solid exports closed
  again (`tests/test_formats_stl.py`).

## Measured

- **Cost.** Binary records are unpacked 8,192 at a time with one `struct`
  format: a scene of 100,000 triangles reads in 0.2 s and one of a million in
  2.4 s in pure Python on the development PC. Every triangle counts against
  `triangles` (20 million) and every vertex against `vertices`.
- **The corpus** (verified, `tests/test_formats_corpus.py`, numbers only): all
  377 STL files in the folders of the development corpus read (376 binary, 1
  ASCII), from 2,644 triangles at the median to 495,936; each exported, 268 of
  them closed once welded by exact coordinates (why the other 109 are not was
  not looked into); a read took 9 ms at the median and 1.7 s at most, an
  export 37 ms and 7 s, a rendered preview 0.11 s and 4.9 s, none cut short.
  No file changed while it was read.
