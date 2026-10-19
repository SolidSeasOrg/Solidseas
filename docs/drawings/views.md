# Views

`solidseas.drawing.views` draws a part's views (`docs/DRAWINGS.md` 8).
Provisional until the first release that makes drawings.

- `project(model, spec, *, features=None, limits, quality)` draws one view and
  returns its `ViewGeometry`.
- `make_views(model, features, options, settings, *, limits)` draws the default
  set: front, top and right, or the views the options name, and the isometric
  when the settings or options ask for it.
- `view_frames(front, turn)` gives the third-angle frames for a front direction
  and a quarter turn.

Choosing the front and the views by coverage (8.2, 8.3) is the planner's,
which calls `project` for the views it picks.

## The engine

For a view direction `d` (from the part toward the viewer):

1. **Curves.** Every B-rep edge on the tessellator's shared samples, and every
   curved face's silhouette.
2. **Occluder.** Every triangle projected onto the view plane and binned in a
   grid of about three triangles a cell, edge-on triangles dropped.
3. **Visibility.** Points every 1/400 of the diagonal along each curve, each
   change of visibility bisected 12 times. A circle's added points are put back
   on the circle, since a point on a chord lies inside it, where the faces
   beside the edge can hide it (a sphere's rim seen along its axis).
4. **The own-face test.** A curve carries the faces whose tessellation passes
   through it: an edge's two faces and every face at its end points; a
   silhouette's face and its neighbours.
   - A hit on one of those faces counts only when the point lies more than 3
     chords behind the triangle, measured square to the triangle. A steep
     triangle beside an edge cannot hide the points its chord passes behind,
     and a curved own face hiding a hole's far rim is still found.
   - A hit on any other face counts from 1e-7 of the diagonal.
5. **2D cleanup.** Pieces shorter than 0.02 % of the diagonal are dropped. So
   is a piece lying along a kept piece of higher rank (visible before hidden,
   edges before silhouettes, longer before shorter). This removes back edges
   behind front edges, edges of faces seen edge-on, hidden lines under visible
   ones, and the far rim of a through hole seen along its axis. Lengths are
   compared to the nanometre, so pieces of equal length, such as a cone's two
   silhouette lines, keep the order they were found in on every platform
   rather than one their last bits choose.
6. **Output.** Each run keeps its source (body, the edge's or face's
   signature, the view) and the curve parameter range it covers.

A view whose visibility tests pass `visibility_queries` raises `SldLimitError`
naming that bound; `make_views` stops at `seconds_views` in all, and at `views`
views. Draft quality samples half as often.

## Silhouettes

- **Cylinders and cones, in closed form.** Find the generator angles where the
  normal is square to `d`, then clip each generator to the face through its own
  triangles in (u, v). The line is tried a period either side and a hair
  either side of itself, so a generator on the face's seam is found once.
- **Everything else, from the mesh.** Find where `n . d` changes sign across
  each triangle's corner normals, then chain the pieces by mesh edge.
  Refinement on the exact surface is not done yet; these silhouettes are
  within the chord.

## Tangent edges

Each view's setting leaves tangent edges out (the ASME default), draws them
thin, or draws them phantom. Wherever a tangent edge's common normal is square
to the view within 2 degrees, it is outline and drawn visible whatever the
setting. Without that rule o11's right view lost 10 mm (12 %) of its visible
outline; the tests check the outline is whole. The isometric draws visible
lines only, its tangent edges thin.

## Exact entities (C6)

| Run of | Becomes |
|---|---|
| a straight edge, a cylinder's or cone's silhouette | `Segment` |
| a circle square to the view | `Arc` (a whole ring: a full circle) |
| a circle in an oblique plane | `EllipseArc`, exact (major axis along N x d, ratio N . d) |
| a circle seen edge-on | `Segment` to its exact extremes |
| a whole B-spline edge | `Spline` with its control points projected |
| anything else | `Polyline` through the samples |

## Centres, axes and witnesses

**Centre marks and lines.**
- An axis seen end-on whose revolved faces cover at least 180 degrees gets a
  centre mark of its largest bore or boss.
- An axis seen side-on gets a centre line over its faces' axial extent; layout
  adds the overshoot.
- A circular pattern's pitch circle is a centre-line circle; an arc pattern's is
  the part of it from one end hole to the other, carried a third of the step
  (at most 10 degrees) past each.
- The isometric gets none.

**Also recorded:** the faces seen in true shape, the axes seen end-on and
side-on, each edge's visibility, and the virtual sharps of angled faces seen
along their meet line.

**Witnesses (C8).** Every visible straight run square to a sheet axis is a
witness at its position along that axis. `ViewGeometry.witness_at(axis,
position, tol)` answers the planner's question "is there a visible line here"
before it attaches a dimension.

## Tested against

- **Analytic oracles,** compared run by run: a plate with holes, a stepped block
  with a pocket, a cylinder on a plate, a hemisphere on a disc.
- **The fixtures** o02, o07, o11 and o12.

SOLIDWORKS' own DXF views of the synthetic parts (`docs/DRAWINGS.md` 24 item 4)
and the speed targets of 8.12 on the drawn parts (item 1) are measured on the
PC.
