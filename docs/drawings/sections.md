# Sections and detail views

`solidseas.drawing.sections` makes full sections and detail views
(`docs/DRAWINGS.md` 8.9, 8.10). Provisional until the first release that makes
drawings.

## Full sections

`section(model, spec)` returns the section view's geometry and a reason when it
could not hatch. `spec` is a `ViewSpec` of kind `section` whose `cut` is the
plane (a point, and the normal pointing toward the viewer, the side removed);
`section_through(point, view, id, letter)` makes one replacing a view, through
a hole's axis for example.

1. **Cut.**
   - The welded mesh is cut with the plane. Each vertex is classed by its signed
     distance, zero or more counting as the removed side everywhere.
   - Each crossing is keyed by the mesh edge it lies on, and pieces are chained
     from where a triangle leaves the removed side to where it enters it.
   - On a closed mesh every loop closes without joining by tolerance.
     `cut(model, point, normal)` returns the loops and whether all closed.
2. **Snap.** Each loop is split by the face it crosses, and each piece is
   drawn as the exact intersection where one has a closed form:
   - a plane, or a cylinder or cone whose axis lies in the cutting plane, gives
     straight lines;
   - a cylinder, cone or sphere square to the plane gives a circle of its exact
     radius at the plane;
   - anything else gives the polyline.
3. **Hatch.** Thin parallel lines at 45 degrees are clipped to the loops by the
   even-odd rule, 3 mm apart at full size (layout respaces them for the scale).
   The angle turns to 135, 30, 60, 120 or 150 degrees when an outline runs
   within 2 degrees of it.
4. **Behind.** What lies behind the plane is drawn with the view engine:
   - the occluder keeps the triangles with any vertex behind the plane;
   - the cap hides what projects inside it, except on its boundary, where an
     edge lying under the cut's outline is dropped by cleanup;
   - a section draws no hidden lines.

**When the cut fails:**
- A loop that does not close (a mesh with a face missing) refuses the hatch and
  says so; the planner then falls back to hidden lines.
- A plane that misses the part says that instead.

## Detail views

`detail(parent_geometry, spec, centre, radius)` clips the parent view's runs to
the circle, in the parent's view coordinates:

- segments exactly;
- arcs by angle;
- other entities as polylines.

It keeps the centre marks inside. Layout scales and places the detail, and draws
the circle and letter on the parent.

## Not yet

Choosing when a section is needed belongs to the planner:

- stepped bores, internal grooves and holes ending in another bore;
- hidden lines for one blind feature instead of a section.

Half sections, removed sections, broken views and broken-out sections are
stage 2.
