"""``BrepModel`` against the synthetic parts' ground truth (docs/DRAWINGS.md 6.3,
19.2), and on the fixtures."""

import math

import pytest

from drawing_support import close, faces, fixture, model, part
from solidseas import open_document
from solidseas.drawing import facegraph as F
from solidseas.drawing import keys
from solidseas.drawing.limits import DrawingLimits
from solidseas.errors import SldLimitError

MM = 1e-3


@pytest.mark.parametrize(
    "name",
    [
        "hole_kinds",
        "patterns",
        "four_holes",
        "link",
        "boss",
        "step_slot",
        "angled_round",
        "inclined_hole",
        "groove",
        "sixteen_holes",
        "printed_bracket",
    ],
)
def test_every_synthetic_part_is_a_closed_model_whose_faces_all_have_surfaces(name):
    m = model(name)
    _xt, truth = part(name)
    assert m.closed is True and m.warnings == ()
    assert len(m.faces) == truth["faces"]
    assert all(f.kind != "other" for f in m.faces)
    lo, hi = m.box
    env = [hi[i] - lo[i] for i in range(3)]
    assert close(env, truth["envelope"], 1e-6)
    assert m.tolerance == pytest.approx(m.diagonal * 1e-6)
    # every face is bounded by its loops' edges and knows its neighbours
    for f in m.faces:
        assert f.loops and all(k in m.edges for lp in f.loops for k in lp)
        assert f.neighbours and f.index not in f.neighbours


def test_planes_carry_their_outward_normal_and_offset():
    m = model("four_holes")
    top = faces(m, "plane", normal=(0.0, 0.0, 1.0))
    bottom = faces(m, "plane", normal=(0.0, 0.0, -1.0))
    assert len(top) == len(bottom) == 1
    assert top[0].surface.offset == pytest.approx(10 * MM)
    assert bottom[0].surface.offset == pytest.approx(0.0)
    assert top[0].area == pytest.approx(100 * 60 * MM * MM - 4 * math.pi * (3.3 * MM) ** 2, rel=1e-3)
    assert len(top[0].loops) == 5  # the outline and four holes


def test_holes_are_concave_cylinders_on_their_axes():
    m = model("four_holes")
    _xt, truth = part("four_holes")
    cyl = faces(m, "cylinder")
    assert len(cyl) == 4 and all(f.surface.concave for f in cyl)
    for f, h in zip(
        sorted(cyl, key=lambda f: f.surface.point[0]),
        sorted(truth["holes"], key=lambda h: h["at"][0]),
        strict=True,
    ):
        assert f.surface.radius == pytest.approx(h["diameter"] / 2)
        assert close(f.surface.point[:2], h["at"][:2], 1e-12)
        assert abs(abs(f.surface.axis[2]) - 1.0) < 1e-12
    assert len(m.axis_groups) == 4


def test_hole_kinds_have_their_cones_shoulders_and_ends():
    m = model("hole_kinds")
    cones = faces(m, "cone")
    angles = sorted(round(math.degrees(2 * f.surface.half_angle)) for f in cones)
    # countersinks at 82 and 90, a 118 drill point, a 118 step
    assert angles == [82, 90, 118, 118]
    assert all(f.surface.concave for f in cones)
    shoulders = [
        f
        for f in faces(m, "plane", normal=(0.0, 0.0, 1.0))
        if len(f.loops) == 2 and f.surface.offset < 20 * MM
    ]
    assert sorted(round(f.surface.offset * 1000, 3) for f in shoulders) == [
        13.5,
        19.5,
    ]  # counterbore, spotface
    flat = [
        f
        for f in faces(m, "plane", normal=(0.0, 0.0, 1.0))
        if len(f.loops) == 1 and f.surface.offset < 20 * MM
    ]
    assert [round(f.surface.offset * 1000, 3) for f in flat] == [8.0]  # the blind flat bottom
    # each counterbore, spotface, blind and drill-point hole shares one axis
    assert len(m.axis_groups) == 8


def test_edge_kinds_follow_the_material():
    m = model("hole_kinds")
    kinds = [e.kind for e in m.edges.values()]
    # concave: the counterbore's and spotface's inner corners, the blind floor, the drill
    # point and the step's upper bore
    assert kinds.count("concave") == 5 and kinds.count("convex") == len(kinds) - 5
    slot = model("step_slot")
    tangent = [e for e in slot.edges.values() if e.kind == "tangent"]
    assert len(tangent) == 8 and all(e.curve.kind == "line" for e in tangent)
    assert all(e.kind in ("convex", "tangent") for e in model("link").edges.values())


