# Datums and geometric tolerances

`solidseas.drawing.plan.gdt` (`docs/DRAWINGS.md` 10.5). Provisional until the
first release that makes drawings.

## The datum scheme

The default for machined parts (the user's answer to Q1):

- Datum feature symbols A, B and C go on the datum faces the features stage
  chose (the largest planar face, the largest square to it, the largest square to
  both; between equal faces the one on the low side of its axis). Each is drawn
  in a view where its face is a visible line, the front first, as a filled
  triangle on the face's line, a short leader and the letter in a square box.
  When that view has no clear spot for it, the next view showing the face as a
  line takes it (`docs/drawings/layout.md`, Placement).
- Locations of holes, slots, bosses, widths and steps from the datums are basic
  (boxed) and show the places they need.
- Each hole callout carries one position frame: Ø, the Settings value for its
  role (clearance, or tapped when a thread is confirmed), at MMC by default, to
  A, B and C. A pattern's callout carries one frame for the group. A boss's
  diameter and a slot's width carry one too.
- Sizes keep their own tolerance from the block.
- One general note gives every surface not otherwise controlled a profile of a
  surface to A, B and C: `UNLESS OTHERWISE SPECIFIED, ALL SURFACES` followed by
  the frame.

## Plus/minus

An option per drawing, and the default for printed parts: locations are
toleranced by the block and no frames are drawn. When the drawing needs a
model-governs note, datum symbols A, B and C are drawn anyway so the note can
name them (`gdt.draws_datums`).

## Values

Frame values are kept in metres like every other value: `FrameCell.value` is
the zone in model metres, and `gdt.zone_text` shows it in the drawing's unit to
the places it needs, at least three in inches and one in millimetres (`.010`,
`0.25`). `gdt.frame_item` turns a planned frame into the display list's
`FrameItem` (characteristic, zone text, Ø, modifier `mmc` or `lmc`, datums).

## The model-governs note

A reduced-dimension drawing (anything unclaimed) ends its notes with our wording
of 10.10: the model by part number, revision and short hash, that the dimensions
shown take precedence, and the undimensioned surfaces' profile to A, B and C
(the Settings' value for undimensioned surfaces when one is set, else the
general profile).

## Verify

How the general profile interacts with a planar width whose size is toleranced
separately is a verify item for the user's review of the goldens (10.5): the
default is that the size tolerance governs size and the profile governs
location. Frame and symbol proportions are verify items in
[standards.md](standards.md).
