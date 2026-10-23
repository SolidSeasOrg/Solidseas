# Drawings to ISO

Status: design, 2026-10-22. `docs/DRAWINGS.md`
section 2 left ISO drawings to stage 4 (Q6); this page is that stage's design,
in slices a bead each.

SolidSeas draws to ASME practice: Y14.5-2018 for dimensioning and tolerancing,
Y14.1 for the sheet and title block, Y14.3 for views. A company that works to
ISO needs its drawings to follow the ISO system instead: ISO 8015 and the GPS
standards for what a tolerance means, ISO 5456-2 and ISO 128 for views, ISO 5457
and ISO 7200 for the sheet and its title block, ISO 129-1 and ISO 3098 for how
dimensions and text look. A switch in Drawing Settings chooses between the two.

The ISO standards are copyrighted, as the ASME ones are. What follows is in our
own words. The facts about the title block and the sheet come from the identical
Indian adoptions of ISO 7200:2004 and ISO 5457:1999 (IS 11665 and IS 10711),
which are published openly; anything not confirmed from a public source is
marked (verify) and is checked against a purchased copy before SolidSeas claims
conformance. Until then the docs say an ISO drawing follows ISO practice as
summarised, never that it conforms. Buying the standards is the user's decision,
as for ASME (Q10).

## The switch

**Drawing Settings > Standard and Units:**

- **Standard:** ASME (the default) or ISO (`standard.profile`, `asme` or `iso`).
- **Projection:** as the standard says, first angle or third angle
  (`standard.projection`: `standard`, `first` or `third`). The standard's own is
  third angle for ASME and first angle for ISO; ISO allows either (ISO 5456-2),
  and a company that draws ISO in third angle chooses it here.

`default_settings("iso")` gives the ISO defaults: profile `iso`, millimetres for
the drawing and for parts that state no unit, projection as the standard. Every
later slice adds its defaults there (sheets, general tolerances, lettering).

A drawing keeps the standard it was made to: its settings snapshot holds the
profile and the projection (section 7.4), and its options name the profile
(`options.profile`), so a released drawing reproduces as it was. Use Current
Drawing Settings changes them as it changes any setting. A SolidSeas from before
ISO opens an ISO drawing with the problems it lists (the profile it does not
draw, and the projection setting it does not know), shows the laid-out sheet as
it was saved, and would lay it out again to ASME: such a drawing is edited in a
SolidSeas that has the profile.

## What differs, and the slice that builds it

