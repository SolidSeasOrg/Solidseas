"""What the tessellator keeps for drawings (``detail=True``, docs/DRAWINGS.md 6.1).

The views of a drawing classify every edge in every view by the normals of its two
faces, and refine silhouettes by Newton from each vertex's (u, v). The tessellator
knows both as it works; ``detail=True`` returns them (``TessDetail``), with the
points and normals in float64, and must leave the mesh exactly as it was.

The shapes are the fixtures' parts and the synthetic bodies of ``xt_bodies``, whose
geometry is known exactly.
"""

import math
import tracemalloc
from array import array

import pytest

import xt_bodies as X
from solidseas import open_document
from solidseas.errors import InvalidArgumentError
from solidseas.tessellate import (
    EdgeDetail,
    TessDetail,
    bodies_of,
    tessellate_body,
    tessellate_document,
    tessellate_transmit,
)
from solidseas.tessellate.surfaces import Geometry
from solidseas.tessellate.topology import CURVE_TYPES, EDGE, SURFACE_TYPES, Topology
from support import fixture_path

PARTS = ("o02_boxA.SLDPRT", "o11_curved.SLDPRT", "o12_multibody.SLDPRT", "o13_two_geometry_configs.SLDPRT")
SHAPES = {
    "cylinder": X.cylinder,
    "sphere": X.sphere,
    "torus": X.torus,
    "cone": X.cone,
    "hemisphere": X.hemisphere,
    "nurbs_cylinder": X.nurbs_cylinder,
    "nurbs_sphere": X.nurbs_sphere,
    "void_box": X.void_box,
    "split_box": X.split_box,
}


def _same_mesh(a, b) -> bool:
    return (
        bytes(a.mesh.positions) == bytes(b.mesh.positions)
        and bytes(a.mesh.normals) == bytes(b.mesh.normals)
        and bytes(a.mesh.triangles) == bytes(b.mesh.triangles)
        and [(f.first_vertex, f.n_vertices, f.first_triangle, f.n_triangles) for f in a.mesh.faces]
        == [(f.first_vertex, f.n_vertices, f.first_triangle, f.n_triangles) for f in b.mesh.faces]
        and a.face_ids == b.face_ids
        and a.counts == b.counts
        and a.closed == b.closed
        and a.checks == b.checks
        and a.reasons == b.reasons
        and a.chord_m == b.chord_m
    )


def _part(name: str, **options):
    with open_document(fixture_path(name)) as doc:
        return tessellate_document(doc, **options)


# -- the mesh is the same ------------------------------------------------------------
@pytest.mark.parametrize("name", PARTS)
def test_detail_leaves_a_parts_mesh_as_it_was(name):
    plain, detailed = _part(name), _part(name, detail=True)
    assert plain.detail is None and isinstance(detailed.detail, TessDetail)
    assert _same_mesh(plain, detailed)
    assert _same_mesh(plain, _part(name, detail=False))


BLENDS = {
    "filleted_box": X.filleted_box,
    "tolerant_filleted_box": lambda: X.filleted_box(tolerant=True),
    "rounded_cylinder": X.rounded_cylinder,
    "tilted_cylinder": lambda: X.tilted_cylinder()[0],
}


@pytest.mark.parametrize("shape", sorted(SHAPES) + sorted(BLENDS))
def test_detail_leaves_a_synthetic_bodys_mesh_as_it_was(shape):
    """Rolling blends are done after every other face, and tolerant edges are sampled
    along a fin's curve: the detail follows both and changes neither."""
    xt = {**SHAPES, **BLENDS}[shape]()
    plain, detailed = tessellate_transmit(xt), tessellate_transmit(xt, detail=True)
    assert _same_mesh(plain, detailed) and plain.closed is True
    _aligned(detailed)
    for e in detailed.detail.edges.values():
        assert len(e.faces) == 2 and all(v >= 0 for side in e.vertices for v in side)


def test_every_entry_takes_detail_and_nothing_else_for_it():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        _name, bodies, _w, _n = bodies_of(doc)
        assert tessellate_body(bodies[0], detail=True).detail is not None
        assert tessellate_document(doc, detail=True).detail is not None
        for bad in ("yes", 1, None):
            with pytest.raises(InvalidArgumentError) as info:
                tessellate_document(doc, detail=bad)
            assert info.value.detail["parameter"] == "detail"
    assert tessellate_transmit(X.sphere(), detail=True).detail is not None


