# Feature recognition

`solidseas.drawing.features.recognise(model, frame_hint=None, *, limits)` turns a
`BrepModel` into a `FeatureSet` (`docs/DRAWINGS.md` 6.4 and 9), from the face
graph and the edge samples alone. Provisional until the first release that makes
drawings.

## Order

The recognisers run in a fixed order, and each claims the faces it explains so
the next does not take them again:

1. the frame and datums;
2. face grooves;
3. holes and bosses;
4. patterns of the holes;
5. slots;
6. pockets and their depths;
7. widths;
8. steps;
9. blends;
10. chamfers;
11. angled faces;
12. the accounting.

The features come out in a fixed order too, which is the order a drawing gives
their ids in: holes first, so a pattern's members are their indices in the set,
then patterns, bosses, grooves, slots, pockets, widths, steps, blends, chamfers
and angled faces, each sorted by position.

Last, `FeatureSet.turned` holds the part's turned profile when it looks turned or
mixed, else None ([turned.md](turned.md)). It claims no face: the features above
are the same whatever the part is, and a turned drawing plans from them and the
profile together.

## What each recogniser finds

| Feature | Rule | Values |
|---|---|---|
| Frame | the model axes when the largest planar faces are square to them, else the frame of those faces | directions, extents |
| Datums | A the largest planar face; B the largest square to A; C the largest square to both; between equal faces, the one on the low side of its axis | face, reason in words |
| Hole | concave revolved faces on one axis, joined through planar shoulders and flat bottoms bounded only by the hole's own walls; complete when the smallest bore leaves no gap over 31 degrees; partial above 180 degrees of cover | segments from the entry (a cone's included angle in radians, like every angle of the set), kind, ends, full-diameter depth, entry face and its kind, entry break, cover, thread candidates, needs auxiliary |
| Boss | a convex complete cylinder | axis, diameter, length |
| Pattern | equal holes (kind, every segment, depth, through, direction) split into the largest pitch circle (four members or three equally spaced) or arc (holes on one circle at an equal step that leaves the circle open: four or more, or three round the axis of another hole or a boss), then rows at an equal pitch, then a grid, a pair or scattered holes | members in order (round a pitch circle from a hole on a centre line when one is; an arc's from one end to the other, starting from the end on a principal axis when only one is), pitches, counts, pitch circle, step, first angle |
| Groove | an annular floor between a concave outer and a convex inner wall | inner and outer diameter, width, depth, the face it opens on |
| Slot | two concave half cylinders (150 to 210 degrees) of one radius joined by two tangent walls 2r apart | width, centre distance, ends, direction, depth or through |
| Pocket | a planar floor whose sharp edges are all concave | floor, walls, depth from the open face, corner radius, open sides |
| Depth | each pocket's and blind slot's depth as its own record (C11) | floor, open face, axis, value, owner |
| Width | antiparallel planar faces square to a frame axis, footprints overlapping, facing each other directly (rays from one meet the other first over half the samples) | the pair, material or gap, role, size, overlap, symmetric about the envelope |
| Step | a planar face square to a frame axis with concave and convex edges | face, axis, offset |
| Blend | a curved face with two tangent edges to different faces, not part of a hole, slot or groove | radius (exact for cylinders, tori and spheres, else from the chord and the turn of the normal), fillet or round, derived full-round end |
| Chamfer | a narrow planar face between two planar faces at angles summing to 90 degrees, both long edges convex; or a complete convex cone of 20 to 70 degrees | legs, angle, planar or conical |
| Angled face | a planar face square to no frame axis | angle to the nearest principal plane; meet line with the neighbouring principal face whose normal is nearest its own (the larger of two as near; never one square to it, which meets it at 90 degrees); virtual sharp when a blend or chamfer lies between |

Hole classification, from the entry:

- **Counterbore:** a bore ending on a planar shoulder.
- **Spotface:** a counterbore 1 mm deep or less.
- **Countersink:** a cone at the entry of 60, 82, 90, 100, 110 or 120 degrees
  included (within 1 degree).
- **Stepped:** a change of diameter through a cone.
- **Tapered:** another cone at the entry.

Combinations are joined by `+`. A cone of 118 degrees (within 6) closing the far
end is a drill point, a segment rather than a kind. An entry cone or a torus round
whose leg is 0.5 mm or less belongs to the hole as its entry break (C12).

The ends are as follows:

- **Blind:** ended by a flat bottom or a drill point.
- **Into a bore:** the hole meets another hole's wall.
- **Open:** a point just past the end lies outside the solid.

The entry is the open end; of two open ends, it is the wider, or the one toward
the frame axis's positive direction.

## Widths against the envelope (C10, a decision still open)

Section 9 ranks pairs by overlap share and then by the smaller width. On the
slice's pocketed block that took the walls beside a pocket as material widths and
refused the envelope, which then closed a loop. The recogniser implements the
slice's answer until the VM settles it:

1. the envelope ranks first, then spaces, then material, smaller first within
   each;
2. a material pair touching only one envelope extreme is two positions, not a
   width;
3. the envelope is still a width when its faces do not face each other directly
   (a boss on a block).

A slot's walls are the slot's, not a width.

## Accounting

Every face is claimed by a feature, or is a position (a planar face square to a
frame axis that no feature claims, located by the plan), or is unclaimed with its
reason:

- `free_form`: B-spline, swept, spun, offset and rolling-blend faces;
- `needs_auxiliary`: holes off the frame's axes or entering an angled face (stage
  1 lists them);
- `skipped`: faces the tessellator left out;
- `unrecognised`: anything else;
- `model_defined`: added by the planner, not recognition, for the faces of what a
  key-dimensions drawing leaves to the model (`dimensions.md`).

Coverage counts features, faces and area, and anything unclaimed makes a
reduced-dimension drawing with the model-governs note. The warnings say how many
faces of each kind are defined by the model.

## Point in solid

Ends and widths ask whether a point lies inside the solid and which face a ray
meets first. A ray index bins the triangles on the plane square to a direction,
so each query looks at one cell's triangles (C9).

## Threads and hints

**Thread candidates** come from the tap drill, clearance (ISO 273) and major
diameter tables of `standards.py`. A simple hole carries the designations its
diameter is the tap drill of. Nothing becomes a thread until the user confirms
it.

**KeyWords values** rank alternatives by value only (`hints.matches`,
`hints.rank`); they never supply a value.

## Measured

On the synthetic parts recognition takes 1 to 35 ms, within the corpus median of
7 ms in most cases; the design's cap is 20 s (`seconds_features`). The corpus
sweep on the PC measures it on real parts (section 20.3).

## Not built here

- **Cross holes and manifold passages.** The synthetic parts builder makes no
  intersection curves, so no test part has an `into_bore` end yet. A cross hole
  entering a cylinder and a passage ending in a cross bore wait for a builder
  that makes them.
- **Turned profiles** are recognised ([turned.md](turned.md)); what they do not
  recognise yet (flats, keyseats and holes across the axis as turned features) is
  listed there.
- **Rolling-blend radii** come in stage 4. Until then those faces
  are blends whose radius is estimated, or free-form faces when they do not
  qualify.
