"""Damaged and crafted bodies never hang the tessellator, exhaust memory or raise.

Each test damages a body (fixture o11's, which has planes, cylinders, a torus,
lines and circles, or a synthetic one) and tessellates it under a short time
limit: the face or body concerned is skipped with the reason expected, the rest
is done, and the call returns well within a few seconds.
"""

import copy
import math
import time

import pytest

import xt_bodies
from solidseas import open_document
from solidseas.formats.solidworks import xt_schema as S
from solidseas.formats.solidworks.parasolid import (
    FieldDef,
    Node,
    SchemaInfo,
    read_file,
    split_header,
    write_text,
)
from solidseas.tessellate import curves, tessellate_document, tessellate_transmit
from support import fixture_path

with open_document(fixture_path("o11_curved.SLDPRT")) as _doc:
    O11 = _doc.parasolid().bodies[0].transmit


def _o11():
    return copy.deepcopy(O11)


def _set(xt, node, name, value) -> None:
    node.vals[xt.field_names(node.type).index(name)] = value


def _get(xt, node, name):
    return node.vals[xt.field_names(node.type).index(name)]


def _of(xt, tname: str):
    return [n for n in xt.nodes if n.tname == tname]


def _add(xt, ntype: int, **fields) -> Node:
    lay = [tuple(f[:3]) for f in S.BASE[ntype]]
    xt.layouts.setdefault(ntype, lay)
    xt.schema_info.setdefault(ntype, SchemaInfo("base"))
    idx = max(n.index for n in xt.nodes) + 1
    vals = [fields.get(name, xt_bodies._default(kind, n)) for name, kind, n in lay]
    node = Node(ntype, idx, vals, None)
    xt.nodes.append(node)
    xt._by_index = None
    return node


def _run(xt, **kw):
    t0 = time.perf_counter()
    t = tessellate_transmit(xt, max_seconds=5, **kw)
    assert time.perf_counter() - t0 < 6
    return t


def test_the_undamaged_body_is_whole():
    t = _run(_o11())
    assert t.closed is True and t.counts["faces_done"] == 12 and t.reasons == {}


def test_a_fin_ring_that_never_comes_back_fails_its_face():
    xt = _o11()
    by = xt.by_index()
    loop = next(
        lp for lp in _of(xt, "LOOP") if by[_get(xt, by[_get(xt, lp, "halfedge")], "forward")] is not None
    )
    f0 = by[_get(xt, loop, "halfedge")]
    f1 = by[_get(xt, f0, "forward")]
    f2 = by[_get(xt, f1, "forward")]
    _set(xt, f2, "forward", f1.index)  # f1 -> f2 -> f1 -> ...: never back to f0
    t = _run(xt)
    assert t.reasons.get("bad_reference", 0) >= 1 and t.counts["faces_done"] >= 1
    assert any("ring" in s.detail for s in t.skipped)


@pytest.mark.parametrize("tname", ["REGION", "SHELL"])
def test_a_chain_that_loops_fails_the_body(tname):
    xt = _o11()
    node = _of(xt, tname)[0]
    _set(xt, node, "next", node.index)
    t = _run(xt)
    assert t.counts["bodies_skipped"] == 1 and t.reasons == {"bad_reference": 1} and t.mesh.n_triangles == 0
    assert t.skipped[0].face == -1
    assert t.closed is False  # a solid with no triangles is not whole (None is for no solid)


def test_a_solid_whose_walk_fails_beside_a_whole_one_is_not_closed():
    xt = read_file(fixture_path("o12_multibody.x_b").read_bytes())
    assert _run(xt).closed is True
    by = xt.by_index()
    region = by[_get(xt, _of(xt, "BODY")[1], "region")]
    _set(xt, region, "next", region.index)
    t = _run(xt)
    assert t.counts["bodies_skipped"] == 1 and t.counts["faces_done"] == 6 and t.closed is False


def test_pointers_to_the_wrong_node_or_to_no_node_fail_their_face():
    xt = _o11()
    faces = _of(xt, "FACE")
    _set(xt, faces[0], "surface", _of(xt, "LOOP")[0].index)
    _set(xt, faces[1], "surface", 10**6)  # no such node
    t = _run(xt)
    assert t.reasons == {"bad_reference": 2} and t.counts["faces_done"] == 10 and t.closed is False


