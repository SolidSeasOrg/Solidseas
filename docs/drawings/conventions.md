# Implied conventions

The code this page describes is
`tests/drawing_reconstruct.py` (the reconstruction oracle of `docs/DRAWINGS.md`
19.3) and its tests, `tests/test_drawing_reconstruct.py`. The oracle was written
apart from the planner and imports nothing from `solidseas.drawing.plan`. This
page is the reference the planner is held to: every golden and
synthetic part must give the oracle nothing missing, redundant or wrong (19.5,
check 3). Everything here is provisional until the first release, and follows
ASME practice as summarised in [standards.md](standards.md); a clause marked
(verify) is checked against a purchased copy before SolidSeas claims
conformance.

```python
from drawing_reconstruct import Coincident, Conventions, reconstruct

report = reconstruct(model, feature_set.frame, plan.dimensions, Conventions(),
                     features=feature_set, coincident=centre_lines)
report.findings          # each missing, redundant, wrong or unresolved item
report.summary()         # "targets 42, recovered 42, missing 0, ..." (the corpus sweep's counts)
```

## 1. How it works

The oracle reads the drawing's dimensions and the conventions below as linear
equations in the unknown positions and sizes of the part, fixes one origin per
frame axis at the model's value, and solves them one at a time by Gauss-Jordan
elimination: the origins first, then the implied links, then the dimensions in
the order the drawing lists them. Then:

- a target the equations leave undetermined is **missing**;
- a dimension whose equation adds nothing, because the target it locates is
  already determined through other dimensions (two independent paths, a loop),
  is **redundant**; the finding names the dimensions of the loop;
- a target determined at a value other than the B-rep's is **wrong**; the
  finding names the dimensions it was rebuilt from;
- a dimension the oracle cannot attach to the model is **unresolved**.

Values agree when they are within half the model's tolerance
(`BrepModel.tolerance`, 1e-6 of its diagonal; `Conventions.share`), angles
within 1e-7 radian (`Conventions.angle_tolerance`). A position or an anchor is
matched to the model within ten times the model's tolerance. The oracle is
deterministic (the same inputs give the same report, its findings in a fixed
order) and bounded: at most `DrawingLimits.dimensions` dimensions and
`DrawingLimits.requirements` unknowns, and a fixed amount of elimination work,
past which it raises `limit_exceeded`.

## 2. What it checks

The **targets**, all read from the B-rep, in the frame's directions (any three
square directions; a coordinate is the dot product of a model point with the
direction, so it is measured from the model's origin, not from a datum):

| Target | Recovered when |
|---|---|
| Every planar face square to a frame axis: its offset along that axis | its position is determined |
| Every round axis (an axis group of cylinders and countersink cones whose axis is a frame direction: holes, bosses, slot ends, rounds): its position along each of the other two axes | determined |
| The end of a blind hole's full diameter where a drill point or a step's cone begins | determined |
| Every cylinder's radius (one per radius per axis) and every countersink's diameter at the surface | stated (a size, section 3, or a derived R, convention 5) and determined |
| Every countersink's included angle | stated once |
| Every chamfer's two legs | stated once |
| The first member's angle of a circular or arc pattern the drawing gives a pitch circle, an angle or a step | stated once or implied (convention 8) |
| The step of an arc pattern (holes at one equal step that leave the circle open) | stated once (convention 8) |
| Every angled face square to one frame axis that is not a chamfer: its angle to the nearest principal plane | stated once |
| The same face: a line it meets a principal face on (through a sharp edge, or past one round or chamfer, a virtual sharp), along the axis across that face; any one neighbour's line will do | determined, at the model's value |

Faces outside the oracle are listed in `Report.uncovered` with a reason and are
never findings: planar faces square to no frame axis that are neither chamfers
nor angled faces it judges (`angled face`: square to no frame axis, or meeting no
principal face), round faces whose axis is not a frame direction, tori,
spheres, free-form faces and cones that are neither countersinks nor drill
points nor steps. They belong to the model-governs note in stage 1 (10.10) and
to stage 2. A chamfer is a planar face square to one frame axis, between two
planar faces square to the other two that it meets along sharp convex edges,
whose legs are under a tenth of the part's diagonal (section 9's rule).

