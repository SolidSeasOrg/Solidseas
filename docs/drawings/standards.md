# Drafting rules, ranked

This page is section 22 of `docs/DRAWINGS.md`, copied here as that section
asks, with its two corrections (rules 13 and 18). Change the rules in
both places or, once the design document is retired, here only.

The ASME and ISO standards are copyrighted. These rules are in our own words,
with clause references where we are confident of them; nothing is quoted. A
value from common practice rather than a standard is marked (practice); a
detail not confirmed from a public source is marked (verify) and is checked
against a purchased copy before SolidSeas claims conformance. The public-domain
NASA Goddard Engineering Drawing Standards Manual (X-673-64-1F, 1994), built on
the ANSI and ASME Y14 series, is the main public source for values.

**Which documents govern what (ASME profile):** sheet size, format, zones and
title block, Y14.1-2020; drawing practice, Y14.100 (a single part is a detail
drawing, Y14.24); lines and lettering, Y14.2; views, projection and sections,
Y14.3; dimensioning and tolerancing, Y14.5-2018 (its fundamental rules in
section 4.1); threads, B1.1 (Unified), B1.13M (metric) and Y14.6
(representation); surface texture, Y14.36 and B46.1; revisions, Y14.35;
reduced-dimension drawings, Y14.41; additive manufacturing, Y14.46-2022 with
ISO/ASTM 52900 (terms and process categories) and 52901 (what a buyer
specifies). The ISO profile (stage 4) uses ISO 5457, 7200, 128-2 and 128-3,
5456-2, 129-1, 8015 and 2768-1 (ISO 22081 replaced 2768-2 in 2021, and a new
single-part ISO 2768 reached publication in June 2026).

**P0: without these the drawing is wrong or misleading**

1. True orthographic projection with the profile's projection angle (third
   angle for ASME, Y14.3), views aligned with their parent at one scale, and the
   projection symbol shown.
2. A units statement once, and numbers formatted per unit: inch without a
   leading zero, its decimals tied to the tolerance; millimetre with a leading
   zero (Y14.5 section 4). Displayed values must equal the model within a
   fraction of the tolerance, or be flagged.
3. Every dimension toleranced, directly or through the general block or a note;
   only reference, MAX, MIN, stock and basic dimensions (the last with a frame)
   are exempt (Y14.5-2018 4.1). Block values are the company's choice.
4. A complete, non-redundant set: every feature's size, form and location
   determined with nothing to scale or assume, and each characteristic
   dimensioned once, a derivable one only as a reference in parentheses
   (Y14.5-2018 4.1). As a check: per axis the positions form a connected graph
   (complete) with no cycle (not redundant); sizes appear once, patterns once
   with nX.
5. Dimensions on visible geometry in true-shape views: Ø for full circles and
   cylinders, R for arcs of 180 degrees or less, hole sizes in the circular view
   by leader, turned diameters on the profile view, nothing dimensioned to a
   hidden line (Y14.5-2018 4.1; NASA 3.5).
6. A title block with company (the design activity), title, drawing number,
   revision, size, scale, sheet n of m, dates, approvals, material, finish, the
   tolerance block, the projection symbol and the governing standard (Y14.1;
   NASA 1.4).
7. Hole and thread callouts in the standard grammar: count, Ø, THRU or depth,
   the counterbore, spotface and countersink symbols, a thread designation per
   B1.1 or B1.13M with its depth; threads only after the user confirms them,
   since geometry alone cannot prove a hole is threaded (Y14.5 symbols; Y14.6).

**P1: standard-conformant presentation**

8. Sheet format: size, border, margins (A and B 0.38 in, C to E 0.50 in, NASA
   1.1; verify Y14.1-2020's A size), zones (letters up from the bottom, numbers
   leftward from the right), the title block lower right and the revision block
   upper right (Y14.1, Y14.35).
9. Line widths about 2:1, thick 0.6 mm and thin 0.3 mm at least (Y14.2 as
   publicly summarised); visible thick; hidden, centre, dimension and hatch
   thin; centre marks and axes on every round feature; visible lines win over
   hidden, hidden over centre (practice).
10. Lettering at least 3 mm (0.12 in) for dimensions and notes, larger for
    labels, title and drawing number, upper case, no squeezed or stretched text
    (Y14.2; NASA 3.3.2 forbids fitted text).
11. Dimension layout: the first dimension line at least 10 mm from the outline
    and rows at least 6 mm apart (Y14.5 figure 4-6 as publicly summarised);
    extension lines with a visible gap of about 1.5 mm and an overrun of about
    3 mm (practice); filled arrows about as long as the text height at 3:1
    (practice); shorter dimensions inside longer ones; no dimension line crosses
    another; unidirectional text; inclined leaders ending in a short shoulder,
    radial on circles; nothing crosses dimension text.
