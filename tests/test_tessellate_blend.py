"""Rolling blends (BLENDED_EDGE) in the tessellator, on synthetic bodies.

Before, every face on a blend was skipped (``unsupported_surface``), so a part with a
rolled fillet came out with holes in the 3D view and in the STL and 3MF of a 3D
print, and a tolerant edge beside a blend took the face next to it along. A blend is
now drawn from the rational B-spline the STEP export writes for it
(``solidseas.tessellate.blend``), its side taken from its loops, or on a blend
closed round its spine from a face it meets tangentially. These tests check what that
gives against what is known without it: exact volumes and areas, the same body with
its round on the exact torus, the canal surface the sphere sweeps, and solids closed
edge for edge in the mesh, the 3D print model and the STL and 3MF written from it; and
that what cannot be drawn is refused with its reason, never guessed.
"""

import io
import math
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter

import pytest

import xt_bodies as X
from solidseas import export
from solidseas.formats import open_model
from solidseas.formats.solidworks import parasolid as ps
from solidseas.tessellate import REASONS, tessellate_transmit

W, D, H, R_BLEND = 0.03, 0.02, 0.01, 0.002  # the filleted box
RC, HC = 0.01, 0.02  # the rounded and the tilted cylinder


def _box_exact():
    """Volume and area of the filleted box: the box less the corner the round cuts away
    (a square of side r less a quarter disc) along its length, the round's quarter
    cylinder in place of the two strips it replaces."""
    r = R_BLEND
    corner = (1.0 - math.pi / 4.0) * r * r
    volume = W * D * H - corner * D
    area = 2.0 * (W * D + W * H + D * H) - 2.0 * r * D + 0.5 * math.pi * r * D - 2.0 * corner
    return volume, area


def _rounded_exact():
    """Volume and area of the rounded cylinder (Pappus): the corner region and the quarter
    arc turned about the axis."""
    R, Hc, r = RC, HC, R_BLEND
    removed = 2.0 * math.pi * (r * r * (R - r / 2.0) - math.pi * r * r / 4.0 * (R - r) - r**3 / 3.0)
    volume = math.pi * R * R * Hc - removed
    arc = 0.5 * math.pi * r * 2.0 * math.pi * (R - r + 2.0 * r / math.pi)
    area = 2.0 * math.pi * R * (Hc - r) + math.pi * R * R + math.pi * (R - r) ** 2 + arc
    return volume, area


def _blend_faces(xt):
    """The FACE node ids of the faces on a BLENDED_EDGE."""
    out = set()
    for f in xt.nodes:
        if f.type == 14:
            s = xt.by_index().get(X.field(xt, f, "surface"))
            if s is not None and s.type == 56:
                out.add(X.field(xt, f, "node_id"))
    return out


def _numbered(xt):
    for n in xt.nodes:
        if n.type in (14, 16, 18):
            n.vals[0] = n.index
    return xt


def _closed(tris) -> bool:
    edges = Counter()
    for k in range(0, len(tris), 3):
        a, b, c = tris[k], tris[k + 1], tris[k + 2]
        edges[(a, b)] += 1
        edges[(b, c)] += 1
        edges[(c, a)] += 1
    return all(edges.get((b, a), 0) == n == 1 for (a, b), n in edges.items())


# --------------------------------------------------------------------------- whole bodies
def test_a_filleted_box_comes_out_closed_with_its_volume_and_area():
    xt = X.filleted_box()
    volume, area = _box_exact()
    errors = []
    for chord in (1e-4, 1e-5, 2e-6):
        t = tessellate_transmit(xt, chord_m=chord)
        assert t.closed is True and t.skipped == () and t.truncated == ()
        m = t.measures()
        assert m["volume"] == pytest.approx(volume, rel=2e-4)
        assert m["area"] == pytest.approx(area, rel=2e-4)
        errors.append(abs(m["volume"] / volume - 1.0))
    assert errors[2] < errors[1] < errors[0]  # a finer chord comes closer