## 3. What it reads from a dimension

A `PlannedDimension` is read by its kind and what it carries. `value` is the
model's value in metres or radians (10.8: values are exact from the B-rep),
never negative. Dimensions with `state="removed"`, datum feature symbols and
feature control frames are not read.

| Record | Read as |
|---|---|
| any kind with `axis` and two `positions` (`linear`, `ordinate`, a callout's depth line, a leader note's depth) | the distance between the two positions along the axis is `value` |
| `diameter`, `hole_callout`, `leader_note` without positions | a diameter |
| `radius`, or a `leader_note` whose `prefix` ends in the symbol R | a radius |
| `diameter` naming a circular or arc pattern, with `radius` the pitch circle's radius | the pitch circle's diameter |
| `angle` without `axis` naming a pattern, with `radius` the pitch circle's radius | an arc pattern's step, with `nX` the count of spaces |
| `angle` without `axis`, otherwise | a countersink's included angle |
| `angle` with `axis` | a circular or arc pattern's first angle, from that frame axis |
| `chamfer` | a leg: both legs (a 45 degree chamfer) without `axis`, else the leg along `axis` |
| `datum_feature`, `frame` | not read |

**Which way.** A linear dimension takes its size from `value` and its sense
from its positions: the second position lies on the side its attach point
says. So a wrong value moves the far end, and a wrong attach point is
unresolved.

**Positions.** `Position.value` is the coordinate of the attach point along the
frame axis, in model metres, as above. `features` names the feature ids the
position stands for (C16).

- `centre=False`: a planar face square to the axis at that value among the
  named features' faces; failing that, the end of a hole's full diameter;
  failing that, a tangent extreme of a named round (its axis plus or minus its
  radius).
- `centre=True`: the axis of a named round at that value; the centre of a named
  circular pattern; the centre plane of two parallel faces of the named feature
  that lie either side of the value (the widest such pair). Every one of these
  that matches is taken (see convention 3).

**Sizes.** A size names its features and carries `radius`, the radius of the
round it points at (the attach geometry, so a wrong `value` stays a wrong
value), and, without `nX`, an `anchor` on the round's axis to choose among the
feature's rounds of that radius.

**Hole callouts.** A callout is one record per value it states, each naming the
hole (or the pattern): each diameter line is a `hole_callout` with the
diameter as `value` (the bore, the counterbore or spotface, the countersink at
the surface); each depth is a `hole_callout` with `axis` and two positions, the
entry face and the floor or the end of the full diameter; a countersink's
angle is an `angle` record. The count goes in `prefix` (`4X`) of every record
of a callout that sizes more than one hole.

**The feature table.** `features=` maps the ids the dimensions name to model
faces: a mapping, or a `FeatureSet`, whose features are `f-1`, `f-2`... in
recognition order (13.4), a pattern holding its members' faces. A position or
size naming an id the table lacks is unresolved. Without a table, positions
and sizes are matched by value alone, and pitches, angles and chamfers cannot
be read.

**The fillet note.** `fillet_radius=` is the radius the drawing's fillet note
states (FILLETS AND ROUNDS R3, rule 14). It states every round of that radius
that no dimension sizes, a round being told from a hole by its tangency to a face.
The note's rounds are then placed by that tangency, as a sized round is
(convention 4).

## 4. The implied conventions

Each convention is something the drawing shows without a value. They are in
our own words; the rules of `docs/DRAWINGS.md` section 22 behind them are
named. `Conventions` turns each off (the defaults are the contract), which is
how the tests show what each one carries.

1. **Square where drawn square** (rule 4; Y14.5-2018 4.1, the implied 90 degree
   angle, verify). The frame's three directions are square to each other. A
   planar face square to a frame axis, and a round whose axis is a frame
   direction, are taken as exactly square or parallel to it, so each needs one
   coordinate per axis and no angle. A face or axis that is not square to the
   frame is outside the oracle in stage 1.

2. **In line** (`coplanar`; 10.2). Planar faces square to one axis at one
   offset are one position: a dimension to one locates all of them. Whether
   the drawing gives each an extension line is the planner's display check
   (R4.coincident), not the oracle's. With `coplanar=False` each face is its
   own position, and a position naming several features joins only those.

