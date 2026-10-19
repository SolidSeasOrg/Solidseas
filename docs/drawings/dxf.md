# The DXF writer

`solidseas.drawing.dxf` writes a drawing's sheet as an ASCII
DXF R2000 (AC1015) file, by hand: group codes, handles, tables, entities and
dimension blocks, in pure Python. `docs/DRAWINGS.md` section 12.2 is the design;
this page says what was built and how it reads the sheet. Provisional until the
first release.

```python
from solidseas.drawing import write_dxf

with open("1234-001 A PRELIMINARY.dxf", "xb") as fh:
    write_dxf(drawing, fh)  # a Drawing, or a display.Sheet
```

`write_dxf(drawing_or_sheet, fh, *, limits=DEFAULT_LIMITS, symbol_words=False,
units=None)` returns the number of bytes written; `dxf_bytes(...)` returns the
bytes instead. Anything but a `Drawing` with a sheet or a `display.Sheet` is
refused with `InvalidArgumentError` (parameter `drawing`). A sheet holding a
value the display list does not allow (a number that is not finite, an unknown
path operation, a dimension short of definition points, a note line that is not
text) is refused with parameter `sheet`. A file that would pass
`limits.output_bytes` raises `SldLimitError` (limit `output_bytes`). In every
refusal nothing reaches `fh`.

## What you get

- **Measuring, non-associative dimensions.** Linear, aligned, radial, diameter,
  angular and ordinate DIMENSION entities carry measured text (`<>`), so
  stretching geometry together with a dimension updates its value in
  AutoCAD-family programs and LibreCAD. Nothing is associative: moving geometry
  alone does not move the dimension. The model-driven route is the `.ssdrw`.
- **A single-size hole's Ø** is a diameter DIMENSION with its count prefix and
  THRU or depth suffix around `<>` (`4X %%c<> THRU`); counterbore, countersink,
  depth and thread lines are MTEXT beside it, where the sheet shows them.
- **Feature control frames and datum symbols** are lines and text in one block
  per annotation (`SS_FCF_1`, `SS_DATUM_1`, ...), inserted where they stand. The
  characteristic symbols are drawn as lines, so no special font is needed.
- **Basic boxes** are drawn around the measured text by the dimension's block,
  and a basic dimension carries a negative `DIMGAP`, so a program that
  regenerates it draws the box too.
- **Detail-view dimensions** carry explicit text and a per-dimension `DIMLFAC`,
  which LibreCAD shows as fixed text.
- **The PRELIMINARY stamp** is TEXT on its own layer, STAMP.
- **Strings are cleaned** of control characters and MTEXT codes are escaped.

**So far the DXF is checked only by SolidSeas' own reader.** The tests read every
file back with `tests/dxf_reader.py` (below). The audit in LibreCAD and in DWG
TrueView or the ODA File Converter, and whether SOLIDWORKS' DXF import keeps the
DIMENSION entities as measuring dimensions, are checks on the Windows PC
(`docs/DRAWINGS.md` section 24, items 5 and 3). Each is a bead of its own,
waiting on the user: the first until the user chooses to install those programs,
the second until SOLIDWORKS is free. Neither blocks the release. Until the
SOLIDWORKS check passes, the editable route inside SOLIDWORKS is the stage 3
`.SLDDRW`.

## The file

- ASCII only, every line ending in CRLF (the file is meant for Windows
  programs; every reader takes either ending, and one file never mixes them).
- The first pair is a `999` comment, `SolidSeas <version>`, which is how
  the drawing file's Save knows SolidSeas wrote a file. Then HEADER, CLASSES, TABLES, BLOCKS,
  ENTITIES and OBJECTS, and `EOF`.
- Handles are hexadecimal from 1, given out in one fixed order: the tables, their
  entries, the block records, the objects, then each block's BLOCK, entities and
  ENDBLK, then the model-space entities. `$HANDSEED` is the next one. Every owner
  (group 330) and every pointer (340, 350, 390) names a handle in the file.