def test_a_ring_of_blend_matches_the_exact_torus_it_is():
    """A blend round a whole circular spine is the torus of radii R - r and r: the same
    body with that face on the TORUS tessellates to the same volume and area, and both
    come close to the exact ones."""
    blend = tessellate_transmit(X.rounded_cylinder(), chord_m=1e-5)
    torus = tessellate_transmit(X.rounded_cylinder(torus=True), chord_m=1e-5)
    assert blend.closed is True and blend.skipped == () and torus.closed is True
    mb, mt = blend.measures(), torus.measures()
    assert mb["volume"] == pytest.approx(mt["volume"], rel=2e-4)
    assert mb["area"] == pytest.approx(mt["area"], rel=2e-4)
    volume, area = _rounded_exact()
    assert mb["volume"] == pytest.approx(volume, rel=2e-3) and mb["area"] == pytest.approx(area, rel=1e-3)
    finer = tessellate_transmit(X.rounded_cylinder(), chord_m=2e-6).measures()
    assert abs(finer["volume"] / volume - 1.0) < abs(mb["volume"] / volume - 1.0)


def _ellipse_distance(p, C, A, B, a, b) -> float:
    """The distance from ``p`` to the ellipse ``C + a cos t A + b sin t B``: a scan of 720
    points, then a golden-section search about the nearest."""

    def at(t):
        return tuple(C[i] + a * math.cos(t) * A[i] + b * math.sin(t) * B[i] for i in range(3))

    def d(t):
        return math.dist(at(t), p)

    k = min(range(720), key=lambda j: d(2.0 * math.pi * j / 720))
    lo, hi = 2.0 * math.pi * (k - 1) / 720, 2.0 * math.pi * (k + 1) / 720
    g = (math.sqrt(5.0) - 1.0) / 2.0
    for _ in range(60):
        c1, c2 = hi - g * (hi - lo), lo + g * (hi - lo)
        if d(c1) < d(c2):
            hi = c2
        else:
            lo = c1
    return d(0.5 * (lo + hi))


