"""ACIS SAB (``docs/formats/alibre.md`` section 7): the tokenizer, the entity decoders,
B-splines, the mapping to Parasolid nodes and standalone ``.sab`` files, on synthetic
streams written by ``tests/sab_writers.py``."""

import math

import pytest

import sab_writers as W
from solidseas import export
from solidseas.errors import FormatNotSupportedError, SldFormatError
from solidseas.formats import Limits, open_model
from solidseas.formats.acis import sab
from solidseas.formats.acis.bspline import (
    SplineError,
    Values,
    curve_point,
    read_curve,
    surface_point,
    xt_knots,
)
from solidseas.formats.acis.entities import Cone, Model, Plane, Spline
from solidseas.formats.acis.geometry import bodies, body_faces, build_body
from solidseas.formats.solidworks.parasolid import validate
from solidseas.tessellate import tessellate_transmit

L = Limits()
CM3 = 1e-6  # one cubic centimetre in cubic metres: the writers' unit is the centimetre


def model(sol: W.Solid, **kw) -> Model:
    return Model(sab.read(sol.sab(**kw), L), L)


# --------------------------------------------------------------------------- tokenizer
def test_header_and_records():
    data = W.cube().sab(mm_per_unit=25.4)
    h = sab.read_header(data, L)
    assert (h.signature, h.version, h.mm_per_unit, h.resabs, h.resnor) == (
        "ACIS BinaryFile",
        2100,
        25.4,
        1e-6,
        1e-10,
    )
    assert h.product == "SolidSeas tests" and h.verified
    f = sab.read(data, L)
    names = [r.name for r in f.records]
    assert names[:3] == ["body", "lump", "shell"] and not f.history
    for name, n in (("face", 6), ("loop", 6), ("coedge", 24), ("edge", 12), ("vertex", 8), ("point", 8)):
        assert names.count(name) == n, name
    assert names.count("plane-surface") == 6 and names.count("straight-curve") == 12
    assert f.subtypes == []


def test_type_names_join_their_prefixes():
    f = sab.read(W.cube(color=(1, 0, 0)).sab(persistent_ids=True), L)
    names = {r.name for r in f.records}
    assert {"PersistentID-Alibre-attrib", "rgb_color-st-attrib", "plane-surface"} <= names


def test_subtype_definitions_are_numbered_and_ref_names_them():
    m = model(W.split_box())
    assert len(m.sab.subtypes) == 1  # the definition; the reference is not counted
    first, second = m.indices("spline-surface")
    a, b = m.surface(first), m.surface(second)
    assert isinstance(a, Spline) and isinstance(b, Spline)
    assert a.subtype == b.subtype == "exactsur" and a.bs3 == b.bs3
    assert surface_point(a.bs3, 0.5, 0.5) == pytest.approx((1.0, 0.5, 1.0))


def test_the_decoders_walk_the_topology():
    m = model(W.cube())
    (body,) = bodies(m)
    faces = body_faces(m, body)
    assert len(faces) == 6
    top = [f for f in faces if isinstance(m.surface(m.face(f).surface), Plane) and m.face(f).reversed]
    assert len(top) == 1 and m.surface(m.face(top[0]).surface).normal == (0.0, 0.0, -1.0)
    for f in faces:
        lp = m.loop(m.face(f).loop)
        ce = m.coedge(lp.coedge)
        partner = m.coedge(ce.partner)
        assert partner.edge == ce.edge and partner.reversed != ce.reversed


# --------------------------------------------------------------------------- B-splines
def test_knots_get_one_more_at_each_end():
    assert xt_knots(2, ((0.0, 2), (1.0, 2), (2.0, 2))) == ([0.0, 1.0, 2.0], [3, 2, 3])
    with pytest.raises(SplineError):
        xt_knots(3, ((0.0, 4), (1.0, 4)))  # not the degree at the ends: a convention not verified