3. **Coaxial where drawn so** (`coaxial`; 10.2). Round faces on one axis line
   (one `BrepModel` axis group) are one axis: a counterbore and its bore, a
   hole through a boss and the boss, and a pitch circle and the bore at its
   centre. Holes on different axes at the same coordinate are not one
   position: the drawing joins them only by a position that names them all (an
   extension line to a centre line drawn through them) or by a `Coincident`
   (convention 9). One position that meets several axes, centre planes or faces
   at its value joins them all.

4. **Tangent** (`tangent`; 10.2's links from a centre to its tangent extremes
   by r). A planar face meeting a cylinder along a tangent edge lies at the
   cylinder's axis plus or minus its radius: a slot's walls follow its ends, a
   full-round end's centre lies midway across. A dimension to a round's extreme
   (its silhouette) is linked to the round's axis by the radius, so it locates
   the axis once the radius is stated. An overall dimension to tangent extremes
   whose centres are located elsewhere closes a loop: it is a reference or is
   not drawn (10.2).

5. **Derived radii** (`derived`; 10.1, rule 4). A full-round end is stated as
   "R" with no value: a `radius` record with `tolerance="derived"` (and `nX`
   for several). It states the round's form and adds no value: the radius is
   half the width between the two parallel faces tangent to the round on
   opposite sides, so it follows the width. A derived R on a round with no such
   pair is wrong. A valued R on a full-round end is redundant, because the
   width already gives it.

6. **Equal spacing with nX** (`equal_spacing`; rule 14, nX and never TYP;
   10.1). A `linear` or `ordinate` dimension between two members of a pattern
   with `nX` in its `prefix` is the pitch: the pattern's members lie on equally
   spaced lines square to the axis, n spaces of that pitch, and the members on
   one line share its coordinate (a grid's columns or rows). `nX` counts the
   spaces and must equal them; on a callout's depth line it counts holes. Without `nX` the dimension is only the distance between
   those two members. The members must truly be equally spaced in the model, or
   the relation is wrong.

7. **nX on a size** (rule 4: sizes once, patterns once with nX). A size with
   `nX` states n rounds and must name exactly n; a size without it must name
   one. Each round's radius is then stated once; a second statement of the same
   round is redundant.

8. **Pitch circles** (`equal_spacing`, `square`; 10.3). A diameter on a circular
   pattern (three or more members whose axes lie on one circle) is the pitch
   circle. Its members lie on it at equal steps of 360 degrees over the count,
   from the first member's angle; its centre is coaxial with any axis there
   (convention 3), else it is a position of its own. The first angle is stated
   by an `angle` record naming the pattern, with `axis` the frame axis it is
   measured from (that axis through the centre, whichever way is nearer the
   member) and `anchor` on the member it measures, on the side the member is
   drawn. It is implied, with no record, when a member lies on a centre line
   through the centre parallel to a frame axis (0, 90, 180 or 270 degrees,
   `square`). Stated and implied both, or stated twice, is redundant.

   An arc pattern is holes on one circle at an equal step that leave the rest of
   the circle open. Its first member is an end hole, and its angle is stated or
   implied as above, measured from whichever way along the axis is nearer, so
   it is never more than 90 degrees; a centre line through a hole in the middle
   implies nothing, since it would not say which way the holes run. The step is
   an `angle` record with no `axis` that names the pattern, with `radius` the
   pitch circle's radius, `anchor` on the second hole and `nX` in `prefix`
   counting the spaces. The members lie on the pitch circle from the first end,
   one step apart, running towards the hole the step is drawn to (into the arc
   when it has no anchor), as many steps as `nX` says, or one without it. `nX`
   must equal the spaces. A drawing without the step leaves the step and every
   hole past the first missing. The step is checked against the model's, and
   the holes must truly be equally spaced, or the relation is wrong.

9. **Symmetric and aligned only where drawn so** (Y14.5-2018 4.1, the implied
   zero basic dimension where axes, centre planes or surfaces are shown
   coincident, verify). The oracle never infers symmetry from the model. The
   drawing shows it by a centre line through the feature's axis or centre plane
   and the centre plane it is symmetric about, given to the oracle as
   `Coincident(axis, positions, id)`: a zero dimension across `axis` between
   each of `positions`. A boss centred on its block is located by two such
   lines and no dimension; a location dimension as well is redundant. A centre
   line through things that are not in line in the model is a wrong relation.
   `types.Plan` holds no centre items yet; the planner gives its centre lines
   to the oracle this way.

10. **The datum frame's origins** (10.2's origin; rule 13). Each frame axis has
    one origin, fixed at the model's value: the first datum, in letter order,
    whose face is a plane square to that axis or a round whose axis is square
    to it (an axis datum gives both of its cross axes). Failing that,
    `Conventions.origins` names a face; failing that, the largest face square
    to the axis, then the largest round. Every other datum face is a position
    like any other and must be located.