# -- the arrays line up with the mesh --------------------------------------------------
def _aligned(t) -> None:
    d = t.detail
    m = t.mesh
    assert len(d.points) == len(m.positions) and len(d.normals) == len(m.normals)
    assert array("f", d.points) == m.positions and array("f", d.normals) == m.normals
    assert len(d.face_uv) == len(m.faces) == len(t.face_ids)
    for f, uv in zip(m.faces, d.face_uv, strict=True):
        assert len(uv) == 2 * f.n_vertices and all(math.isfinite(x) for x in uv)
    for i in range(0, len(d.normals), 3):
        assert abs(math.hypot(*d.normals[i : i + 3]) - 1.0) < 1e-9


@pytest.mark.parametrize("name", PARTS)
def test_the_float64_points_and_normals_are_the_meshes(name):
    _aligned(_part(name, detail=True))


def test_a_face_left_out_leaves_nothing_behind():
    """Faces skipped (too few points allowed) and a stop part way (too few triangles)
    leave the detail aligned with what the mesh kept."""
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        few_points = tessellate_document(doc, detail=True, max_face_points=16)
        few_triangles = tessellate_document(doc, detail=True, max_triangles=900)
    assert few_points.counts["faces_skipped"] > 0 and few_triangles.truncated == ("max_triangles",)
    for t in (few_points, few_triangles):
        _aligned(t)
        done = {fid for _b, fid in t.face_ids}
        for e in t.detail.edges.values():
            assert set(e.faces) <= done


# -- edges -----------------------------------------------------------------------------
def _face_ranges(t) -> dict[tuple[int, int], tuple[int, int]]:
    return {
        key: (f.first_vertex, f.first_vertex + f.n_vertices)
        for key, f in zip(t.face_ids, t.mesh.faces, strict=True)
    }


@pytest.mark.parametrize("name", PARTS)
def test_each_edge_sample_is_a_corner_of_both_faces_triangles(name):
    t = _part(name, detail=True)
    d = t.detail
    ranges = _face_ranges(t)
    assert d.edges and all(isinstance(e, EdgeDetail) for e in d.edges.values())
    for (body, _eid), e in d.edges.items():
        n = len(e.points) // 3
        assert len(e.params) == n >= 2 and len(e.faces) == len(e.normals) == len(e.vertices)
        if t.closed:
            assert len(e.faces) == 2  # a closed solid: a face on each side
        for fid, normals, vertices in zip(e.faces, e.normals, e.vertices, strict=True):
            lo, hi = ranges[(body, fid)]
            assert len(normals) == 3 * n and len(vertices) == n
            for k, v in enumerate(vertices):
                assert lo <= v < hi  # a vertex of that face
                assert d.points[3 * v : 3 * v + 3] == e.points[3 * k : 3 * k + 3]
                assert d.normals[3 * v : 3 * v + 3] == normals[3 * k : 3 * k + 3]


def test_both_faces_share_the_samples_so_their_triangles_meet():
    """The two sides of an edge use the same points: their triangles' edges along it
    coincide, which is what keeps a solid closed and lets a view follow the edge."""
    t = tessellate_transmit(X.void_box(), detail=True)
    for e in t.detail.edges.values():
        a, b = e.vertices
        assert [t.detail.points[3 * v : 3 * v + 3] for v in a] == [
            t.detail.points[3 * v : 3 * v + 3] for v in b
        ]


def _topology(xt, body_index: int = 0):
    topo = Topology(xt)
    body = topo.bodies()[body_index]
    return topo, body


def _edge_by_key(topo, edges, key: int):
    """The EDGE a detail key names: its node_id, or -1 minus its node index (the
    synthetic bodies number no nodes)."""
    for edge in edges:
        if key == topo.get(edge, "node_id", None) or key == -1 - edge.index:
            return edge
    raise AssertionError(f"no edge {key}")


def _edges_of(topo, body):
    seen = {}
    for face in topo.faces(body):
        for lp in topo.loops(face):
            for fin in topo.fins(lp):
                edge = topo.ref(fin, "edge", (EDGE,))
                if edge is not None:
                    seen[edge.index] = edge
    return list(seen.values())


def _edge_curve(topo, geom, edge):
    node = topo.ref(edge, "curve", CURVE_TYPES)
    if node is None:
        node = next(
            topo.ref(f, "curve", CURVE_TYPES)
            for f in topo.edge_fins(edge)
            if topo.ref(f, "curve", CURVE_TYPES)
        )
    return geom.curve(node)


