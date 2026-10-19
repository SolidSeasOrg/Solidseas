"""Synthetic STEP files for the OCCT oracle's reader tier (``test_occt_oracle.py``).

:data:`SHAPES` are files SolidSeas' STEP reader reads correctly: every surface, edge
and topology form ``p21_writers`` writes, a sheet, several bodies and an assembly
that places one part twice. :data:`DEFECTS` reproduce, in files written by code, the
reader defects the oracle found in real files (``docs/formats/step.md``, the OCCT
oracle): each entry gives the file, OCCT's volume of it in mm^3 (None for a sheet)
and what the reader did wrong before its fix (it reads each right now). Every name and
value is invented here.
"""

from pathlib import Path

import p21_writers as W


def _part(items_fn, **kw) -> bytes:
    f, _ids = W.part_file(items_fn, **kw)
    return f.bytes()


def _sheet(f) -> int:
    return f.add(f"SHELL_BASED_SURFACE_MODEL('band',(#{W.torus_band_shell(f)}))")


def _hollow_cylinder_brep(f, r_out=8.0, r_in=5.0, h=12.0) -> int:
    """A hollow cylinder: two cylinders on one axis (their faces share a centroid), split in
    halves as SOLIDWORKS writes them, and two annular caps."""
    b = W.Brep(f)
    rims = {}
    for r in (r_out, r_in):
        for z in (0.0, h):
            c = f.circle((0, 0, z), (0, 0, 1), (1, 0, 0), r)
            rims[(r, z)] = (b.edge(c, (r, 0, z), (-r, 0, z)), b.edge(c, (-r, 0, z), (r, 0, z)))
    for r, outward in ((r_out, True), (r_in, False)):
        side = f.cylinder((0, 0, 0), (0, 0, 1), r)
        s0 = b.edge(f.line((r, 0, 0), (0, 0, 1)), (r, 0, 0), (r, 0, h))
        s1 = b.edge(f.line((-r, 0, 0), (0, 0, 1)), (-r, 0, 0), (-r, 0, h))
        (b1, b2), (t1, t2) = rims[(r, 0.0)], rims[(r, h)]
        if outward:
            b.face(side, [[(b1, True), (s1, True), (t1, False), (s0, False)]])
            b.face(side, [[(b2, True), (s0, True), (t2, False), (s1, False)]])
        else:  # the bore: its face looks at the axis
            b.face(side, [[(s1, False), (b1, False), (s0, True), (t1, True)]], same_sense=False)
            b.face(side, [[(s0, False), (b2, False), (s1, True), (t2, True)]], same_sense=False)
    ob1, ob2 = rims[(r_out, 0.0)]
    ib1, ib2 = rims[(r_in, 0.0)]
    ot1, ot2 = rims[(r_out, h)]
    it1, it2 = rims[(r_in, h)]
    b.face(
        f.plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(ob2, False), (ob1, False)], [(ib1, True), (ib2, True)]]
    )
    b.face(
        f.plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(ot1, True), (ot2, True)], [(it2, False), (it1, False)]]
    )
    return b.solid("hollow cylinder")