- Numbers are fixed point (ten decimals, sixteen for knots and weights), never
  `-0.0` and never with an exponent. The same sheet writes the same bytes.
- HEADER: `$ACADVER` AC1015, `$DWGCODEPAGE` ANSI_1252, the extents and limits
  (the sheet at `1/scale`), `$LTSCALE`, `$DIMSCALE`, `$DIMSTYLE`, `$INSUNITS`
  (4 millimetres, 1 inches), `$MEASUREMENT` (1 metric, 0 English), `$LWDISPLAY`
  on, `$HANDSEED`.
- CLASSES: the three the objects need (`ACDBDICTIONARYWDFLT`,
  `ACDBPLACEHOLDER`, `LAYOUT`).
- TABLES: all nine. VPORT `*Active` framing the sheet; LTYPE; LAYER; STYLE;
  VIEW and UCS empty; APPID `ACAD`; DIMSTYLE; BLOCK_RECORD with `*Model_Space`,
  `*Paper_Space` and one record a block.
- OBJECTS: the root dictionary with `ACAD_GROUP`, `ACAD_LAYOUT` (Model and
  Layout1), `ACAD_MLINESTYLE` (Standard), `ACAD_PLOTSETTINGS` and
  `ACAD_PLOTSTYLENAME` (Normal, the placeholder the layers point to).

## Units and size

Model space is in the drawing's unit: `units` when given, else the drawing's
option (`in` or `mm`), else the unit its model states, else millimetres. A bare
`Sheet` is in millimetres unless `units` says otherwise.

A sheet point P (millimetres) goes to `P * unit / s`, where `s` is the sheet's
scale (sheet millimetres per model millimetre, 0.5 at 1:2) and `unit` is 1 for
millimetres or 1/25.4 for inches. For a view placed at the sheet's scale this is
exactly the view's own coordinates (`ViewPlacement.to_view`, metres) times 1000,
set at its origin's place: **views are at true size**, so a 0.1 m edge drawn at
1:2 is a 100 mm LINE, and DIMENSION entities measure their true values with
`DIMLFAC` 1. The border, title block, notes and stamp sit round the views at
`1/s` of their paper size.

A view placed at another scale (a detail) keeps the look it has on paper,
magnified against the others. Its dimensions carry their value as explicit text
and `DIMLFAC` = sheet scale / view scale (0.25 for a 2:1 detail on a 1:2 sheet)
as an `ACAD` `DSTYLE` override in the dimension's extended data, so the value
also comes out right if someone puts `<>` back.

## Layers, line types, text and dimension styles

| Layer | Line type | Weight (mm) | Holds |
|---|---|---|---|
| VISIBLE | CONTINUOUS | 0.60 | visible edges (thin lines at 0.30 on the entity) |
| HIDDEN | HIDDEN | 0.30 | hidden edges |
| TANGENT | DASHED | 0.30 | tangent edges |
| CENTER | CENTER | 0.30 | centre marks and lines |
| PHANTOM | PHANTOM | 0.30 | phantom lines |
| DIM | CONTINUOUS | 0.30 | DIMENSION entities, frames, datum symbols, callout lines |
| HATCH | CONTINUOUS | 0.30 | section hatching |
| BORDER | CONTINUOUS | 0.60 | the border and zones |
| TITLE | CONTINUOUS | 0.30 | the title block, tolerance block, projection symbol |
| NOTES | CONTINUOUS | 0.30 | notes, view labels, the plot stamp |
| STAMP | CONTINUOUS | 0.30 | the PRELIMINARY stamp |
| DEFPOINTS | CONTINUOUS | default | dimension definition points (does not plot) |

Line types carry `acad.lin`'s names and patterns: HIDDEN, DASHED, CENTER and
PHANTOM in inches for an inch drawing, and `acadiso.lin`'s millimetres (the same
times 25.4) for a millimetre one. `$LTSCALE` makes the hidden dash 3 mm on paper
at the sheet's scale (`3 / 6.35 / s`); the other patterns keep `acad.lin`'s
proportions, so a centre line's long dash is 15 mm on paper where the PDF draws
12. A painted stroke whose dashes differ from its layer's names its own line
type.