@pytest.mark.parametrize(
    ("tname", "field", "value", "reason"),
    [
        ("POINT", "pvec", (float("nan"), 0.0, 0.0), "non_finite"),
        ("POINT", "pvec", (float("inf"), 0.0, 0.0), "non_finite"),
        ("CYLINDER", "axis", (0.0, 0.0, 0.0), "bad_geometry"),
        ("CYLINDER", "radius", 0.0, "bad_geometry"),
        ("CYLINDER", "radius", -0.004, "bad_geometry"),
        ("CYLINDER", "radius", float("inf"), "non_finite"),
        ("TORUS", "minor_radius", -1.0, "bad_geometry"),
        ("CIRCLE", "radius", float("nan"), "non_finite"),
        ("PLANE", "normal", (0.0, 0.0, 0.0), "bad_geometry"),
        ("LINE", "direction", (0.0, 0.0, 0.0), "bad_geometry"),
    ],
)
def test_bad_numbers_fail_the_faces_that_use_them(tname, field, value, reason):
    xt = _o11()
    _set(xt, _of(xt, tname)[0], field, value)
    t = _run(xt)
    assert set(t.reasons) == {reason} and 0 < t.counts["faces_skipped"] < 12, t.reasons
    p = t.mesh.positions
    assert all(math.isfinite(x) for x in p)


def test_huge_tolerances_and_tiny_limits_end_cleanly():
    xt = _o11()
    for e in _of(xt, "EDGE"):
        _set(xt, e, "tolerance", 1e300)
    for v in _of(xt, "VERTEX"):
        _set(xt, v, "tolerance", 1e300)
    t = _run(xt)
    assert t.counts["faces"] == 12
    t = _run(_o11(), max_edge_points=3)
    assert set(t.reasons) == {"edge_too_long"}
    t = _run(_o11(), max_face_points=16)
    assert "max_face_points" in t.reasons


def test_geometry_that_refers_to_itself_fails_its_face():
    xt = _o11()
    off = _add(xt, 60, surface=0, offset=0.001, sense="+")
    _set(xt, off, "surface", off.index)
    _set(xt, _of(xt, "FACE")[0], "surface", off.index)
    trimmed = _add(xt, 133, basis_curve=0, parm_1=0.0, parm_2=1.0)
    _set(xt, trimmed, "basis_curve", trimmed.index)
    _set(xt, _of(xt, "EDGE")[0], "curve", trimmed.index)
    t = _run(xt)
    assert set(t.reasons) == {"bad_reference"} and t.counts["faces_skipped"] >= 2


def test_a_face_whose_work_outlasts_the_limit_stops_within_it():
    t0 = time.perf_counter()
    t = tessellate_transmit(xt_bodies.sphere(0.01), chord_m=1e-9, angle_deg=0.5, max_seconds=0.5)
    assert time.perf_counter() - t0 < 2.0
    assert t.truncated in (("max_seconds",), ())  # stopped, or done first on a very fast machine


# --------------------------------------------------------------------------- B-splines and charts
def _nurbs():
    xt = xt_bodies.nurbs_cylinder()
    return xt, next(n for n in xt.nodes if n.type == xt_bodies.NURBS_SURF)


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (
            lambda xt, ns, by: _set(xt, by[_get(xt, ns, "u_knots")], "knots", [0.0, 2.0, 1.0, 3.0, 4.0]),
            "bad_geometry",
        ),
        (lambda xt, ns, by: _set(xt, by[_get(xt, ns, "u_knot_mult")], "mult", [3, 2, 2, 2]), "bad_geometry"),
        (lambda xt, ns, by: _set(xt, ns, "n_u_vertices", 10**7), "bad_geometry"),
        (lambda xt, ns, by: _set(xt, ns, "u_degree", 100), "bad_geometry"),
        (lambda xt, ns, by: _set(xt, ns, "vertex_dim", 7), "bad_geometry"),
        (
            lambda xt, ns, by: _get(xt, by[_get(xt, ns, "bspline_vertices")], "vertices").__setitem__(
                3, -1.0
            ),
            "bad_geometry",
        ),
        (
            lambda xt, ns, by: _get(xt, by[_get(xt, ns, "bspline_vertices")], "vertices").__setitem__(
                0, float("nan")
            ),
            "non_finite",
        ),
    ],
    ids=["knots_decrease", "knots_short", "ten_million_points", "degree_100", "dimension", "weight", "nan"],
)
def test_damaged_b_splines_fail_their_face(damage, reason):
    xt, ns = _nurbs()
    damage(xt, ns, xt.by_index())
    t = _run(xt)
    assert t.reasons == {reason: 1} and t.counts["faces_done"] == 2