@pytest.mark.parametrize("degrees", [30, 50])
def test_a_blend_round_an_ellipse_lies_on_the_surface_its_sphere_sweeps(degrees):
    """The cut cylinder's round has no closed form: every vertex of its triangles lies on
    the canal surface (at the radius from the elliptical spine) within the chord tolerance,
    every triangle faces away from the spine, out of the material, and the solid closes."""
    xt, (C, A, B, a, b) = X.tilted_cylinder(degrees=degrees)
    xt = _numbered(xt)
    chord = 1e-5
    t = tessellate_transmit(xt, chord_m=chord)
    assert t.closed is True and t.skipped == ()
    blend_ids = _blend_faces(xt)
    mesh = t.mesh
    pos = mesh.positions
    faces = [f for f, (_k, fid) in zip(mesh.faces, t.face_ids, strict=True) if fid in blend_ids]
    assert len(faces) == 1
    (f,) = faces
    worst = 0.0
    for v in range(f.first_vertex, f.first_vertex + f.n_vertices, 7):
        p = (pos[3 * v], pos[3 * v + 1], pos[3 * v + 2])
        worst = max(worst, abs(_ellipse_distance(p, C, A, B, a, b) - R_BLEND))
    assert worst <= chord
    tri = mesh.triangles
    against = 0
    spine = [
        tuple(C[i] + a * math.cos(s) * A[i] + b * math.sin(s) * B[i] for i in range(3))
        for s in (2.0 * math.pi * j / 720 for j in range(720))
    ]
    for k in range(f.first_triangle, f.first_triangle + f.n_triangles, 5):
        corners = [tri[3 * k + j] for j in range(3)]
        q = [(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]) for i in corners]
        u = [q[1][i] - q[0][i] for i in range(3)]
        w = [q[2][i] - q[0][i] for i in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        c = [sum(p[i] for p in q) / 3.0 for i in range(3)]
        # the normal points away from the spine point nearest the centroid
        near = min(spine, key=lambda s, c=c: math.dist(s, c))
        if sum(n[i] * (c[i] - near[i]) for i in range(3)) <= 0.0:
            against += 1
    assert against == 0


# --------------------------------------------------------------------------- the defects
def test_a_tolerant_edge_beside_a_blend_is_sampled_along_its_other_fin():
    """A tolerant edge has no curve: each fin carries an SP-curve in its own face's (u, v).
    The blend's fin came first, and its (u, v), Parasolid's own parameters of the blend,
    cannot be evaluated (the blend is drawn from an approximation with parameters of its
    own): the edge failed, and with it the plane beside the blend too. It is sampled
    along the plane's fin instead, and the box closes with its volume."""
    xt = X.filleted_box(tolerant=True)
    assert ps.validate(xt)["ok"]
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert t.skipped == () and t.closed is True
    volume, _area = _box_exact()
    assert t.measures()["volume"] == pytest.approx(volume, rel=2e-4)


def test_a_curve_given_only_in_a_blends_own_parameters_is_refused_not_guessed():
    """With the plane's fin curve gone, only the blend's SP-curve is left: its (u, v) are
    not the approximation's, so the edge is refused (``unsupported_curve``) and its two
    faces with it, rather than sampled somewhere else on the blend."""
    xt = X.filleted_box(tolerant=True)
    edge = next(e for e in xt.nodes if e.type == 16 and X.field(xt, e, "tolerance") == 1e-8)
    fins = [f for f in xt.nodes if f.type == 17 and X.field(xt, f, "edge") == edge.index]
    plane_fin = next(f for f in fins if f.index != X.field(xt, edge, "halfedge"))
    X.set_field(xt, plane_fin, "curve", 0)
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert sorted((s.surface, s.reason) for s in t.skipped) == [
        ("BLENDED_EDGE", "unsupported_curve"),
        ("PLANE", "unsupported_curve"),
    ]


def _blend_node(xt):
    return next(n for n in xt.nodes if n.type == 56)


def test_an_offset_of_a_blend_is_refused_not_drawn_the_wrong_way():
    """An offset goes along its base's natural normal, and a blend's is not known: such a
    face is skipped with that reason, never drawn on a guess, while the same face on the
    blend itself is drawn. (Before, every face on a blend or an offset of one was refused
    alike, its detail only ``BLENDED_EDGE``.)"""
    xt = X.filleted_box()
    whole = tessellate_transmit(xt, chord_m=1e-5)
    assert whole.skipped == () and whole.counts["faces_done"] == 7 and whole.closed is True
    blend = _blend_node(xt)
    offset = X.add_node(xt, 60, surface=blend.index, offset=0.0, sense="+", check="U", scale=1.0)
    face = next(f for f in xt.nodes if f.type == 14 and X.field(xt, f, "surface") == blend.index)
    X.set_field(xt, face, "surface", offset.index)
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert [(s.surface, s.reason, s.detail) for s in t.skipped] == [
        ("OFFSET_SURF", "unsupported_surface", "an offset of a rolling blend")
    ]
    assert t.counts["faces_done"] == 6 and t.closed is False


def blend_sheet():
    """The filleted box's round alone, a sheet: its supports are planes no face lies on,
    so it meets no face to take its side from."""
    r = R_BLEND
    b = X.XtBuilder()
    P = {"G": (W - r, 0, H), "Hh": (W - r, D, H), "I": (W, 0, H - r), "J": (W, D, H - r)}
    V = {k: b.vertex(p) for k, p in P.items()}
    front, back = (W - r, 0, H - r), (W - r, D, H - r)
    b.plane((0, 0, H), (0, 0, 1), (1, 0, 0))  # the top
    b.plane((W, 0, 0), (1, 0, 0), (0, 1, 0))  # the side
    e1 = b.edge(b.line(P["Hh"], (0, -D, 0)), V["Hh"], V["G"])
    e2 = b.edge(b.circle(front, (0, -1, 0), (1, 0, 0), r), V["I"], V["G"])
    e3 = b.edge(b.line(P["I"], (0, D, 0)), V["I"], V["J"])
    e4 = b.edge(b.circle(back, (0, -1, 0), (1, 0, 0), r), V["J"], V["Hh"])
    spine = b.line(front, (0, 1, 0))
    blend = b.node(56, blend_type="R", spine=spine, range=[-r, -r], sense="+")
    b.face(blend, "+", [[(e1, "+"), (e2, "-"), (e3, "+"), (e4, "+")]])
    xt = b.body([e1, e2, e3, e4], body_type=3)
    planes = sorted((n for n in xt.nodes if n.type == 50), key=lambda n: X.field(xt, n, "normal")[0])
    X.set_field(xt, _blend_node(xt), "surface", [planes[0].index, planes[1].index])  # top, then side
    return xt


def test_a_blend_face_that_meets_no_face_tangentially_takes_its_side_from_its_loop():
    """No face to take its side from: its loop runs counter-clockwise about its outward
    normal, as every outer loop does, so the sign of the loop's area in the
    approximation's (u, v) gives it. The round faces away from its spine, as it does in
    the box."""
    t = tessellate_transmit(blend_sheet(), chord_m=1e-5)
    assert t.skipped == () and t.closed is None
    mesh = t.mesh
    pos, nrm = mesh.positions, mesh.normals
    spine_x, spine_z = W - R_BLEND, H - R_BLEND
    for v in range(mesh.n_vertices):
        out = (pos[3 * v] - spine_x, pos[3 * v + 2] - spine_z)
        assert nrm[3 * v] * out[0] + nrm[3 * v + 2] * out[1] > 0.0


def ring_sheet():
    """The rounded cylinder's ring of blend alone, a sheet: closed round its spine, its
    loops two rings, and no face to take its side from."""
    r, R, Hc = R_BLEND, RC, HC
    b = X.XtBuilder()
    side_top = b.edge(b.circle((0, 0, Hc - r), X.Z, X.X, R))
    top = b.edge(b.circle((0, 0, Hc), X.Z, X.X, R - r))
    b.cylinder((0, 0, 0), X.Z, R, X.X)
    b.plane((0, 0, Hc), X.Z, X.X)
    spine = b.circle((0, 0, Hc - r), X.Z, X.X, R - r)
    blend = b.node(56, blend_type="R", spine=spine, range=[-r, -r], sense="+")
    b.face(blend, "+", [[(side_top, "+")], [(top, "-")]])
    xt = b.body([side_top, top], body_type=3)
    return X.blend_on(xt, spine, r, ("top", "side"))


def test_a_ring_of_blend_that_meets_no_face_tangentially_is_skipped_with_the_reason():
    """Its loops wrap round the blend: they cannot say which way it faces."""
    t = tessellate_transmit(ring_sheet(), chord_m=1e-5)
    assert [(s.surface, s.reason) for s in t.skipped] == [("BLENDED_EDGE", "orientation_conflict")]
    assert "orientation_conflict" in REASONS and t.closed is None


def test_a_blend_that_cannot_be_fitted_within_the_chord_is_refused(monkeypatch):
    """Two sections round the whole ellipse and no refinement: the loft strays far beyond
    the chord tolerance, so the face is skipped (``fit_failed``) and the solid is not
    closed, rather than drawn off its surface."""
    from solidseas.tessellate import blend

    monkeypatch.setattr(blend, "FIRST_SECTIONS", 3)
    monkeypatch.setattr(blend, "ROUNDS", 0)
    t = tessellate_transmit(X.tilted_cylinder()[0], chord_m=1e-5)
    (s,) = t.skipped
    assert (s.surface, s.reason) == ("BLENDED_EDGE", "fit_failed")
    assert t.closed is False and "fit_failed" in REASONS


@pytest.mark.parametrize(
    "change, reason, why",
    [
        ({"blend_type": "X"}, "unsupported_surface", "a blend of type 'X'"),
        ({"range": [-R_BLEND, -2.0 * R_BLEND]}, "unsupported_surface", "two ranges differ"),
        ({"range": [-R_BLEND]}, "bad_reference", "without its two supports and ranges"),
        ({"surface": [999_999, 999_998]}, "bad_reference", "support is missing"),
        ({"spine": "trimmed"}, "unsupported_curve", "spine is a trimmed curve"),
        # as the export says it: its geometry cannot be evaluated
        ({"spine": 0}, "unsupported_surface", "supports cannot be evaluated"),
    ],
)
def test_a_damaged_blend_is_skipped_with_a_reason_and_the_rest_is_drawn(change, reason, why):
    """Each damage is refused for its own cause, which the detail names. (Before, every
    face on a blend was refused alike, ``unsupported_surface`` with the detail
    ``BLENDED_EDGE``, damaged or not.)"""
    xt = X.filleted_box()
    blend = _blend_node(xt)
    for name, value in change.items():
        if value == "trimmed":
            line = xt.by_index()[X.field(xt, blend, "spine")]
            value = X.add_node(
                xt,
                133,
                basis_curve=line.index,
                sense="+",
                parm_1=0.0,
                parm_2=0.02,
                point_1=(0.028, 0.0, 0.008),
                point_2=(0.028, 0.02, 0.008),
            ).index
        X.set_field(xt, blend, name, value)
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert [(s.surface, s.reason) for s in t.skipped] == [("BLENDED_EDGE", reason)]
    assert why in t.skipped[0].detail
    assert t.counts["faces_done"] == 6 and t.closed is False


def test_blends_come_last_so_the_time_limit_leaves_out_only_blends(monkeypatch):
    """A blend costs far more than any other face: the body's other faces are done first.
    The time running out while a blend is fitted leaves out the blend alone, with the
    reason, and the rest is whole, so the result is not cut short (a 3D print of it is
    made, with a hole there, rather than refused)."""
    from solidseas.tessellate import blend
    from solidseas.tessellate.topology import TimeUp

    xt = _numbered(X.filleted_box())
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert t.face_ids[-1][1] in _blend_faces(xt) and len(t.face_ids) == 7

    def out_of_time(self, s, hint=None):
        self.sampler.clock.deadline = 0.0  # the whole tessellation's time, not just this blend's
        raise TimeUp

    monkeypatch.setattr(blend.Blends, "_fit", out_of_time)
    t = tessellate_transmit(xt, chord_m=1e-5)
    assert t.truncated == () and t.reasons == {"max_seconds": 1} and t.closed is False
    assert t.counts["faces"] == 7 and t.counts["faces_done"] == 6 and t.counts["faces_skipped"] == 1
    assert [(s.surface, s.reason) for s in t.skipped] == [("BLENDED_EDGE", "max_seconds")]
    assert not {fid for _k, fid in t.face_ids} & _blend_faces(xt) and "max_seconds" in REASONS


def _slow_blends(monkeypatch):
    """Blends whose fits go on until the tessellation's own time is up (as many blends that
    each take their share do), on a clock that moves only while they are fitted: every
    clock of the library reads time.perf_counter, so the test takes no real time and does
    not depend on the machine's load. Returns the clock's [now]."""
    import time

    from solidseas.tessellate import blend

    now = [time.perf_counter()]
    monkeypatch.setattr(time, "perf_counter", lambda: now[0])

    def slow(self, s, hint=None):
        while True:
            now[0] += 0.01
            self.sampler.clock.check()

    monkeypatch.setattr(blend.Blends, "_fit", slow)
    return now


def test_the_blends_pass_ends_its_reserve_before_the_deadline(monkeypatch):
    """Blends the time runs out on are left out, not the result cut short. A caller that
    gave the tessellation all of its own time and must still use the result (a Parasolid
    file's export scene) asks their pass to end ``blend_reserve_s`` before the deadline;
    without one it runs to the deadline, as a part's tessellation does."""
    now = _slow_blends(monkeypatch)
    for max_seconds, reserve in ((2.0, 0.0), (2.0, 0.2), (30.0, 2.0)):
        start = now[0]
        t = tessellate_transmit(
            _numbered(X.filleted_box()), chord_m=1e-5, max_seconds=max_seconds, blend_reserve_s=reserve
        )
        assert t.truncated == () and t.reasons == {"max_seconds": 1}
        assert max_seconds - reserve <= now[0] - start <= max_seconds - reserve + 0.02


def test_a_parasolid_file_whose_blends_run_out_of_time_still_gives_a_scene_and_a_print(monkeypatch):
    """A Parasolid file's export scene gives the tessellator all of its own time. Its blends
    used to run to that deadline, so the scene's own clock had run out as the tessellation
    returned: an export's scene and the 3D print raised limit_exceeded where the blends
    should have been left out with a hole, as for a SOLIDWORKS part. Now their pass ends a
    tenth of the time before the deadline and both are made, the blends skipped
    (``max_seconds``) and the print saying the part is not closed, and a display scene
    names max_seconds in ``truncated`` so a thumbnail is marked partial."""
    from solidseas.render import render_preview

    _slow_blends(monkeypatch)
    data = _x_b(_numbered(X.filleted_box()))
    with open_model(data, name="part.x_b") as doc:
        scene = doc.scene(max_seconds=2.0)
    assert [(s.surface, s.reason) for s in scene.skipped] == [("BLENDED_EDGE", "max_seconds")]
    assert scene.truncated == () and scene.counts["faces_done"] == 6 and scene.objects[0].n_triangles > 0
    with open_model(data, name="part.x_b") as doc:
        view = doc.scene(prefer="display", max_seconds=2.0)
    assert view.truncated == ("max_seconds",) and view.counts["faces_done"] == 6
    with open_model(data, name="part.x_b") as doc:
        pm = export.print_model(doc, max_seconds=2.0)
    assert not pm.closed and pm.objects[0].n_triangles > 0
    (left_out,) = [w for w in pm.warnings if w.code == "faces_left_out"]
    assert "(max_seconds 1)" in left_out.message  # the print says why, as a SOLIDWORKS part's does
    assert "not_closed" in {w.code for w in pm.objects[0].warnings}
    with open_model(data, name="part.x_b") as doc:
        assert render_preview(doc).partial


def test_a_fit_whose_share_runs_out_keeps_its_best_round_when_it_is_close_enough(monkeypatch):
    """The ellipse's round is measured at 38, 2.7, 1.9, 1.4 and 1 times the target in its
    rounds. Its time share running out in the third round, the second round's surface,
    within the deviation allowed (10 times the target), is drawn rather than the blend
    refused, and the solid closes."""
    import time

    from solidseas.tessellate import blend

    now = [time.perf_counter()]
    monkeypatch.setattr(time, "perf_counter", lambda: now[0])
    real_loft, lofts = blend.loft, []

    def late(*args, **kw):
        lofts.append(len(args[0]))
        if len(lofts) == 3:
            now[0] += 5.0  # past this blend's 3 s share, well within the tessellation's 30 s
        return real_loft(*args, **kw)

    monkeypatch.setattr(blend, "loft", late)
    t = tessellate_transmit(X.tilted_cylinder()[0], chord_m=1e-5, max_seconds=30.0)
    assert t.skipped == () and t.closed is True and len(lofts) == 3
    volume = tessellate_transmit(X.tilted_cylinder()[0], chord_m=1e-5).measures()["volume"]
    assert t.measures()["volume"] == pytest.approx(volume, rel=1e-4)


@pytest.mark.parametrize("max_seconds, share", [(30.0, 3.0), (300.0, 15.0), (10.0, 1.0)])
def test_a_blend_whose_fit_outruns_its_share_of_the_time_is_refused(monkeypatch, max_seconds, share):
    """One blend may take a tenth of the time allowed, and at most 15 s: at a 3D print's
    300 s a tenth was 30 s a blend, mostly spent on blends refused anyway. A fit that takes
    longer, with no round within the deviation allowed, is refused (``fit_failed``) and the
    others go on."""
    from solidseas.tessellate import blend
    from solidseas.tessellate.topology import TimeUp

    def too_slow(self, s, hint=None):
        assert self.clock is not self.sampler.clock and share - 1.0 < self.clock.left() <= share
        raise TimeUp  # its own share ran out, the tessellation's has not

    monkeypatch.setattr(blend.Blends, "_fit", too_slow)
    t = tessellate_transmit(_numbered(X.filleted_box()), chord_m=1e-5, max_seconds=max_seconds)
    (s,) = t.skipped
    assert (s.reason, t.truncated) == ("fit_failed", ()) and f"{share:g} s a blend may take" in s.detail


# --------------------------------------------------------------------------- what people get
def _x_b(xt) -> bytes:
    xt.max_types = 231
    return ps.text_header(xt, fmt="binary", key="k", file="k.x_b").encode("ascii") + ps.write_binary(xt)


def _stl_closed(data: bytes):
    """A binary STL's triangles welded by their exact coordinates: closed (each edge used
    once each way) and its volume in m^3 (the file is in millimetres)."""
    n = struct.unpack_from("<I", data, 80)[0]
    ids: dict = {}
    pos, tris = [], []
    for k in range(n):
        vals = struct.unpack_from("<12f", data, 84 + 50 * k)
        for j in range(3):
            p = vals[3 + 3 * j : 6 + 3 * j]
            tris.append(ids.setdefault(p, len(ids)))
            if len(pos) < len(ids):
                pos.append(p)
    return _closed(tris), _signed_volume(pos, tris) * 1e-9


def _3mf_closed(data: bytes):
    z = zipfile.ZipFile(io.BytesIO(data))
    root = ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".model"))))
    ns = root.tag[: root.tag.index("}") + 1]
    (mesh,) = list(root.iter(ns + "mesh"))
    pos = [(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in mesh.iter(ns + "vertex")]
    tris = [int(t.get(k)) for t in mesh.iter(ns + "triangle") for k in ("v1", "v2", "v3")]
    assert root.get("unit") == "millimeter"
    return _closed(tris), _signed_volume(pos, tris) * 1e-9


def _signed_volume(pos, tris) -> float:
    v = 0.0
    for k in range(0, len(tris), 3):
        a, b, c = pos[tris[k]], pos[tris[k + 1]], pos[tris[k + 2]]
        v += a[0] * (b[1] * c[2] - b[2] * c[1])
        v -= a[1] * (b[0] * c[2] - b[2] * c[0])
        v += a[2] * (b[0] * c[1] - b[1] * c[0])
    return v / 6.0


@pytest.mark.parametrize("shape", ["filleted_box", "rounded_cylinder"])
def test_the_viewer_and_the_3d_print_files_of_a_rounded_part_have_no_holes(shape):
    """A Parasolid file of the part, as the viewer opens it: its scene is drawn whole, and
    the 3D print model and the STL and 3MF written from it are closed solids of the part's
    volume. Before, the round was left out of all of them."""
    xt = getattr(X, shape)()
    volume = (_box_exact if shape == "filleted_box" else _rounded_exact)()[0]
    with open_model(_x_b(xt), name="part.x_b") as doc:
        scene = doc.scene()
        assert scene.warnings == () and scene.objects[0].n_triangles > 0
        assert scene.objects[0].measures()["volume_m3"] == pytest.approx(volume, rel=5e-3)
        pm = export.print_model(doc)
    assert pm.closed and pm.objects[0].warnings == ()
    printed = pm.measures()["volume_m3"]
    assert printed == pytest.approx(volume, rel=2e-3)  # the print's chord, on the cylinder too
    stl_closed, stl_volume = _stl_closed(export.export_bytes(pm, "stl"))
    tmf_closed, tmf_volume = _3mf_closed(export.export_bytes(pm, "3mf"))
    assert stl_closed and tmf_closed
    assert stl_volume == pytest.approx(printed, rel=1e-5) and tmf_volume == pytest.approx(printed, rel=1e-5)