| Item | ASME (as built) | ISO | Slice |
|---|---|---|---|
| Projection | third angle (Y14.3) | first angle by default, third on request (ISO 5456-2) | 1 |
| View arrangement | top above the front, right on its right, left on its left, bottom below, back beyond the right | first angle: the view from above below the front, from below above it, from the right on its left, from the left on its right, from the rear beyond the view from the left (ISO 5456-2, which lets the rear stand at either end) | 1 |
| Projection symbol | third angle: the cone's narrow end toward its end view | first angle: its wide end toward the end view (ISO 5456-2; proportions verify) | 1 |
| What a tolerance means | Y14.5-2018, Rule #1 (the envelope) by default; DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018 in the block | the GPS system (ISO 8015): the independency principle by default, the envelope only where Ⓔ asks for it; TOLERANCING ISO 8015 in the block (wording verify) | 1 |
| Plus and minus between features | Y14.5-2018 discourages it (R13.plusminus) | the GPS system treats it as ambiguous and asks for geometrical tolerances (ISO 14405-2; verify) | 1 |
| Sheets | A to E inches, margins 0.38 and 0.50 in, zones lettered up from the bottom and numbered leftward from the right | A4 to A0 (ISO 216, ISO 5457), below | 2 |
| Title block | Y14.1 block, B to E one layout and A a compact one; a continuation block after the first sheet | ISO 7200's data fields, 180 mm wide, the same block on every size; scale, projection symbol and general tolerances beside it, not in it; below | 2 |
| Lines | thick 0.6, thin 0.3 mm | line groups of ISO 128-20 by size, 0.5 and 0.25 mm on A4 and A3, 0.7 and 0.35 mm from A2 up (practice; verify) | 2 |
| Scales | 1:2, 1:4, 1:10, 1:20; 2:1, 4:1, 10:1, 20:1 | 1:2, 1:5, 1:10, 1:20, 1:50; 2:1, 5:1, 10:1, 20:1 (ISO 5455) | 2 |
| General tolerances | the decimal block (or ISO 2768 as an option, offered in Settings and not yet applied) | ISO 2768-1 classes by size range, the decimals selecting nothing; GENERAL TOLERANCES ISO 2768-m in the block | 3 |
| General geometrical tolerance | the general profile note to A, B and C | an ISO 22081 general geometrical specification beside the title block (ISO 22081 replaced ISO 2768-2 in 2021; verify the indication) | 3 |
| Lettering | 3.0 mm, unidirectional, the value in a break of the dimension line | 3.5 mm (ISO 3098), aligned with the dimension line and above it, read from the bottom or the right (ISO 129-1) | 4 |
| Numbers | a point; inch without a leading zero | a comma by default, a point on request; always a leading zero | 4 |
| Count | `4X` | `4×` | 4 |
| View labels | SECTION A-A; DETAIL B SCALE 4:1 | A-A; B (5:1) | 4 |
| Edges | BREAK SHARP EDGES .005-.015 | the ISO 13715 edge symbol with its limits | 4 |
| Datum feature symbol | a framed letter on a leader to a filled triangle (Y14.5-2018) | the same form, the triangle filled or open (ISO 5459) | 5 |
| Feature control frames | Y14.5 compartments; frames under hole callouts | the same compartments (ISO 1101); the leader to a derived feature in line with its size dimension; theoretically exact dimensions in the same box | 5 |
| Parts list and balloons | ITEM, PART NO., DWG NO., DESCRIPTION, QTY. (Y14.34) | the item list of ISO 7573 and item references of ISO 6433 | 6 |

Nothing about which dimensions a part needs changes: the planner's requirements,
graphs, datums and schemes are the same under both, and so are the checks of
section 20.1 apart from the rows named below.

## Slice 1: the switch and the projection (the first to build)

- `settings.Standard`: `profile` takes `asme` or `iso`; `projection` takes
  `standard`, `first` or `third`; `standards.projection(settings)` gives the angle
  in force. `default_settings("iso")` as above.
- **Views.** `layout.arrange` places the projected views by the angle:
  third angle as before; first angle with the view from above below the front,
  from below above it, from the right on its left, from the left on its right and
  from the rear beyond the view from the left. The gaps, bands and centring are
  the same. A view's geometry does not change: the view from above is the same
  view; only where it stands does.
- **The symbol.** `glyphs.Pen.projection_symbol(angle=...)` and the DXF's own
  symbol draw the angle in force; the title block's `ProjectionSymbol` names it.
- **What the block says.** The tolerance block ends with the standard the
  dimensions are read by: DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018, or
  TOLERANCING ISO 8015 (`standards.interpretation(profile)`). The units
  statement and the decimal rows are the same in this slice: a company's own
  general tolerance block is ISO practice too, and ISO 2768 comes in slice 3.
- **Checks.** R1.symbol wants the symbol of the drawing's angle; R1.aligned
  wants each projected view on its parent's side for that angle; R3.tolerance
  wants the standard's statement (Y14.5 or ISO 8015); R13.plusminus names the
  standard the drawing follows.
- **The file.** `options.profile` is written from the settings, as before, and
  read back as `asme` or `iso`; anything else is a problem and ASME is used.
- **The viewer.** Drawing Settings' Standard and Units page offers both standards
  and the projection. The wizard and the editor need nothing more: they draw with
  the settings they are given.

