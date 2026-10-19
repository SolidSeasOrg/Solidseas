# The engineer's review

The rubric of `docs/DRAWINGS.md` section 20.4. The user scores printed drawings
on their own machine; only the scores leave it, and each problem found becomes
a synthetic part in `tests/drawing_parts.py` and a bead.

Score each item 0, 1 or 2:

- **0:** wrong or missing; the drawing cannot be used as it is.
- **1:** usable after a change the reviewer can name.
- **2:** right as drawn.

| # | Item | Asks |
|---|---|---|
| 1 | Make and inspect | Could a shop make the part and inspect it from the sheet alone, without the model? |
| 2 | Views | Are these the fewest views that define the part, with the most descriptive front, and a section or detail where one is needed? |
| 3 | Origins and datums | Are the datums the faces the part is located by, and do the dimensions start from them? |
| 4 | Callouts, frames and threads | Do the hole callouts, position frames and thread notes read in the standard grammar and say what is meant? |
| 5 | Missing or extra | Is any size or location missing, given twice, or derivable without being a reference? |
| 6 | Readability | Is everything legible at the sheet's scale, clear of other annotation, with no crossing dimension lines? |
| 7 | Title block, material and finish | Are the title, number, revision, material, finish and tolerance block right and complete? |
| 8 | Notes | Are the general notes the right ones for the process, and nothing more? |

## Targets

- Every golden drawing (section 19.4) scores 2 on items 1, 4, 6 and 7.
- Eight of ten of the user's own parts score at least 1 on every item after at
  most five edits each.

## The sheet to fill in

One row per drawing. Part names may be left out; a number is enough.

| Drawing | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | Edits | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |
