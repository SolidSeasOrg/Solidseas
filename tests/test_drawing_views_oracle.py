"""Analytic hidden-line oracles (docs/DRAWINGS.md 8.4): synthetic parts whose views are
known exactly, compared run by run."""

import math

import pytest

import drawing_parts as P
import xt_bodies
from drawing_support import fixture, model
from solidseas import open_document
from solidseas.drawing import facegraph
from solidseas.drawing import types as T
from solidseas.drawing import views as V
from solidseas.drawing.display import Arc, Polyline, Segment

MM = 1e-3


def view(m, name, hidden=False):
    d, up = V.view_frames()[name]
    return V.project(m, T.ViewSpec("v-1", "base", d, up, name, hidden=hidden))


def lines(g, style="visible"):
    out = set()
    for r in g.runs:
        if r.style == style and isinstance(r.primitive, Segment):
            a, b = sorted(
                (
                    tuple(round(c / MM, 3) for c in r.primitive.p0),
                    tuple(round(c / MM, 3) for c in r.primitive.p1),
                )
            )
            out.add(a + b)
    return out


def edges_of(points):
    out = set()
    for k in range(len(points)):
        a, b = points[k], points[(k + 1) % len(points)]
        a, b = sorted((tuple(round(c, 3) for c in a), tuple(round(c, 3) for c in b)))
        out.add(a + b)
    return out


def test_a_stepped_block_shows_its_profile_from_the_front():
    xt, _truth = P.pocket_tab_block()
    m = facegraph.from_transmit(xt)
    g = view(m, "front")
    profile = [(0, 0), (80, 0), (80, 20), (72, 20), (72, 35), (66, 35), (66, 20), (0, 20)]
    pocket = [(15, 4), (55, 4), (55, 16), (15, 16)]
    assert lines(g) == edges_of(profile) | edges_of(pocket)


def test_a_stepped_block_from_the_top_hides_the_pocket_floor_unless_asked():
    xt, _truth = P.pocket_tab_block()
    m = facegraph.from_transmit(xt)
    top = view(m, "top")
    # seen from above: the block's top at y = 20 beside the tab, the tab's top at 35;
    # the extrusion runs 50 along z, which the top view shows going down the sheet
    assert (0.0, -50.0, 0.0, 0.0) in lines(top)  # the left end
    assert (66.0, -50.0, 66.0, 0.0) in lines(top) and (72.0, -50.0, 72.0, 0.0) in lines(top)
    hidden = lines(view(m, "top", hidden=True), "hidden")
    # the pocket's floor, 8 deep from the face at z = 50, lies inside the block
    assert (15.0, -42.0, 55.0, -42.0) in hidden


def test_a_cylinder_on_a_plate():
    m = model("boss")
    front = view(m, "front")
    arcs = sorted(round(r.primitive.radius / MM, 6) for r in front.runs if isinstance(r.primitive, Arc))
    assert arcs == [5.0, 15.0]
    assert edges_of([(0, 0), (60, 0), (60, 60), (0, 60)]) <= lines(front)
    right = view(m, "right")
    # the block 60 x 20 and the boss standing 15 on it, seen from the side (z across)
    assert (-35.0, 15.0, -35.0, 45.0) in lines(right)  # the boss's top, edge-on
    assert {(-35.0, 15.0, -20.0, 15.0), (-35.0, 45.0, -20.0, 45.0)} <= lines(right)  # its silhouettes


def test_a_hemisphere_on_a_disc():
    r = 0.01
    m = facegraph.from_transmit(xt_bodies.hemisphere(r))
    side = view(m, "front")  # seen from +z: the full circle of its rim
    arcs = [p.primitive for p in side.runs if isinstance(p.primitive, Arc)]
    assert len(arcs) == 1 and arcs[0].radius == pytest.approx(r)
    top = view(m, "top")  # seen from +y: the rim edge-on and the dome's silhouette
    sil = [p.primitive for p in top.runs if p.source.kind == "silhouette"]
    assert sil and all(isinstance(s, Polyline) for s in sil)
    pts = [q for s in sil for q in s.points]
    assert all(abs(math.hypot(*q) - r) <= 2 * m.chord for q in pts)
    span = max(q[0] for q in pts) - min(q[0] for q in pts)
    assert span == pytest.approx(2 * r, rel=0.02)


@pytest.mark.parametrize(
    "name, size",
    [("o02_boxA.SLDPRT", None), ("o07_boxB_h31.SLDPRT", None)],
)
def test_fixture_boxes_draw_their_faces(name, size):
    with open_document(fixture(name)) as doc:
        m = facegraph.from_document(doc)
    (lo, hi) = m.box
    w, h = (hi[0] - lo[0]) / MM, (hi[1] - lo[1]) / MM
    x0, y0 = lo[0] / MM, lo[1] / MM
    rect = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    assert lines(view(m, "front")) == edges_of(rect)