The rest of an ISO drawing is drawn as an ASME one until its slice lands: the
sheets are A to E, the title block is the ASME one, and the text, numbers and
labels follow ASME.

## Slice 2: sheets and the title block (ISO 5457, ISO 7200)

**Sheets** (ISO 216 sizes; ISO 5457 layout):

| Size | Trimmed sheet, mm | Drawing space, mm | Grid fields, long by short side |
|---|---|---|---|
| A0 | 1189 x 841 | 1159 x 821 | 24 x 16 |
| A1 | 841 x 594 | 811 x 574 | 16 x 12 |
| A2 | 594 x 420 | 564 x 400 | 12 x 8 |
| A3 | 420 x 297 | 390 x 277 | 8 x 6 |
| A4 | 297 x 210 | 277 x 180 | 6 x 4 |

- A0 to A3 stand landscape only; A4 stands portrait only, its title block across
  the bottom of the drawing space.
- The border is 20 mm on the left, a filing margin, and 10 mm on the other three
  sides; the frame round the drawing space is a 0.7 mm line.
- Four centring marks, 0.7 mm lines on the sheet's two axes of symmetry, from
  the grid reference border to 10 mm past the frame.
- The grid reference fields are 50 mm long, counted outward from the centring
  marks, the remainder going to the corner fields; letters from the top down
  (I and O not used) and numbers from left to right, on both sides of the sheet,
  on A4 at the top and the right side only; their characters 3.5 mm, the grid
  lines 0.35 mm. ASME's zones run the other way (letters up from the bottom,
  numbers leftward from the right), so a revision's zone is read by the sheet's
  own standard.
- Trimming marks, two overlapping 10 by 5 mm rectangles, in the four corners.
- The size, such as A3, in the bottom border at the right corner.