11. **Depths** (10.1, 10.9). A blind hole's depth is to the end of its full
    diameter, never to the drill point. A drill point's or a step's cone takes
    the drill's angle (118 degrees, practice) and is neither dimensioned nor
    checked. A pocket's depth is a dimension between its open face and its
    floor.

## 5. How dimensions count

- **Toleranced** (`block`, an explicit tolerance, MAX or MIN) and **basic**
  dimensions each give one equation and count alike, for completeness and for
  redundancy. A basic dimension's value is exact and its tolerance is in a
  frame, but a characteristic stated twice is still stated twice (rule 4), so a
  loop of basic dimensions is redundant. Under the datum scheme the baseline
  locations are basic (10.4) and form a tree from the origins like any other.
- **Reference** dimensions (`tolerance="reference"`, in parentheses) give no
  equation: they are compared with the model and are wrong when they disagree.
  A size or an angle given only as a reference is not stated, so its target is
  missing.
- **Derived** radii state a form and give no value (convention 5).
- **Implied links** (conventions 2 to 9) give equations that never count as
  redundant themselves; a dimension that closes a loop through them is
  redundant. Each implied link must hold for the model's own values; one that
  does not is a wrong relation.
- **Sizes** (Ø, R, countersinks, chamfers) count once per round, per countersink
  and per chamfer leg. The oracle checks geometry: the duplicate check on
  requirement keys (R4.redundant) is the planner's graph's.

## 6. The report

`Report.findings` holds `Finding` records: `kind` (`missing`, `redundant`,
`wrong`, `unresolved`), `what` (`plane`, `axis`, `end`, `extreme`, `centre`,
`radius`, `angle`, `leg`, `count`, `relation`, `dimension`), the frame `axis`,
the model `faces`, the `dimensions` involved, words, and the model's value
(`expected`) and the rebuilt one (`found`) where there are values. A wrong
count (`nX` against the model) is a `wrong` finding of `what="count"`.
`Report.targets` and `recovered` count the targets and those rebuilt at the
model's value; `origins` says where each axis's origin is; `uncovered` lists
the faces outside the oracle. `Report.counts()` and `summary()` give numbers
only, which is what the corpus sweep prints (20.3).

## 7. What the oracle does not check

Views, visibility and true shape (R5), layout (R11), callout grammar and
threads (R7), tolerance values and precision (R2, R3), notes other than the
fillet note's radius, datum symbols and frames (R18), and requirement keys. Stage 2 brings angled faces square to no
frame axis, inclined holes and auxiliary views, tori, spheres and turned
profiles; until then they are `uncovered`.

## 8. What the planner must give the oracle

- `PlannedDimension.value` in model metres or radians; `positions` with the
  attach points' coordinates along the frame axis and the feature ids they
  stand for; sizes with `radius` and, without `nX`, `anchor` on the axis.
- One record per value of a hole callout (section 3), `nX` in `prefix`.
- For a pitch circle, its diameter with `radius` the circle's radius, and the
  first member's angle with `axis` and `anchor` on that member unless a centre
  line implies it. For an arc pattern, the first end's angle the same way and
  the step as an `angle` without `axis`, with `radius` the circle's radius,
  `anchor` on the second hole and the count of spaces as `nX` in `prefix`.
- `tolerance="derived"` on "R" without a value; `"reference"` on dimensions in
  parentheses; `"basic"` on boxed ones.
- Its centre lines as `Coincident` records, and its feature table (or the
  `FeatureSet`, whose ids are `f-1`, `f-2`... in order).
- The fillet note's radius, exactly as the model has it.