def test_edges_carry_their_curves_samples_and_both_faces():
    m = model("link")
    circles = [e for e in m.edges.values() if e.curve.kind == "circle"]
    assert {round(e.curve.radius * 1000, 6) for e in circles} == {15.0, 6.0}
    for e in m.edges.values():
        assert len(e.faces) == 2 and e.faces[0] != e.faces[1]
        assert len(e.normals) == 2 and len(e.normals[0]) == len(e.points)
        assert e.length == pytest.approx(
            sum(math.dist(e.points[i], e.points[i + 1]) for i in range(len(e.points) - 1))
        )
        if e.curve.kind == "line":
            assert e.length == pytest.approx(math.dist(*e.ends))
    rings = [e for e in model("four_holes").edges.values() if e.ends is None]
    assert len(rings) == 8


def test_each_side_is_found_through_the_mesh_vertices():
    m = model("boss")
    for e in m.edges.values():
        for side, verts in zip(e.faces, e.normals, strict=True):
            f = m.faces[side]
            # each sample's normal on a side is that face's outward normal there
            if f.kind == "plane":
                assert all(close(n, f.surface.normal, 1e-9) for n in verts)


def test_vertices_know_the_faces_that_meet_there():
    m = model("step_slot")
    corners = [v for v in m.vertices if len(v.faces) >= 3]
    assert corners
    vf = m.vertex_faces()
    for v in m.vertices:
        assert vf[F._vkey(v.point)] == v.faces
        for key in v.edges:
            assert set(m.edges[key].faces) <= set(v.faces)


def test_boss_and_groove_walls_are_convex_or_concave_as_built():
    boss = model("boss")
    convex = [f for f in faces(boss, "cylinder") if not f.surface.concave]
    concave = [f for f in faces(boss, "cylinder") if f.surface.concave]
    assert [round(f.surface.radius * 1000, 6) for f in convex] == [15.0]
    assert [round(f.surface.radius * 1000, 6) for f in concave] == [5.0]
    assert len(boss.axis_groups) == 1  # boss and hole on one axis
    groove = model("groove")
    walls = sorted((round(f.surface.radius * 1000, 6), f.surface.concave) for f in faces(groove, "cylinder"))
    assert walls == [(10.0, True), (20.0, False), (25.0, True)]


def test_the_angled_face_and_its_round():
    m = model("angled_round")
    rounds = faces(m, "cylinder")
    assert len(rounds) == 1 and not rounds[0].surface.concave
    assert rounds[0].surface.radius == pytest.approx(5 * MM)
    angled = [f for f in faces(m, "plane") if 1e-6 < abs(f.surface.normal[0]) < 1 - 1e-6]
    assert len(angled) == 1
    tilt = math.degrees(math.atan2(angled[0].surface.normal[0], angled[0].surface.normal[1]))
    assert tilt == pytest.approx(30.0)
    assert sum(e.kind == "tangent" for e in m.edges.values()) == 2


def test_signatures_ignore_where_the_part_was_stored_but_not_its_geometry():
    a = F.from_transmit(part("four_holes")[0])
    b = F.from_transmit(part("four_holes")[0])
    assert sorted(a.signatures()) == sorted(b.signatures())
    assert keys.digest(a.signatures()) == keys.digest(b.signatures())
    assert keys.digest(a.signatures()) != keys.digest(model("sixteen_holes").signatures())


def test_a_fixture_part_and_a_multi_body_part():
    with open_document(fixture("o11_curved.SLDPRT")) as doc:
        m = F.from_document(doc)
    kinds = sorted(f.kind for f in m.faces)
    assert kinds.count("plane") == 6 and kinds.count("cylinder") == 5 and kinds.count("torus") == 1
    assert m.closed and len(m.bodies) == 1 and m.bodies[0].volume > 0
    with open_document(fixture("o12_multibody.SLDPRT")) as doc:
        multi = F.from_document(doc)
    assert [len(b.faces) for b in multi.bodies] == [6, 6]
    assert {k[0] for k in multi.edges} == {0, 1}
    assert all(multi.faces[i].body == 1 for i in multi.bodies[1].faces)
    t0, t1 = multi.faces[multi.bodies[1].faces[0]].triangles
    assert all(multi.tri_face[i] == multi.bodies[1].faces[0] for i in range(t0, t1))


def test_the_bounds_refuse_a_part_before_it_is_tessellated():
    xt, _truth = part("sixteen_holes")
    with pytest.raises(SldLimitError) as info:
        F.from_transmit(xt, limits=DrawingLimits(faces=10))
    assert info.value.detail["limit"] == "faces"
    assert F.topology_counts([xt]) == {"bodies": 1, "faces": 22, "edges": 44}


def test_quality_sets_the_chord():
    xt, _truth = part("link")
    normal = F.from_transmit(xt)
    fine = F.from_transmit(xt, quality="fine")
    assert fine.chord < normal.chord and len(fine.triangles) > len(normal.triangles)
    with pytest.raises(ValueError):
        F.from_transmit(xt, quality="best")