@pytest.mark.parametrize(
    "shape", ["cylinder", "cone", "hemisphere", "nurbs_cylinder", "void_box", "split_box"]
)
def test_each_samples_parameter_puts_it_on_its_curve(shape):
    xt = SHAPES[shape]()
    t = tessellate_transmit(xt, detail=True)
    topo, body = _topology(xt)
    geom = Geometry(topo, t.chord_m)
    edges = _edges_of(topo, body)
    checked = 0
    for (_b, eid), e in t.detail.edges.items():
        curve = _edge_curve(topo, geom, _edge_by_key(topo, edges, eid))
        n = len(e.params)
        for k in range(n):
            p = e.points[3 * k : 3 * k + 3]
            q = curve.point(e.params[k])
            # the ends are the vertices, which lie on the curve within the edge's tolerance
            assert math.dist(p, q) <= (1e-9 if 0 < k < n - 1 else 1e-6)
            checked += 1
    assert checked > 0


# -- (u, v) and normals ----------------------------------------------------------------
def _surfaces(xt, t):
    """Each face's surface and the side its normals point to, by mesh face. The
    synthetic bodies number no nodes, so with every face done (and no rolling blend,
    which is done last) the mesh's faces are the body's in order."""
    topo, body = _topology(xt)
    geom = Geometry(topo, t.chord_m)
    faces = topo.faces(body)
    assert len(faces) == len(t.face_ids) == t.counts["faces_done"]
    out = []
    for face in faces:
        snode = topo.ref(face, "surface", SURFACE_TYPES, required=True)
        S = geom.surface(snode)
        out.append((S, topo.sense(face) * topo.sense(snode) * S.flip))
    return out


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_each_vertexs_uv_evaluates_back_to_it_and_its_normal_is_the_surfaces(shape):
    xt = SHAPES[shape]()
    t = tessellate_transmit(xt, detail=True)
    d = t.detail
    worst = 0.0
    for f, uv, (S, o) in zip(t.mesh.faces, d.face_uv, _surfaces(xt, t), strict=True):
        for k in range(f.n_vertices):
            v = f.first_vertex + k
            u_, v_ = uv[2 * k], uv[2 * k + 1]
            p = d.points[3 * v : 3 * v + 3]
            worst = max(worst, math.dist(S.point(u_, v_), p))
            n = S.normal(u_, v_)
            # At a pole the normal is the triangles' mean, and the surface's is noise.
            if n is not None and not any(abs(v_ - pv) <= 1e-9 for pv, _q in S.poles):
                assert sum(a * o * b for a, b in zip(n, d.normals[3 * v : 3 * v + 3], strict=True)) > 1 - 1e-9
    # Inside points are the surface's own; boundary points are the edges' samples, on
    # the surface within the edges' tolerance and the chord.
    assert worst <= t.chord_m


def test_a_cylinders_edge_normals_point_out_from_its_axis_and_along_it():
    r, h = 0.005, 0.02
    t = tessellate_transmit(X.cylinder(r, h), detail=True)
    sides = 0
    for e in t.detail.edges.values():
        for normals in e.normals:
            for k in range(len(e.points) // 3):
                x, y, z = e.points[3 * k : 3 * k + 3]
                nx, ny, nz = normals[3 * k : 3 * k + 3]
                if abs(nz) > 0.5:  # a cap: straight up or down, away from the middle
                    assert abs(abs(nz) - 1.0) < 1e-12 and nz * (z - h / 2) > 0
                else:  # the side: out from the axis
                    assert abs(nz) < 1e-12 and abs(nx * x + ny * y - math.hypot(x, y)) < 1e-9
                    sides += 1
    assert sides > 0


def test_a_rim_has_the_side_and_the_cap_as_its_two_faces():
    """Where the cylinder's side meets a cap, each sample carries both normals, a right
    angle apart: what tells a view the rim is an edge, not a smooth join."""
    t = tessellate_transmit(X.cylinder(), detail=True)
    rims = [e for e in t.detail.edges.values() if e.vertices[0] != e.vertices[-1]]  # not the seam
    assert rims
    for e in rims:
        a, b = e.normals
        for k in range(len(e.points) // 3):
            dot = sum(x * y for x, y in zip(a[3 * k : 3 * k + 3], b[3 * k : 3 * k + 3], strict=True))
            assert abs(dot) < 1e-9


# -- what it costs ---------------------------------------------------------------------
def test_the_detailed_call_costs_less_than_half_the_prototypes_memory_a_triangle():
    """The design's prototype needed 4.7 KB a triangle for the whole drawing child; the
    detailed tessellation's peak, the detail included, stays under half of that."""
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        _name, bodies, _w, _n = bodies_of(doc)
        tracemalloc.start()
        try:
            t = tessellate_body(bodies[0], detail=True)
            _now, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    triangles = t.counts["triangles"]
    assert triangles > 1000 and peak / triangles < 4700 / 2
    assert t.detail.nbytes() / triangles < 200  # what the detail itself holds
