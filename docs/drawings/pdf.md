# The PDF writer

The code this page describes is
`solidseas/drawing/pdf.py` (the writer) and `solidseas/drawing/images.py` (the
narrow PNG reader for the logo). The design is `docs/DRAWINGS.md` section 12.1,
with 7.1 (the logo), 12.4 (determinism), 17.2 (hostile input) and 18 (privacy).
Provisional until the first release that makes drawings.

## What it does

```python
from solidseas.drawing import pdf

problems = []
with open("1234-001 A PRELIMINARY.pdf", "xb") as fh:
    n = pdf.write_pdf(drawing, fh, problems=problems)   # or a display.Sheet
out = pdf.to_pdf(sheet, title="PLATE, MOUNTING")         # PdfOutput(data, problems)
```

`write_pdf(drawing_or_sheet, fh, *, title=None, limits=DEFAULT_LIMITS,
problems=None)` takes a `Drawing` (it writes the drawing's `sheet`) or a
`display.Sheet`, writes PDF 1.7 to a binary file object, a page for each sheet
(one, unless an assembly's parts list goes on to more sheets, DRAWINGS.md 11.7,
when each is a page in order; one sheet gives the same bytes it always did), and returns
the number of bytes written. `solidseas.drawing.write_pdf` reaches it through
the pipeline's entry point. `to_pdf` makes the same bytes without a file and
returns them with the problems met. Anything but a drawing with a sheet, or a
sheet, is refused with `InvalidArgumentError` (`detail["parameter"]` is
`drawing`), as are a file object without `write` (`fh`), a title that is not a
string (`title`) and limits that are not `DrawingLimits` (`limits`). Nothing is
written to `fh` unless the whole file was made.

The page is the sheet. Its MediaBox is the sheet's size in points (a
millimetre is 72/25.4 points), and its content is the sheet's painted layer
replayed through `painter.paint` on a `PdfPainter`, the call the SVG reference
writer makes, so the PDF and the SVG draw the same items in the same order and
agree to a hundredth of a millimetre; the tests compare every path and every
text position of the core's sample sheet. Numbers are written in points with
three decimals (a third of a micrometre). The content stream is compressed
with FlateDecode.

- **Strokes** carry the item's width, its dash pattern (millimetres to points,
  phase 0), cap and join (0 butt or miter, 1 round, 2 square or bevel) and grey
  (0 black to 1 white). The graphics state is written only when it changes. A
  dash pattern of zeros is drawn solid, since a reader would refuse it.
- **Curves** are the painter's cubic Béziers, written as they come: arcs in
  pieces of at most 90 degrees, ellipses through their affine frame, B-splines
  of degree 3 or less exactly.
- **Fills** use the nonzero rule, as SVG's default does, with the item's grey.
- **Text** is set in the base-14 Helvetica and Helvetica-Bold with
  WinAnsiEncoding, so a PDF reader draws it from its own copy of the font and
  the widths in `fonts.py` are the widths it draws. `size` is the font size in
  millimetres. The anchor (left, centre, right on the baseline) is applied by
  the writer, shifting the start by the width `fonts.measure` gives along the
  text's direction, and rotation goes into the text matrix. Text is always
  black. A character outside WinAnsi is refused with `InvalidArgumentError`
  naming it and its code point (`detail["parameter"]` is `text`): symbols
  outside WinAnsi (every GD&T symbol, the counterbore, countersink and depth
  symbols, the diameter sign U+2300) reach the writer only as paths drawn by
  layout. Ø (U+00D8), ±, ° and the like are WinAnsi and are text.
- **Strings** in the content are literal strings with parentheses and
  backslashes escaped and every byte that is not printable ASCII as an octal
  escape, so the content stream is plain ASCII. The title in the document
  information is an escaped literal when it is printable ASCII, else UTF-16
  with its byte order mark in hexadecimal.

## Layers

Each painted layer is wrapped in `BDC /OC ... EMC` for its optional content
group; the catalog's `/OCProperties` lists the groups used, in the order below,
all on by default (`/BaseState /ON`, nothing in `/OFF`).

| Painted layer (`display.LAYERS`) | PDF group |
|---|---|
| `visible`, `hatch`, `border` | Visible |
| `hidden`, `tangent`, `phantom` | Hidden |
| `centre` | Centre lines |
| `dimensions` | Dimensions |
| `notes` | Notes |
| `title` | Title block |
| `stamp` | Stamp |

Hidden holds every thin or broken line of the part that is not a centre line,
so turning it off leaves the visible outline, which is what a reader turning
off hidden lines wants to see; the hatching of a section and the sheet's border
draw with the outline. A painted item on a layer the writer does not know is
drawn in Visible and the writer says so in its problems.

## The logo

`images.read_png(data, *, limits)` decodes only the narrow PNG of 7.1: 8-bit
RGB or RGBA, not interlaced, at most `limits.logo_pixels` (1,200) pixels a side
and `limits.logo_bytes` (512 KiB). The file's size and the header are judged
before anything else is read; every chunk's CRC is checked; the IDAT chunks
must be consecutive and are joined; the zlib stream is inflated with its output
bounded by what the header implies (`width * height * channels + height`
bytes), so a stream that would inflate further (a zlib bomb) is refused after
producing one byte more than that; the stream must end exactly there, with
nothing after it; and the five row filters (None, Sub, Up, Average, Paeth) are
undone. It returns a `PngImage`: `width`, `height`, `rgb` and `alpha` (None for
RGB).