def _chart_cylinder(points: int):
    """The synthetic cylinder with its bottom edge on an intersection curve: a closed chart
    of ``points`` points round the circle."""
    xt = xt_bodies.cylinder()
    circle = next(n for n in xt.nodes if n.tname == "CIRCLE")
    r = _get(xt, circle, "radius")
    pts = [
        (r * math.cos(2 * math.pi * k / points), r * math.sin(2 * math.pi * k / points), 0.0)
        for k in range(points)
    ]
    pts.append(pts[0])
    chart = _add(xt, 40, chordal_error=1e-6, hvec=pts)
    chart.count = len(pts)
    planes = [n.index for n in xt.nodes if n.tname in ("PLANE", "CYLINDER")]
    inter = _add(xt, 38, chart=chart.index, surface=planes[:2], sense="+")
    edge = next(e for e in xt.nodes if e.tname == "EDGE" and _get(xt, e, "curve") == circle.index)
    _set(xt, edge, "curve", inter.index)
    return xt


def test_an_intersection_ring_edge_is_sampled_from_its_chart_and_a_huge_chart_is_refused(monkeypatch):
    t = _run(_chart_cylinder(64))
    assert t.closed is True and t.reasons == {}
    m = t.measures()
    assert m["volume"] == pytest.approx(math.pi * 0.005**2 * 0.02, rel=1e-2)
    monkeypatch.setattr(curves, "MAX_CHART_POINTS", 50)
    t = _run(_chart_cylinder(64))
    assert t.reasons == {"edge_too_long": 2} and t.counts["faces_done"] == 1


def test_a_schema_that_names_a_field_twice_reads_the_first():
    """A transmit's own schema may append a field whose name BODY already has (here
    body_type again, as an array): it is read as XtTransmit.get reads it, the first."""
    data = fixture_path("o02_boxA.x_t").read_bytes()
    header, _body = split_header(data)
    xt = read_file(data)
    info = xt.schema_info[12]
    fd = FieldDef("body_type", 0, 2, "u", None)
    z = [i for i, (op, _f) in enumerate(info.ops) if op == "Z"]
    info.ops.insert(z[0] if z else len(info.ops), ("A", fd))
    info.nfields += 1
    xt.layouts[12] = list(xt.layouts[12]) + [fd.layout()]
    for n in xt.nodes:
        if n.type == 12:
            n.vals.append([1, 1])
    back = read_file(header + write_text(xt).encode("latin-1"))
    assert [f[0] for f in back.layouts[12]].count("body_type") == 2
    t = _run(back)
    assert t.bodies == ("body",) and t.closed is True and t.counts["triangles"] == 12


def test_a_b_spline_cap_with_a_huge_period_lays_a_short_pole_line():
    """A B-spline cone, closed round u with its top row collapsed to the apex, one loop round
    its base, and its u knots a billion units apart: the pole line takes as many points
    as the loop has, not period / angle of them."""
    w = math.sqrt(0.5)
    circle = [(1, 0, 1), (1, 1, w), (0, 1, 1), (-1, 1, w), (-1, 0, 1)]
    circle += [(-1, -1, w), (0, -1, 1), (1, -1, w), (1, 0, 1)]
    r, h = 0.005, 0.01
    rows = [[(x * r * c, y * r * c, 0.0, c), (0.0, 0.0, h * c, c)] for x, y, c in circle]
    b = xt_bodies.XtBuilder()
    knots = [k * 1e9 for k in (0, 1, 2, 3, 4)]
    side = b.nurbs_surface(rows, 2, 1, knots, [3, 2, 2, 2, 3], [0, 1], [2, 2], rational=True, uclosed=True)
    rim = b.edge(b.circle((0, 0, 0), xt_bodies.Z, xt_bodies.X, r))
    b.face(side, "+", [[(rim, "+")]])
    t = _run(b.body([rim], body_type=3))
    assert t.counts["faces_done"] == 1 and 0 < t.counts["triangles"] < 5000


def test_the_time_limit_of_a_document_counts_reading_its_bodies(monkeypatch):
    import solidseas.tessellate as tess

    real = tess.bodies_of

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(tess, "bodies_of", slow)
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        t0 = time.perf_counter()
        t = tessellate_document(doc, max_seconds=0.1)
        assert time.perf_counter() - t0 < 1.0
    assert t.truncated == ("max_seconds",) and t.mesh.n_triangles == 0 and t.closed is False