Text is TEXT or MTEXT in the `SOLIDSEAS` style (Arial, which has Helvetica's
widths; `SOLIDSEAS_BOLD`, Arial Bold, for bold runs), its height the capital
height the sheet gives it. AutoCAD's `Standard` style is there too.

There is one dimension style per unit, `SOLIDSEAS_MM` and `SOLIDSEAS_IN`, besides
AutoCAD's `Standard`: the preset's text height (3 mm, 0.12 in), arrows as long
as the text is tall, the extension gap and overrun, horizontal text in a break of
the line, decimal units with 2 places in millimetres and 3 in inches (no leading
zero in inches, trailing zeros kept), angles in decimal degrees, and `DIMSCALE`
`1/s`. A dimension whose precision differs carries `DIMDEC` (or `DIMADEC` for an
angle) as an override.

## How the sheet is read

The writer reads the semantic layer first and the painted layer for what only it
holds (`docs/DRAWINGS.md` 6.7).

**View geometry** (`Sheet.geometry`) is written exactly: LINE, ARC, CIRCLE,
ELLIPSE (its parameters, with the axes swapped when the ratio is over 1), SPLINE
(degree, knots, control points and weights as the display list holds them,
planar, rational when weighted) and LWPOLYLINE. A painted stroke on a view layer
that is the same path as a geometry primitive (within 5 micrometres, so a sheet
read back from the `.ssdrw` still matches) is not written again.

**Dimensions.** Each measuring `Dimension` is a DIMENSION on DIM with its own
anonymous block `*D1`, `*D2`, ... The block holds the painted items whose owner is
the dimension's id, replayed on layer 0 by block (lines, LWPOLYLINE, Béziers as
exact cubic SPLINEs, arrows as SOLID or a solid HATCH, text as TEXT), and the
definition points on DEFPOINTS. A dimension with nothing painted gets a block
drawn from its definition points: extension and dimension lines, arrowheads and
its text. The kinds and their definition points (`Dimension.points`, in order):

- `linear` (rotated, `angle_deg` its direction) and `aligned`: the first
  extension line's origin, the second's, a point on the dimension line;
- `radius`: the centre, the point on the arc;
- `diameter` and `hole_callout`: the point on the circle the arrow touches, the
  opposite point;
- `angle`: the vertex, a point on each side, and a point on the arc (else
  `text_at`);
- `ordinate`: the origin, the feature, the leader's end; X-type when the leader
  runs more up than across.

Other kinds (a chamfer note) are written as what the sheet painted for them, or
as MTEXT at `text_at` when nothing was painted.

