"""Equal angles are stated once (docs/DRAWINGS.md 10.1): angled faces at one angle to one
principal plane, whose meet lines run along one frame axis, get one angle with its count,
nX, as equal chamfers and fillets do. Faces at one angle to different planes (slopes that
are complements of each other) keep an angle each, so none is read from the wrong plane.
Equal bosses on one axis likewise get one diameter with their count."""

import math

import drawing_parts as P
from drawing_golden_support import settings, source_stage
from solidseas.drawing import display as D
from solidseas.drawing import pipeline
from solidseas.drawing.types import AngledFace, DrawingOptions

MM = 1e-3
OPTIONS = DrawingOptions(units="mm")


def _draw(name: str, profile, height: float = 15 * MM) -> pipeline.Run:
    xt, truth = P.build(P.prism(profile, height))
    return pipeline.run(
        None, options=OPTIONS, settings=settings(), stages={"source": source_stage(name, xt, truth)}
    )


def _angles(run: pipeline.Run) -> list[tuple[str, float]]:
    dims = run.orchestrated.planned.plan.dimensions
    return sorted((d.prefix, round(math.degrees(d.value), 3)) for d in dims if d.kind == "angle")


def test_equal_angles_are_stated_once_with_their_count():
    r = 30 * MM
    hexagon = [
        (r + r * math.cos(math.radians(60 * k)), r + r * math.sin(math.radians(60 * k))) for k in range(6)
    ]
    run = _draw("hexagon", hexagon)
    assert sum(isinstance(f, AngledFace) for f in run.features.features) == 4
    assert _angles(run) == [("4X ", 30.0)]
    (need,) = [n for n in run.orchestrated.planned.detail.req.needs if n.kind == "angle"]
    assert need.count == 4 and len(need.req.features) == 4 and len(need.faces) == 4
    # its leader may start at any of the four meet lines, the first's or the others'
    assert len({need.anchor, *need.anchors}) == 4


def test_equal_bosses_are_sized_once_with_their_count():
    # four 6 mm bosses at no pattern's pitch and one of 10 mm, on a plate
    p = P.box(60 * MM, 40 * MM, 8 * MM)
    for k, (x, y) in enumerate(((8, 8), (50, 9), (12, 31), (47, 33))):
        p = P.add_boss(p, (x * MM, y * MM, 8 * MM), "+z", 6 * MM, 5 * MM, f"b{k}")
    p = P.add_boss(p, (30 * MM, 20 * MM, 8 * MM), "+z", 10 * MM, 5 * MM, "big")
    xt, truth = P.build(p)
    stages = {"source": source_stage("bosses", xt, truth)}
    run = pipeline.run(None, options=OPTIONS, settings=settings(), stages=stages)
    dims = run.orchestrated.planned.plan.dimensions
    assert sorted(d.prefix for d in dims if d.kind == "diameter") == ["4X Ø", "Ø"]
    (need,) = [n for n in run.orchestrated.planned.detail.req.needs if n.kind == "diameter" and n.count == 4]
    assert len({need.anchor, *need.anchors}) == 4  # its leader may start at any of the four


def test_a_radius_starts_on_an_arc_measured_from_that_arcs_centre():
    # two corners of R6 (the general note's radius) and two of R10, stated as 2X R10: its
    # leader starts on one of the R10 arcs, and the dimension's centre is that arc's own
    corners = [(0.0, 0.0), (60 * MM, 0.0), (60 * MM, 40 * MM), (0.0, 40 * MM)]
    run = _draw("rounded", P.rounded(corners, [6 * MM, 6 * MM, 10 * MM, 10 * MM]), 8 * MM)
    sheet = run.drawing.sheet
    (dim,) = [a for a in sheet.annotations if isinstance(a, D.Dimension) and a.kind == "radius"]
    centre, start = dim.points[:2]
    radius = math.dist(centre, start)

    def on(arc, p) -> bool:
        turn = math.degrees(math.atan2(p[1] - arc.centre[1], p[0] - arc.centre[0]))
        on_circle = abs(math.dist(arc.centre, p) - arc.radius) < 1e-3  # a micron on paper
        return on_circle and (turn - arc.start_deg) % 360.0 <= arc.sweep() + 1e-6

    arcs = [g for g in sheet.geometry if isinstance(g, D.Arc) and abs(g.radius - radius) < 1e-3]
    assert len(arcs) >= 2
    assert any(on(a, start) and math.dist(a.centre, centre) < 1e-3 for a in arcs)


def test_one_angle_to_two_planes_is_stated_for_each():
    # two slopes of 33.69 degrees, one to the horizontal and one to the vertical
    profile = [
        (0.0, 0.0),
        (60 * MM, 0.0),
        (60 * MM, 20 * MM),
        (45 * MM, 30 * MM),
        (10 * MM, 30 * MM),
        (0.0, 15 * MM),
    ]
    run = _draw("two-slopes", profile)
    assert sum(isinstance(f, AngledFace) for f in run.features.features) == 2
    assert _angles(run) == [("", 33.69), ("", 33.69)]