12. View choice: the fewest views that define the part; the most descriptive
    front (most true shape, fewest hidden lines, natural or machining position,
    longest dimension horizontal); principal views not labelled; sections for
    hidden internal features, detail views for small ones; preferred scales;
    labels SECTION A-A and DETAIL B SCALE 4:1; letters without I, O, Q (and X,
    after NASA 3.5.5), never reused (Y14.3; NASA 3.5).
13. Arrangement: baseline from the origins by default, chain only where
    functional, ordinate as an option, turned lengths from one datum face
    (Y14.5 section 4). Baseline limits the stack between two features to the
    sum of their two tolerances (corrected: an earlier note said baseline had no
    accumulation at all).
14. General notes for the most common fillet radius, edge breaks and the
    default finish; chamfers as `leg X angle` or two legs (practice; NASA
    title block). Never TYP for repetition: Y14.5 states repetition with nX.
15. Note sets per manufacturing type (machined; turned; 3D printed with
    process, material, layer height, build direction, post-processing,
    critical dimensions and model-governs, per Y14.46 and ISO/ASTM 52901), and
    the material and finish mapping.

**P2: later or optional** (with what this design moved into stage 1)

16. The revision block's history with Y14.35 lettering and an explicit release
    action. Moved to stage 1 (signing and revisions).
17. Dual dimensioning, off by default, primary unit first and the secondary in
    brackets, converted limits rounded inward (ISO 370 principle). Stage 4.
18. Datum feature symbols and GD&T. **Corrected:** an earlier note treated
    datums as optional drafter items; stage 1 has the minimal layer of section
    10.5 (datums A, B, C, basic locations, position on holes and slots, one
    general profile note, a frame editor), as the user decided.
19. Surface texture symbols per face (Y14.36). Stage 2, with turned parts.
20. Simplified thread graphics (stage 1 for confirmed threads), broken views
    and half sections (stage 2), hole tables (stage 4), knurls, centre holes
    and undercuts (drafter items).
21. Exact symbol proportions (the projection symbol, GD&T symbols, the ISO
    13715 edge symbol, the surface texture symbol), checked against purchased
    standards (verify).

**What "fully dimensioned" means here.** For the features the generator
recognises: every one has its size once (once per pattern with nX) and its
location once per axis from the chosen origins; every dimension is toleranced;
every dimension is on a visible edge in a true-shape view, legible at the sheet
scale and clear of other annotation; and anything not dimensioned is listed and
covered by the model-governs note. It does not promise functional correctness:
the generator cannot know which faces mate or how the part is inspected.

**ISO profile parameters (stage 4), for reference:** first angle by default
(third selectable); A4 to A0; a 20 mm left border and 10 mm elsewhere; 50 mm
zone fields; lines 0.5 and 0.25 mm (A4, A3) or 0.7 and 0.35 mm (A2 up); text
3.5 mm, letters 7 mm; aligned text above the line; count prefix `4×`; ISO 2768
class m with ISO 8015; labels "A-A" and "B (5:1)"; preferred scales 1:1, 1:2,
1:5, 1:10, 2:1, 5:1, 10:1; row spacing 7 mm, extension gap and overrun 1 and 2
mm (practice); the ISO 13715 edge symbol.

**ISO 2768-1 permissible deviations** (numeric facts, needed in stage 1 for the
millimetre ISO 2768-m option; `drawing/standards.py` holds them). Under ISO
2768 the number of decimals does not select the tolerance.

| Linear size, mm | f | m | c | v |
|---|---|---|---|---|
| 0.5 to 3 | ±0.05 | ±0.1 | ±0.2 | none |
| over 3 to 6 | ±0.05 | ±0.1 | ±0.3 | ±0.5 |
| over 6 to 30 | ±0.1 | ±0.2 | ±0.5 | ±1 |
| over 30 to 120 | ±0.15 | ±0.3 | ±0.8 | ±1.5 |
| over 120 to 400 | ±0.2 | ±0.5 | ±1.2 | ±2.5 |
| over 400 to 1000 | ±0.3 | ±0.8 | ±2 | ±4 |
| over 1000 to 2000 | ±0.5 | ±1.2 | ±3 | ±6 |
| over 2000 to 4000 | none | ±2 | ±4 | ±8 |

| External radius or chamfer height, mm | f, m | c, v |
|---|---|---|
| 0.5 to 3 | ±0.2 | ±0.4 |
| over 3 to 6 | ±0.5 | ±1 |
| over 6 | ±1 | ±2 |

| Angle, by the shorter side, mm | f, m | c | v |
|---|---|---|---|
| up to 10 | ±1° | ±1°30' | ±3° |
| over 10 to 50 | ±0°30' | ±1° | ±2° |
| over 50 to 120 | ±0°20' | ±0°30' | ±1° |
| over 120 to 400 | ±0°10' | ±0°15' | ±0°30' |
| over 400 | ±0°5' | ±0°10' | ±0°20' |