The text is `prefix`, `<>`, `after`, a stacked tolerance as `\S upper ^ lower;`,
and a first suffix line that is THRU or a depth on the same line. The other
suffix lines are MTEXT on DIM beside the dimension: at the painted text run that
carries such a line (or a piece of one that the value's line lacks), else under
`text_at`, and those runs are left out of the block.

**Feature control frames and datum symbols** are one block each. The block holds
the painted items in the annotation's outline: for a frame, those in its band
(its height, from its left end at `at`) that touch it, grown along the band so a
frame painted wider than the writer measures it still comes whole; for a datum
symbol, those in its box (with room for one half as large again) or along its
leader. Painted items taken this way leave the dimension block or note they were
owned by. With nothing painted there, the writer draws the frame from its cells
(the symbol as lines, the zone with Ø and a circled MMC or LMC, the datum
letters) or the datum symbol (the letter in its box, the leader, the filled
triangle on the feature).

**Notes** whose id owns nothing in the painted layer are MTEXT on NOTES, the
number first, with inline frames inserted after each line's words and the leader
ending in an arrowhead. Painted notes are replayed as they are.

**The stamp** is TEXT on STAMP where the sheet painted it (or at `Stamp.at`);
the painted stamp items are not written again.

**Everything else painted** (border, zones, title block, notes, view labels,
hatching, centre marks) is replayed on its layer at `1/s`. Sheet furniture with
nothing painted on its layer is drawn from the semantic layer: the border and its
zones, the title block's fields, the projection symbol, tolerance and notes
blocks, view labels, the plot stamp, centre marks and lines, virtual sharps.

**The logo is not written**: a DXF image is a link to an outside file, which
would put a path in the file. The DXF holds no folder path or user name.

Positions the writer assumes, for layout to match:
`FeatureControlFrame.at` and `DatumFeature.at` are the lower left corners of the
frame and of the letter's box; a leader's first point is on the feature (where
the arrowhead or triangle goes); `Note.at` is the first line's left end on its
baseline.

## Strings

Every string goes through one cleaner:

- control characters (C0, C1, DEL, line and paragraph separators, the byte order
  mark, lone surrogates) are removed, so a typed bell or line break cannot split
  a value;
- a caret is written `^ `, the DXF form of a literal caret, so `^J` stays text;
- in MTEXT and dimension text, `\`, `{` and `}` are escaped (`\\`, `\{`, `\}`),
  so a title holding `\P` stays text; in TEXT a backslash is `\U+005C`;
- Ø, ± and ° become `%%c`, `%%p` and `%%d`; in a string that holds `%%` each
  percent sign is written `%%%`, so it cannot become a code;
- `<>` typed in a dimension's parts is split, so it cannot become a second
  measured value;
- every other character outside ASCII is written `\U+XXXX`;
- with `symbol_words`, the symbols CAD fonts lack become words: counterbore
  CBORE, countersink CSK, depth DEEP;
- a string is read to at most `limits.string_chars` characters; a TEXT or
  dimension string is cut to 250 characters and MTEXT is split into pieces of at
  most 250, never inside an escape.

## Tests

`tests/dxf_reader.py` is a test-only reader: tags, sections, tables and their
entries, blocks, entities, handles and owners, and helpers to find entities by
type and layer. It is strict about what the writer must do (ASCII, one line
ending, an even number of lines, numeric group codes, sections in order, EOF).
`tests/test_drawing_dxf.py` checks the core's sample sheet, a hand-built sheet
with a dimension of every kind, and a plan view of every synthetic part and of
the o02 to o12 part fixtures (drawn by the test, standing in for the views
stage):

- the reader reads what the writer writes, and the 999 comment comes first;
- every handle is unique, every owner and pointer resolves, `$HANDSEED` is past
  them all;
- the tables define every layer, line type, text style, dimension style and
  block used, and the line types carry `acad.lin`'s patterns;
- views at true size (a 0.1 m edge at 1:2 is 100 units), each primitive exact;
- every DIMENSION has its block with content and measured text; each kind is its
  DIMENSION type with its points; a dimension's painted items are its block;
- the hole Ø as a DIMENSION with prefix and suffix and the counterbore line
  beside it, with and without symbol words;
- basic boxes, detail-view `DIMLFAC` and explicit text, precision overrides;
- frames and datum symbols as inserted blocks, a frame painted under a
  dimension's owner taken out of that dimension's block;
- the stamp as TEXT on STAMP; furniture drawn when nothing was painted;
- injection strings (`\P`, braces, `^J`, a control character, `%%`, a non-ASCII
  name) escaped without breaking the file; long strings cut whole;
- inch drawings, determinism, a sheet through its compact form, refusals and the
  output bound.

## Requests and open items

- **The DXF audit and SOLIDWORKS' import** (above): PC beads, waiting on the user.
- **Owners in the painted layer** (for layout): the writer finds a suffix
  line beside a dimension by its text, and a frame or datum symbol by its outline.
  Both would be exact if layout gave those runs and items owners of their own
  (for instance the frame's id, which `FeatureControlFrame` does not have yet).
- **TOLERANCE entities** for frames are a stage 4 option once tested in readers;
  R12 output is stage 4.
