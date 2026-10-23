# Turned (lathe) parts

Drawings of turned parts: stage 2's `dwg-turned` (`docs/DRAWINGS.md` 3.5, 10.5
and 10.6), as far as it is built. Provisional until the first release that makes
drawings. The drafting rules here follow ASME practice as summarised; nothing is
checked against a purchased standard yet (Q10).

## Which parts are turned

`solidseas.drawing.features.turned.turned_profile(model, frame)` reads the faces
alone and gives a `TurnedProfile` (`solidseas.drawing.types`), which recognition
keeps as `FeatureSet.turned`:

| Rule | What it does |
|---|---|
| The axis | the axis line whose faces of revolution (cylinders, cones and tori by their axes, spheres by their centres) hold the most area. It must lie along a frame axis (`frame_axis`) |
| Turned | every face of revolution is on that axis and every plane is square to it: the "looks turned" rule of 10.6 |
| Mixed | the faces on the axis and the planes square to it hold at least 80 % of the area (`MIXED_SHARE`) and other faces remain (flats, holes across the axis, keyseats, a bolt circle); `mixed` and `share` say so |
| Not turned | anything else, a part with no cylinder on the axis, and a part whose axis no frame axis runs along |
| The larger end | the end whose nearest outside cylinder is the larger; at a tie the end with the larger planar end face; then the low end of the frame axis. `axis` points from it to the other end, from a point on its plane |
| Segments | each face of revolution along the axis from the larger end: kind, start and end, diameter (a cone's at both ends), inside or out. A cylinder split into faces (seam halves) is one segment |
| Datum A | the longest outside cylindrical segment (a bore's when the part has no outside cylinder), as 10.5 asks |
| Datum B | the planar end face at the larger end, when that end is a plane |
| Reason | in words, for the wizard: "every face is a face of revolution about one axis or a plane square to it", or the share for a mixed part |

The design's prototype measured the rule on 6.9 % of sampled corpus parts (10.6);
this recogniser has not been run on the corpus yet (a PC check, 20.3).

## The drawing

A drawing of manufacturing type `turned` (`DrawingOptions.process`, the wizard's
Turned (lathe), `drawing new --process turned`) is planned by these rules; a part
with no profile is drawn by the machined rules whatever the type says.

| Item | Rule |
|---|---|
| The front | the profile view: looking square to the axis, the axis across the sheet, the larger end on the left (`plan.select.profile_choices`), the best of those by the usual score (8.2). Other views come by coverage (8.3): an end view only for what the profile cannot show, such as a bore's callout or a bolt circle |
| Datums | A and B of the profile (`features.turned.for_process`, in place of the planar datums of 9). A's symbol stands on the cylinder's outline in the profile view, apart from its size dimension, which designates its axis (verify against Y14.5) |
| Diameters | one Ø a cylindrical segment, drawn across its outline from one outline line to the other. Equal segments share their outline lines and are stated once with their count (`2X Ø16`), as the coincident-surface check (R4) asks; a datum on such a group is the segments' common axis |
| Runout | under the datum scheme each diameter carries a circular runout frame to A with Drawing Settings' runout value (`gdt.runout_in`, `.005`; `runout_mm`, 0.1 mm), but A's own (`plan.gdt.runout`) |
| Lengths | shoulders and the far end are placed from datum B by baseline dimensions toleranced by the block, not basic ones; the overall length is a size. R13.plusminus leaves these alone under the datum scheme |
| Precision | diameters and shoulders take the hole size and hole location roles: three places in inch and two in millimetres, as 10.6 asks; the overall length the envelope's |
| Other features | chamfers, fillets, face grooves, undercuts (their width and Ø) as on a machined part; a bore's callout in the end view; features off the axis of a mixed part by the machined rules, their position frames to A and B |
| Plus and minus | the scheme as an option: no datums unless a model-governs note needs them, no runout frames, R13.plusminus as for a machined part |
| Settings | a turned part takes the machined entries of Drawing Settings: Default Views, dimensioning, the tolerancing scheme, the notes (the Notes page calls them "Machined and turned parts"), materials and finishes (`types.settings_type`). The checks treat it as machined (`types.MACHINING`) |

A feature control frame under a vertical dimension's text breaks its line below
the text too (`layout.dimension.frame_room`), and the arrangement leaves that room
before it lets the text stand inside the span; a text and frame that do not fit
stand past the end of the line.

The wizard suggests Turned for a part its preview finds turned, with the reason,
until the user chooses a type ([wizard.md](wizard.md)). The `.ssdrw` keeps
`"process": "turned"` in its options; a SolidSeas older than this one reads such a
drawing as machined, with a problem listed for the option it does not know.

## Tests

`tests/turned_parts.py` revolves a profile in the (r, z) half plane into exact
Parasolid bodies: a solid shaft, a stepped shaft with a chamfer, a shoulder with a
fillet, a bored shaft, a bushing, an undercut groove and a shaft built from its small
end. `tests/test_drawing_turned.py` checks the profiles, a funnel whose only cylinder
is its bore, a flange whose bolt holes make it mixed, prismatic parts and fixtures
that are not turned, the turned drawings' views, datums, texts, frames and checks,
the plus and minus scheme, a machined drawing of a turned part, a drawing from a
`.x_t` updated after a diameter changes, and the command line.

## Not built yet

- Half sections for bores, with the one-arrowhead diameter style; a bore keeps its
  callout in an end view.
- Removed sections for keyseats, flats and cross holes, and a keyseat's depth from
  the opposite side.
- Broken views of long shafts (a length-to-diameter setting of about 8).
- Across flats on hex and square ends.
- Surface texture symbols on bearing and seal diameters.
- Tapers: a cone that is not a chamfer is left to the model, so the drawing is a
  reduced-dimension drawing.
- A clocking datum (C) for a mixed part, and the angular graph's extension to axes
  of revolution (10.3) for features across the axis.
- Choosing datum A in the wizard or the editor's window, which has no Set Datum yet.
  The library's `edit.set_datum` on another cylinder's face of a turned drawing moves
  A there: its symbol goes to that cylinder's outline, and the runout frames follow
  (the old A's diameter gains one, the new one loses its).
- Express and Guided drawings: they still start from the machined type.
- The turned goldens of `docs/DRAWINGS.md` 21 (stage 2, item 1) that need
  intersection curves or broken views (a keyseat, a flat and a cross hole at 30
  degrees, a hex end, a long shaft), and the corpus sweep of turned-style parts
  (item 5, on the PC).