What this touches: the sheet table and its margins (`standards.SHEETS` and
`layout.sheet`, a border wider on the left than elsewhere), the zones
(`layout.stamps.border`, the DXF's own border), the sheet choices
(`types.SHEET_CHOICES`, Drawing Settings, the wizard, the editor's Sheet and
Scale, the CLI's `--sheet`), R8.sheet, the scales offered (ISO 5455) and the line
widths by size.

**The title block** carries ISO 7200's data fields, in a block 180 mm wide (so
that it fits an A4 sheet between its 20 and 10 mm borders) in the lower right
corner of the drawing space, the same block on every size. The fields, and how
SolidSeas fills them:

| Field | Mandatory | Characters | SolidSeas fills it with |
|---|---|---|---|
| Legal owner | yes | any | the company's name and logo |
| Identification number | yes | 16 | the drawing number |
| Revision index | no | 2 | the revision (SolidSeas's letters already skip I and O) |
| Date of issue | yes | 10 | the date of release (ISO 8601); empty while unreleased |
| Sheet number, number of sheets | yes, no | 4 and 4 | `2/3` |
| Language code | no | 4 a language | the Settings' (ISO 639; `en` by default) |
| Title | yes | 25 (30 for two-byte scripts) | the title |
| Supplementary title | no | two lines of 25 | the title's second line, when it has one |
| Responsible department | no | 10 | a new company setting |
| Technical reference | no | 20 | a new company setting |
| Approval person | yes | 20 | the person who signed APPROVED |
| Creator | yes | 20 | the person who signed DRAWN |
| Document type | yes | 30 | DETAIL DRAWING or ASSEMBLY DRAWING (terms verify) |
| Classification, key words | no | any | not used |
| Document status | no | 20 | the status in the standard's words: IN PREPARATION (PRELIMINARY), UNDER APPROVAL (CHECKED), RELEASED (verify) |
| Paper size | no | 4 | the sheet's size, A3 |

- ISO 7200 keeps the title block to these fields: scale, the projection symbol,
  general tolerances and surface texture stand beside it, outside the block,
  where the drawing uses them. SolidSeas puts them in a strip above it, with the
  material, finish and mass, which ISO 7200 does not hold, and the model and its
  revision (10.10).
- A checker may be named in the title block or elsewhere: CHECKED keeps its row
  beside the creator and the approval person.
- The sheets after the first: ISO 7200 defines no reduced block. SolidSeas
  repeats the identifying fields on each (legal owner, identification number,
  revision index, date of issue, sheet n of m) and leaves out the rest (verify).
- The revision block: ISO 7200 gives the revision index alone; the table of
  revisions stays in the upper right, as ISO practice keeps one (verify).

## Slice 3: general tolerances (ISO 2768, ISO 22081)

- Under ISO 2768-1 the general tolerance of a size depends on the size range and
  the class (f, m, c, v); the number of decimals selects nothing.
  `standards.iso2768_linear`, `iso2768_radius` and `iso2768_angle_minutes` hold
  the tables already. The planner gives each dimension the block covers its band
  from them, the precision then shows the band's limits, and R2.rounding,
  R3.block and the editor's bands read that band.
- The block says GENERAL TOLERANCES ISO 2768-m (the drawing's class), the units
  statement and nothing else. ISO drawings carry the default class m.
- Drawing Settings already offer ISO 2768 for millimetre parts
  (`tolerances.mm_general`), and drawings do not apply it yet: this slice makes
  the setting take effect for ASME drawings too.
- The general geometrical tolerance: ISO 22081 replaced ISO 2768-2's classes H,
  K and L in 2021 with a general geometrical specification, a profile tolerance
  to a datum system stated beside the title block. It stands in for the general
  profile note under ISO (indication verify).
- A new single-part ISO 2768 was published in June 2026; what it changes is read
  before this slice is built (verify).

## Slice 4: lettering, numbers and labels (ISO 3098, ISO 129-1, ISO 13715)

- Dimension and note text 3.5 mm, view labels 5 mm and the identification number
  7 mm (ISO 3098; practice).
- Aligned text: the value parallel to its dimension line and above it, read
  from the bottom or the right of the sheet (ISO 129-1). ASME's unidirectional
  text, in a break of the line, stays ASME's. The layout's text boxes turn with
  the text, so collisions are found as they are now.
- The decimal sign a comma by default, a point on request (a setting); always a
  leading zero.
- The count `4×` with the multiplication sign.
- View labels `A-A` for a section and `B (5:1)` for a detail; the letters at the
  cutting plane and the detail circle as ASME's.
- The edge symbol of ISO 13715 with its limits in place of BREAK SHARP EDGES;
  the symbol is a glyph of its own (proportions verify).
- R10.text checks the heights of the standard in force.

## Slice 5: geometrical tolerancing (ISO 1101, ISO 5459, ISO 2692)

- The datum feature symbol is the same framed letter on a leader to a triangle;
  ISO 5459 lets the triangle be open, a setting.
- Feature control frames keep their compartments (ISO 1101). The leader to a
  derived feature (an axis, a median plane) ends in line with the feature's size
  dimension; to a surface, on its outline or an extension line. SolidSeas hangs a
  hole's frame under its callout, as ASME does; whether that reads the same under
  ISO is checked before this slice changes it (verify).
- Theoretically exact dimensions in a box are the basic box SolidSeas draws.
- The maximum material requirement Ⓜ (ISO 2692) on positions, as built.
- Under the independency principle a size tolerance does not control form; where
  a fit needs the envelope, Ⓔ goes after the size. Which features mate is the
  engineer's to say: the editor offers Ⓔ on a size, nothing adds it on its own.

## Slice 6: assemblies (ISO 7573, ISO 6433)

The parts list as ISO 7573's item list above the title block (item, quantity,
designation, reference number, material), and the balloons as ISO 6433's item
references. The BOM editor's columns choose the headings as they do now.

## What needs the user or the PC

- Buying the ISO standards (as for ASME, Q10).
- An engineer who works to ISO reviewing ISO drawings of the goldens, as in
  section 20.4.
- The PDF and DXF checks of section 24 on ISO sheets once slice 2 lands.