def test_a_curve_block_decodes():
    name, vals = W.intcurve(
        2, W.CIRCLE_KNOTS, [(x, y, 0) for x, y, _w in W.CIRCLE9], [w for *_xy, w in W.CIRCLE9]
    )
    tags = bytes(t for t, _v in vals)
    c = Values(tags, [v for _t, v in vals], 4)  # past the sense, "{", "exactcur" and its enum
    cv = read_curve(c, L)
    assert cv.form == "nurbs" and cv.degree == 2 and len(cv.points) == 9 and cv.fit_tolerance == 1e-6
    for t in (0.0, 0.5, 1.7, 3.2, 4.0):
        p = curve_point(cv, t)
        assert math.hypot(p[0], p[1]) == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------- whole bodies
SHAPES = [
    ("cube", lambda: W.cube(1.0), 1.0, 6.0),
    ("split_box", W.split_box, 2.0, 10.0),
    ("cylinder", W.cylinder, 2 * math.pi, 6 * math.pi),
    ("cylinder_inward", lambda: W.cylinder(inward=True), 2 * math.pi, 6 * math.pi),
    ("frustum", W.frustum, math.pi * 2 * 7 / 3, None),
    ("cone_point", W.cone_point, math.pi * 2 / 3, None),
    ("sphere", W.whole_sphere, 4 / 3 * math.pi, 4 * math.pi),
    ("sphere_inside_out", lambda: W.whole_sphere(inside_out=True), 4 / 3 * math.pi, 4 * math.pi),
    ("torus", W.ring_torus, 2 * math.pi**2 * 2 * 0.25, 4 * math.pi**2 * 2 * 0.5),
    ("rational_cylinder", W.rational_cylinder, 2 * math.pi, 6 * math.pi),
    ("elliptic_cylinder", W.elliptic_cylinder, 2 * math.pi, None),
]


@pytest.mark.parametrize(("name", "make", "volume", "area"), SHAPES, ids=[s[0] for s in SHAPES])
def test_a_standalone_sab_file_exports_closed_with_its_volume(name, make, volume, area):
    with open_model(make().sab(), name=f"{name}.sab") as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == ("acis", "sab", "part", "brep")
        assert doc.units == {"length": "cm", "scale_m": 0.01, "source": "file"}
        scene = doc.scene()
        assert scene.counts["faces"] == scene.counts["faces_done"] and not scene.skipped
        pm = export.print_model(doc)
    m = pm.measures()
    assert pm.closed, name
    assert m["volume_m3"] == pytest.approx(volume * CM3, rel=2e-3), name
    if area is not None:
        assert m["area_m2"] == pytest.approx(area * 1e-4, rel=2e-3), name
    assert pm.objects[0].source == "bodies"


@pytest.mark.parametrize(
    ("pole", "axis"),
    [
        ((0, 0, 1), (0, 1, 0)),
        ((1, 0, 0), (0, 1, 0)),
        ((0, 1, 0), (0, 1, 0)),
        ((0, 0.6, 0.8), (0, 0.6, 0.8)),
    ],
    ids=["ring_through_z_poles", "ring_through_x_poles", "pole_inside", "pole_oblique"],
)
def test_a_ring_through_both_poles_becomes_the_xt_spheres_equator(pole, axis):
    """A solid sphere cut by a plane through its axis: the sphere face's one loop, a
    ring, runs through both poles, which SolidSeas' tessellator draws wrongly (at this
    chord, 4 to 8 percent too much volume and 26 to 34 percent too much area). The XT
    sphere takes the ring's normal as its axis instead; a pole off the ring is kept."""
    with open_model(W.half_sphere(pole=pole).sab(), name="half.sab") as doc:
        (ref,) = doc.bodies()
        pm = export.print_model(doc, chord_m=1e-5)
    (sphere,) = [n for n in ref.transmit.nodes if n.type == 53]  # SPHERE
    assert ref.transmit.get(sphere, "axis") == pytest.approx(axis)
    m = pm.measures()
    assert pm.closed
    assert m["volume_m3"] == pytest.approx(2 / 3 * math.pi * CM3, rel=3e-3)
    assert m["area_m2"] == pytest.approx(3 * math.pi * 1e-4, rel=3e-3)