# Left out because OCCT cannot referee them, though SolidSeas reads them: the box whose
# bottom edges are pcurves only (OCCT removes the edges and loses a face), the box of
# composite-curve edges and the cylinder of composite rims (OCCT converts no
# COMPOSITE_CURVE edge), the cylinder whose SEAM_CURVE has no pcurves (OCCT translates
# nothing) and the assembly placed by MAPPED_ITEMs (OCCT transfers one of the two).
SHAPES = {
    "box": lambda: _part(lambda f: [W.box_brep(f)]),
    "box of B-spline edges": lambda: _part(lambda f: [W.box_brep(f, edges="bspline")]),
    "box of polyline edges": lambda: _part(lambda f: [W.box_brep(f, edges="polyline")]),
    "box of trimmed edges": lambda: _part(lambda f: [W.box_brep(f, edges="trimmed")]),
    "box of surface curves": lambda: _part(lambda f: [W.box_brep(f, edges="surface_curve")]),
    "box with a B-spline face": lambda: _part(lambda f: [W.bspline_box_brep(f)]),
    "two boxes": lambda: _part(lambda f: [W.box_brep(f), W.box_brep(f, origin=(20, 0, 0))]),
    "split cylinder": lambda: _part(lambda f: [W.cylinder_brep(f)]),
    "rational B-spline cylinder": lambda: _part(lambda f: [W.nurbs_cylinder_brep(f)]),
    "revolved cylinder": lambda: _part(lambda f: [W.revolved_brep(f)]),
    "cylinder revolved from a line trimmed against it": lambda: _part(
        lambda f: [W.revolved_brep(f, sense=False)]
    ),
    "half cylinder extruded from a trimmed circle": lambda: _part(lambda f: [W.half_cylinder_brep(f)]),
    "half cylinder extruded from a circle trimmed against it": lambda: _part(
        lambda f: [W.half_cylinder_brep(f, sense=False)]
    ),
    "periodic B-spline hoop": lambda: _part(lambda f: [W.periodic_hoop_brep(f)]),
    "cone with an apex": lambda: _part(lambda f: [W.cone_brep(f)]),
    "hemisphere": lambda: _part(lambda f: [W.hemisphere_brep(f)]),
    "sphere bounded by its seam": lambda: _part(lambda f: [W.sphere_seam_brep(f)]),
    "elliptic prism": lambda: _part(lambda f: [W.elliptic_prism_brep(f)]),
    "hollow cylinder": lambda: _part(lambda f: [_hollow_cylinder_brep(f)]),
    "plate with a hole": lambda: _part(lambda f: [W.holed_plate_brep(f)]),
    "plate with a hole stored inside out": lambda: _part(
        lambda f: [W.holed_plate_brep(f, holes_reversed=True)]
    ),
    "box with a void": lambda: _part(lambda f: [W.void_box_brep(f)]),
    "torus band sheet": lambda: _part(lambda f: [_sheet(f)], kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION"),
    # The rocket holds what the seam band and the ogive of test_formats_step.py test: OCCT
    # transfers neither of those files, whose seams carry no pcurves.
    "plate bounded by a hyperbola": lambda: _part(
        lambda f: [W.open_conic_plate_sheet(f, "hyperbola")], kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION"
    ),
    "plate bounded by a parabola": lambda: _part(
        lambda f: [W.open_conic_plate_sheet(f, "parabola")], kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION"
    ),
    "rocket made with CadQuery": lambda: (Path(__file__).parent / "generated" / "rocket.step").read_bytes(),
    "assembly placing a box twice": lambda: W.assembly_file(),
    "assembly placing a box twice, one level down": lambda: W.assembly_file(nested=True),
}


# --------------------------------------------------------------------------- the defects
def _inward_box_shell(f, size, origin) -> int:
    """A box's CLOSED_SHELL whose every face looks into the box: each plane as the box
    writes it, the face's same_sense false and its loop run the other way round, so the
    shell is consistent with itself and faces inwards."""
    b = W.Brep(f)
    W_, D, H = size
    ox, oy, oz = origin

    def P(c):
        return (ox + W_ * c[0], oy + D * c[1], oz + H * c[2])

    made: dict = {}

    def E(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = P(key[0]), P(key[1])
            made[key] = b.edge(f.line(pa, tuple(pb[i] - pa[i] for i in range(3))), pa, pb)
        return made[key], (c0, c1) == key

    sides = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
        (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
        (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
    ]
    for cs, n, x in sides:
        back = list(reversed(cs))
        b.face(f.plane(P(cs[0]), n, x), [[E(back[k], back[(k + 1) % 4]) for k in range(4)]], same_sense=False)
    return b.shell()


def _void_facing_in(f) -> int:
    """A 30 mm cube with a 10 mm cubic void, the void written as some writers do: its
    shell already faces into the void, and the BREP_WITH_VOIDS still turns it round
    (ORIENTED_CLOSED_SHELL ``.F.``). Read by ISO 10303-42 to the letter, the void
    faces into the material and adds its volume."""
    outer = W.box_brep(f, (30, 30, 30))
    outer_shell = f.lines[[i for i, _t in f.lines].index(outer)][1].split("#")[1].rstrip(")")
    void = f.add(f"ORIENTED_CLOSED_SHELL('',*,#{_inward_box_shell(f, (10, 10, 10), (10, 10, 10))},.F.)")
    return f.add(f"BREP_WITH_VOIDS('void box',#{outer_shell},(#{void}))")


def _box_with_reversed_loops(f, faces=(1,)) -> int:
    """The 10 x 20 x 30 mm box with the loops of the faces ``faces`` (0 bottom, 1 top,
    2 to 5 the sides) stored running against their face: the edges listed the other
    way round, the bound's orientation still ``.T.``."""
    b = W.Brep(f)
    size = (10.0, 20.0, 30.0)

    def P(c):
        return (size[0] * c[0], size[1] * c[1], size[2] * c[2])

    made: dict = {}

    def E(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in made:
            pa, pb = P(key[0]), P(key[1])
            made[key] = b.edge(f.line(pa, tuple(pb[i] - pa[i] for i in range(3))), pa, pb)
        return made[key], (c0, c1) == key

    sides = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
        (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
        (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
    ]
    for k, (cs, n, x) in enumerate(sides):
        order = list(reversed(cs)) if k in faces else list(cs)
        b.face(f.plane(P(cs[0]), n, x), [[E(order[m], order[(m + 1) % 4]) for m in range(4)]])
    return b.solid("box")


# label -> (file, OCCT's volume in mm^3, what the reader did wrong before its fix)
DEFECTS = {
    "void whose shell already faces into it": (
        lambda: _part(lambda f: [_void_facing_in(f)]),
        27000.0 - 1000.0,
        "the void is turned round as ISO 10303-42 says and adds its volume (bead 1)",
    ),
    "box with one face whose loop runs against it": (
        lambda: _part(lambda f: [_box_with_reversed_loops(f)]),
        6000.0,
        "the face is skipped as seam_configuration and the solid is open (bead 3)",
    ),
    "box whose every loop runs against its face": (
        lambda: _part(lambda f: [_box_with_reversed_loops(f, faces=range(6))]),
        6000.0,
        "every face is skipped and nothing is drawn (bead 3)",
    ),
}

__all__ = ["DEFECTS", "SHAPES"]