Anything else raises `images.PngRefused`, an `InvalidArgumentError` whose
message says why and whose `detail["rule"]` names the rule broken (`not_png`,
`file_size`, `image_size`, `format`, `chunk`, `crc`, `truncated`, `pixels`,
`filter`). Refused, among others: 16-bit samples, greyscale, palette images,
interlacing, a transparency chunk (`tRNS`; only RGBA carries alpha), an
unknown critical chunk, a second header, a damaged or short stream. Ancillary
chunks (`gAMA`, `pHYs`, `tEXt` and the like) and a suggested palette in a
true-colour image are skipped unread, as the PNG specification allows, and
nothing after `IEND` is read. `images.png_problem(data)` gives the reason in
words, or None.

The writer embeds the decoded logo as an image XObject (`/DeviceRGB`, 8 bits)
placed by the `ImageRun`'s position and size, with its alpha as a soft mask
(`/SMask`, `/DeviceGray`) when the PNG had one. The same PNG painted twice is
stored once, and a page embeds at most eight distinct images. **A refused logo
is left out and the page is still written**: the reason, as "the logo was left
out: ..." with the reader's words, is in `PdfOutput.problems` from `to_pdf`,
and is appended to the `problems` list when one is passed to `write_pdf`. The
caller (the wizard, the editor, the CLI) shows it.

Speed: the reader is pure Python. Sub and Up are undone a row at a time with
whole-row integer arithmetic; Average and Paeth go a byte at a time. On the VM
a 1,200 by 1,200 RGBA logo filtered entirely with Paeth, the slowest case the
bounds allow, decodes in about 0.75 s, and with Average in about 0.45 s; a logo
of a few hundred pixels takes milliseconds. The core's sample sheet writes in
well under a millisecond.

## Metadata, privacy and determinism

The document information holds two entries:

- `/Producer`: `SolidSeas` and the library's version (`SolidSeas 0.2.83`).
  The drawing file's Save reads it to know that SolidSeas wrote a file before
  it rewrites a PRELIMINARY export (section 12.6).
- `/Title`: the `title` argument when given, else the `title` field of the
  sheet's title block, else the drawing's `title` field, with control, format
  (bidirectional overrides among them) and unassigned characters removed and
  white space collapsed, at most `limits.title_chars` (256) characters; none
  when it is empty. A longer `title` argument raises `SldLimitError`.

Nothing else: no author, creator, subject, keywords, dates or XMP metadata, and
no folder path or user name anywhere (section 18). A path or name appears only
if the sheet itself paints it as text, and then only there. There is no
`/CreationDate`: a date from the clock would make two writes of one sheet
differ, and the drawing's own dates (signatures, revisions) are in the format
the user chose and are already on the sheet.

The file identifier (`/ID`) is the first 16 bytes of the SHA-256 of the file up
to its cross-reference table, both entries the same. Objects are numbered and
written in a fixed order, so the same sheet writes the same bytes on one
machine (12.4). Across machines zlib's output may differ; the tests compare the
inflated content there, as 12.4 says.

The catalog asks readers to print at the sheet's own size
(`/ViewerPreferences << /PrintScaling /None >>`): a drawing scaled to fit the
paper measures wrong.

## Bounds and hostile input

- The file is at most `limits.output_bytes` (64 MiB); a larger one raises
  `SldLimitError` with `detail["limit"] == "output_bytes"` and nothing is
  written. A text run longer than `limits.string_chars` raises the same error
  for `string_chars`.
- A value the PDF cannot hold is refused with `InvalidArgumentError`: a number
  that is not finite, a coordinate more than 100 m from the sheet, a sheet
  larger than 200 inches a side (the largest page ISO 32000-1 allows without
  `UserUnit`), a negative width or dash, a cap or join outside 0 to 2, a font
  size of 0, an unknown anchor or font, a path that does not start with a move
  or has the wrong number of coordinates.
- Nothing active is ever written: no JavaScript, actions, `/OpenAction`, `/AA`,
  `/Launch`, `/URI`, links, annotations, forms, embedded files or outlines.
  Text that looks like PDF syntax stays a string.

## Deliberately absent

- **PDF/A** (embedded fonts, an output intent, XMP metadata) is stage 4. The
  base-14 fonts are not embedded, which PDF/A forbids and every reader accepts.
- No font embedding, kerning, `/ToUnicode` maps or tagged structure; WinAnsi
  text extracts as it is in every reader.
- No inline images, image interpolation or colour in the drawing itself, which
  is grey; the logo is the only colour on the sheet.
- One page: stage 1 draws one sheet.

## Tests

`tests/test_drawing_pdf.py` reads every file it writes back through
`tests/pdf_reader.py`, a small reader written from ISO 32000-1 for the tests:
the header, the xref table with each offset checked against its object, the
trailer, the objects and streams, FlateDecode, and the content stream as
operators with their operands, with helpers listing the text runs, paths,
optional content groups, images and the document information. The tests cover
the file's structure, the public entry point, refusals, the output bound,
metadata and privacy (a title block holding a fake path), determinism and the
identifier, text and path agreement with the SVG writer on the core's sample
sheet, anchors and rotation, text outside WinAnsi, GD&T symbols as paths,
strokes, fills and dashes, the layer groups, and the logo: good RGB, good RGBA
with its soft mask, every filter type, and twenty refused forms (16-bit,
palette, greyscale, interlaced, too large in pixels or bytes, a bad CRC,
truncated, no `IEND`, a zlib bomb with its memory measured, a short or damaged
stream, bytes after it, an unknown filter, `tRNS`, an unknown critical chunk,
split pixel data, a second header, not a PNG, empty), each with the page still
written.

## What needs the PC

Section 24, item 6: the PDFs are opened in Edge, Chrome and Acrobat Reader on
the Windows PC (the page size, the text, the layers panel listing the groups
above and turning each off, the logo's transparency) and printed to scale, with
a measured line checked on paper. That is done on the PC, not here; on the VM
the files are checked by the test reader, and were rendered with poppler while
the writer was built.