def test_the_bodies_are_parasolid_transmits_that_validate():
    with open_model(W.cylinder().sab(), name="c.sab") as doc:
        (ref,) = doc.bodies()
    assert ref.body_type == "solid" and ref.node == "1"
    assert validate(ref.transmit)["ok"]
    t = tessellate_transmit(ref.transmit)
    assert t.closed and t.counts["faces_done"] == 3


def test_units_colour_and_the_tree():
    with open_model(W.cube(2.0, color=(1.0, 0.5, 0.0)).sab(mm_per_unit=25.4), name="in.sab") as doc:
        assert doc.units["length"] == "in" and doc.units["scale_m"] == 0.0254
        assert [n.kind for n in doc.tree().nodes] == ["object"]
        (obj,) = doc.scene().objects
        assert obj.color == (1.0, 0.5, 0.0, 1.0)
        assert obj.measures()["volume_m3"] == pytest.approx(8 * 0.0254**3, rel=1e-9)


def test_a_body_transform_is_applied_and_warned():
    sol = W.cube(1.0)
    sol.transform = (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (10.0, 0.0, 0.0), 1.0)
    with open_model(sol.sab(), name="moved.sab") as doc:
        scene = doc.scene()
    (obj,) = scene.objects
    box = obj.measures()["box"]
    assert box[0][0] == pytest.approx(0.10) and box[1][0] == pytest.approx(0.11)
    assert "transform_unverified" in {w.code for w in scene.warnings}


def test_an_unmapped_face_is_left_out_and_reported():
    with open_model(W.elliptic_cone().sab(), name="e.sab") as doc:
        scene = doc.scene()
        assert scene.counts["faces"] == 3 and scene.counts["faces_done"] == 2
        assert [s.reason for s in scene.skipped] == ["unsupported_surface"]
        pm = export.print_model(doc)
    assert not pm.closed and "faces_left_out" in {w.code for w in pm.warnings}


def test_a_tolerant_edge_is_read_as_an_ordinary_edge():
    """A ``tedge`` (a tolerance after the edge's own fields) and its ``tcoedge``s, which
    no sample holds: read as an ordinary edge and coedges, its tolerance not carried,
    nothing left out (the format document, 7.6)."""
    recs = W.records_of(W.cube())
    e = W.find(recs, "edge", 0)
    recs[e][0] = "tedge-edge"
    recs[e][1].append(W.d(1e-3))
    for r in recs:
        if r[0] == "coedge" and r[1][7] == (W.PTR, e):
            r[0] = "tcoedge-coedge"
    with open_model(W.stream([(n, v) for n, v in recs]), name="tolerant.sab") as doc:
        scene = doc.scene()
        pm = export.print_model(doc)
    assert scene.counts["faces_done"] == 6 and not scene.skipped and not scene.warnings
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(CM3, rel=1e-9)


def test_a_degenerate_apex_edge_leaves_its_loop():
    m = model(W.cone_point())
    build = build_body(m, bodies(m)[0], L)
    assert build.body_type == "solid" and not build.skipped
    assert isinstance(m.surface(m.face(body_faces(m, bodies(m)[0])[0]).surface), Cone)


# --------------------------------------------------------------------------- refusals
def test_a_sat_text_file_is_refused():
    text = b"700 0 1 0\n@7 SolidSeas 9 ACIS test 24 Thu Jan 01 00:00:00 2026\n10 1e-06 1e-10\n"
    with pytest.raises(FormatNotSupportedError) as err:
        open_model(text, name="part.sat")
    assert err.value.detail == {"rule": "sat_text", "value": "acis"}


@pytest.mark.parametrize("header", [{"version": 700}, {"signature": b"ASM BinaryFile4"}])
def test_an_unverified_sab_version_is_refused(header):
    with pytest.raises(FormatNotSupportedError) as err:
        open_model(W.cube().sab(**header), name="part.sab")
    assert err.value.detail["rule"] == "acis_version"


def test_the_tokenizer_refuses_what_is_not_sab():
    with pytest.raises(SldFormatError):
        sab.read(b"not an ACIS stream at all", L)
    with pytest.raises(SldFormatError):
        sab.read(W.cube().sab() + b"\0", L)  # bytes after the end marker
