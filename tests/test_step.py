"""STEP export (``solidseas.step``) against SOLIDWORKS' own STEP and independent checks.

o02 is exported and compared with SOLIDWORKS' STEP of it (``o02_boxA.step``,
AP203) entity by entity, through a Part 21 re-reader and checkers written for
these tests (``step_support``), which share no code with the writer: the same
counts of every geometric and topological entity, the same vertices, directed
edges, planes and oriented loops, the solid's and the representation's names,
the units and the uncertainty, and only the listed differences (the schema,
AP203's management entities, the context entities, the category). Every fixture
part either converts and passes the checks (syntax, topology, vertices on their
curves and surfaces, each face's normal against SolidSeas' tessellation, each
edge's arc against the source edge) or is refused with its reason.
"""

import json
import math
import os

import pytest

import step_support as T
import xt_bodies as X
from solidseas import cli, model, open_document
from solidseas.errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NothingToExportError,
    NotRepresentableError,
    OutputRefusedError,
    SldLimitError,
)
from solidseas.formats import open_model
from solidseas.formats.solidworks.parasolid import read_file
from solidseas.step import (
    StepModel,
    step_bytes,
    step_configurations,
    step_model,
    step_transmit,
    uncertainty,
    write_step,
)
from solidseas.step import part21 as p21
from solidseas.tessellate import bodies_of
from support import FIXTURES, fixture_path

GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
STAMP = "2026-10-03T00:00:00Z"
SW = T.read((FIXTURES / "o02_boxA.step").read_bytes())
O17 = next(p.name for p in FIXTURES.iterdir() if p.name.startswith("o17_"))
PART_CASES = [
    (name, cfg)
    for name, doc in sorted(GT.items())
    if name.upper().endswith(".SLDPRT")
    for cfg in doc["api"]["configurations"]
]
REFUSED = {("o01_empty.SLDPRT", "Default"), ("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")}
# Geometric and topological entities of SOLIDWORKS' o02 (AP203 and AP214 share them).
SHAPE = (
    "CARTESIAN_POINT",
    "DIRECTION",
    "AXIS2_PLACEMENT_3D",
    "PLANE",
    "VECTOR",
    "LINE",
    "VERTEX_POINT",
    "EDGE_CURVE",
    "ORIENTED_EDGE",
    "EDGE_LOOP",
    "FACE_OUTER_BOUND",
    "ADVANCED_FACE",
    "CLOSED_SHELL",
    "MANIFOLD_SOLID_BREP",
)


def export(name: str, configuration: str | None = None, **options) -> tuple[StepModel, bytes]:
    with open_document(fixture_path(name)) as doc:
        m = step_model(doc, configuration, **options)
    return m, step_bytes(m, time_stamp=STAMP)


def checked(name: str, configuration: str | None = None) -> dict:
    with open_document(fixture_path(name)) as doc:
        m = step_model(doc, configuration)
        _n, bodies, _w, _ = bodies_of(doc, configuration)
    data = step_bytes(m, time_stamp=STAMP)
    got = T.full_check(data, m, [b.transmit for b in bodies])
    got["model"] = m
    return got


def assert_sound(got: dict) -> None:
    """Every independent check passes, and every face and curved edge was compared."""
    assert got["syntax"] == []
    assert got["topology"] == []
    assert got["geometry"]["beyond"] == []
    ori = got["orientation"]
    assert ori["disagree"] == [] and ori["far"] == 0 and ori["not_tessellated"] == 0
    assert ori["agree"] == ori["faces"] == len(got["model"].face_map)
    assert got["arcs"]["wrong"] == [] and got["arcs"]["far"] == []
    assert got["pieces"]["wrong"] == []  # the pieces of every edge cut at a seam cover it once


def _numbered(xt):
    """Synthetic bodies leave node ids 0: number faces, edges and vertices by their index,
    as real files do, so that the oracle can pair faces."""
    for n in xt.nodes:
        if n.type in (14, 16, 18):
            n.vals[0] = n.index
    return xt


def synthetic(xt, **options) -> dict:
    xt = _numbered(xt)
    m = step_transmit(xt, **options)
    data = step_bytes(m, time_stamp=STAMP)
    got = T.full_check(data, m, [xt])
    got["model"], got["data"] = m, data
    return got


# --------------------------------------------------------------------------- o02 against SOLIDWORKS
def _shape_counts(f) -> dict:
    counts = T.box_model(f)["counts"]
    return {k: counts.get(k, 0) for k in SHAPE}


def test_o02_matches_solidworks_step_entity_by_entity():
    m, data = export("o02_boxA.SLDPRT")
    ours = T.read(data)
    assert T.syntax_problems(ours) == []
    a, b = T.box_model(ours), T.box_model(SW)
    assert (
        _shape_counts(ours)
        == _shape_counts(SW)
        == {
            "CARTESIAN_POINT": 27,
            "DIRECTION": 26,
            "AXIS2_PLACEMENT_3D": 7,
            "PLANE": 6,
            "VECTOR": 12,
            "LINE": 12,
            "VERTEX_POINT": 8,
            "EDGE_CURVE": 12,
            "ORIENTED_EDGE": 24,
            "EDGE_LOOP": 6,
            "FACE_OUTER_BOUND": 6,
            "ADVANCED_FACE": 6,
            "CLOSED_SHELL": 1,
            "MANIFOLD_SOLID_BREP": 1,
        }
    )
    assert len(a["vertices"]) == 8 and a["vertices"] == b["vertices"]
    assert (
        len(a["edges"]) == 12 and a["edges"] == b["edges"]
    )  # ends, line point and direction, magnitude 1000
    assert len(a["faces"]) == 6 and a["faces"] == b["faces"]  # planes, normals, senses, oriented loops
    for f in (ours, SW):
        (solid,) = f.of("MANIFOLD_SOLID_BREP")
        assert solid.params[0] == "Boss-Extrude1"
        (rep,) = f.of("ADVANCED_BREP_SHAPE_REPRESENTATION")
        assert rep.params[0] == "o02_boxA"
        items = [f.get(r).name for r in rep.params[1]]
        assert sorted(items) == ["AXIS2_PLACEMENT_3D", "MANIFOLD_SOLID_BREP"]
        (prod,) = f.of("PRODUCT")
        assert prod.params[:3] == ["o02_boxA", "o02_boxA", ""]
        (pd,) = f.of("PRODUCT_DEFINITION")
        assert pd.params[:2] == ["UNKNOWN", ""]
        (pdf,) = f.of("PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE")
        assert pdf.params[0] == "ANY" and pdf.params[3] == "NOT_KNOWN"
        (pds,) = f.of("PRODUCT_DEFINITION_SHAPE")
        assert pds.params[:2] == ["NONE", "NONE"]
        assert T.uncertainty_mm(f) == pytest.approx(1e-5, rel=1e-12)
        (unc,) = f.of("UNCERTAINTY_MEASURE_WITH_UNIT")
        assert unc.params[2:] == ["distance_accuracy_value", "NONE"]
        (ctx,) = f.of("GEOMETRIC_REPRESENTATION_CONTEXT")
        assert ctx.record("REPRESENTATION_CONTEXT") == ["NONE", "WORKASPACE"]
        assert ctx.record("GEOMETRIC_REPRESENTATION_CONTEXT") == [3]
        units = sorted(
            tuple(n for n, _p in f.get(r).records) for r in ctx.record("GLOBAL_UNIT_ASSIGNED_CONTEXT")[0]
        )
        assert units == [
            ("LENGTH_UNIT", "NAMED_UNIT", "SI_UNIT"),
            ("NAMED_UNIT", "PLANE_ANGLE_UNIT", "SI_UNIT"),
            ("NAMED_UNIT", "SI_UNIT", "SOLID_ANGLE_UNIT"),
        ]
        mm = next(
            f.get(r) for r in ctx.record("GLOBAL_UNIT_ASSIGNED_CONTEXT")[0] if f.get(r).has("LENGTH_UNIT")
        )
        assert mm.record("SI_UNIT") == ["MILLI", "METRE"]
    # The differences, each expected: AP214 against AP203.
    assert ours.header_record("FILE_SCHEMA") == [["AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"]]
    assert SW.header_record("FILE_SCHEMA") == [["CONFIG_CONTROL_DESIGN"]]
    ap203_only = {
        "APPROVAL",
        "APPROVAL_DATE_TIME",
        "APPROVAL_PERSON_ORGANIZATION",
        "APPROVAL_ROLE",
        "APPROVAL_STATUS",
        "CALENDAR_DATE",
        "CC_DESIGN_APPROVAL",
        "CC_DESIGN_DATE_AND_TIME_ASSIGNMENT",
        "CC_DESIGN_PERSON_AND_ORGANIZATION_ASSIGNMENT",
        "CC_DESIGN_SECURITY_CLASSIFICATION",
        "COORDINATED_UNIVERSAL_TIME_OFFSET",
        "DATE_AND_TIME",
        "DATE_TIME_ROLE",
        "LOCAL_TIME",
        "ORGANIZATION",
        "PERSON",
        "PERSON_AND_ORGANIZATION",
        "PERSON_AND_ORGANIZATION_ROLE",
        "SECURITY_CLASSIFICATION",
        "SECURITY_CLASSIFICATION_LEVEL",
    }
    sw_names = {e.name for e in SW.entities.values()}
    our_names = {e.name for e in ours.entities.values()}
    assert sw_names - our_names == ap203_only | {"MECHANICAL_CONTEXT", "DESIGN_CONTEXT"}
    assert our_names - sw_names == {"PRODUCT_CONTEXT", "PRODUCT_DEFINITION_CONTEXT"}
    (cat,) = ours.of("PRODUCT_RELATED_PRODUCT_CATEGORY")
    assert cat.params[0] == "part" and SW.of("PRODUCT_RELATED_PRODUCT_CATEGORY")[0].params[0] == "detail"
    assert ours.of("APPLICATION_CONTEXT")[0].params == [
        "core data for automotive mechanical design processes"
    ]
    assert m.exact and not m.partial and m.uncertainty_m == 1e-8
    assert T.planar_volume(ours) == pytest.approx(6000.0, rel=1e-12)


@pytest.mark.parametrize(
    "name, configuration",
    [
        ("o03_boxA_again.SLDPRT", None),
        ("o04_boxA_props.SLDPRT", None),
        ("o05_boxA_props_mat.SLDPRT", None),
        ("o06_boxA_props_mat_cfg.SLDPRT", "Default"),
        ("o13_two_geometry_configs.SLDPRT", "Default"),
        (O17, None),
    ],
)
def test_box_parts_match_solidworks_step(name, configuration):
    _m, data = export(name, configuration)
    a, b = T.box_model(T.read(data)), T.box_model(SW)
    assert _shape_counts(T.read(data)) == _shape_counts(SW)
    assert (a["vertices"], a["edges"], a["faces"]) == (b["vertices"], b["edges"], b["faces"])


def _lifted(model_: dict, z_from: float, z_to: float) -> dict:
    def lift(p):
        return tuple(z_to if (i == 2 and c == z_from) else c for i, c in enumerate(p))

    def edge(e):
        return (lift(e[0]), lift(e[1]), e[2], e[3], lift(e[4]))

    def face(f):
        o, z, x, n, s, loops = f
        return (
            lift(o),
            z,
            x,
            n,
            s,
            tuple((k, tuple((lift(a), lift(b)) for a, b in seq)) for k, seq in loops),
        )

    return {
        "vertices": {lift(v) for v in model_["vertices"]},
        "edges": {edge(e) for e in model_["edges"]},
        "faces": {face(f) for f in model_["faces"]},
    }


def test_o07_is_the_box_31_mm_high():
    m, data = export("o07_boxB_h31.SLDPRT")
    a = T.box_model(T.read(data))
    b = _lifted(T.box_model(SW), 30.0, 31.0)
    assert (a["vertices"], a["edges"], a["faces"]) == (b["vertices"], b["edges"], b["faces"])
    assert T.planar_volume(T.read(data)) == pytest.approx(6200.0, rel=1e-12)


def test_o09_imported_from_solidworks_step_matches_it_as_point_sets_and_planes():
    """o09 was imported from o02_boxA.step itself; the import rebuilt its planes with
    other locations and x directions, so planes are compared as planes."""
    _m, data = export("o09_import_step.SLDPRT")
    a, b = T.box_model(T.read(data)), T.box_model(SW)
    assert a["vertices"] == b["vertices"]
    assert {e[:3] for e in a["edges"]} == {e[:3] for e in b["edges"]}

    def as_plane(f):
        o, z, _x, n, _s, loops = f
        return (z, round(sum(o[i] * z[i] for i in range(3)), 9) + 0.0, n, loops)

    assert {as_plane(f) for f in a["faces"]} == {as_plane(f) for f in b["faces"]}
    (solid,) = T.read(data).of("MANIFOLD_SOLID_BREP")
    assert solid.params[0] == "o02_boxA.step<1>"


# --------------------------------------------------------------------------- every fixture part
@pytest.mark.parametrize("name, configuration", PART_CASES)
def test_every_fixture_part_converts_and_passes_the_checks_or_is_refused(name, configuration):
    if (name, configuration) in REFUSED:
        with open_document(fixture_path(name)) as doc, pytest.raises(NothingToExportError) as exc:
            step_model(doc, configuration)
        assert "does not store the bodies of configuration" in str(exc.value)
        return
    got = checked(name, configuration)
    assert_sound(got)
    m = got["model"]
    truth = GT[name]["api"]["configurations"][configuration]
    assert m.counts["solids"] == truth["solid_bodies"]
    names = sorted(b.name for b in m.bodies)
    assert names == sorted(b["name"] for b in truth["bodies"])
    # the source's faces and edges, before faces round a closed surface were cut in two
    assert m.counts["faces"] - m.counts["split_faces"] == sum(b["faces"] for b in truth["bodies"])
    assert m.counts["edges"] - m.counts["edges_added"] == sum(b["edges"] for b in truth["bodies"])
    assert m.counts["split_faces"] == {"o10": 1, "o11": 2}.get(name[:3], 0)
    lo, hi = T.extent(got["file"])
    box = truth["bounding_box_m"]
    assert lo == pytest.approx(tuple(x * 1000.0 for x in box[:3]), abs=1e-9)
    assert hi == pytest.approx(tuple(x * 1000.0 for x in box[3:]), abs=1e-9)
    assert m.exact and m.uncertainty_m == 1e-8
    for s in got["solids"]:
        assert s.genus == (1 if name.startswith(("o10", "o11")) else 0)


def _midpoint(f, ec) -> tuple:
    """The point halfway along an EDGE_CURVE (mm, rounded), on the arc of its curve from
    its start vertex to its end the way its same_sense says: a seam taken the wrong way
    round its circle has its middle on the other side."""
    c = T.Curve(f, ec.params[3])
    ts, span, sign = T._edge_span(f, ec, c)
    return tuple(round(x, 6) + 0.0 for x in c.point(ts + sign * 0.5 * span))


def _rounded(*points) -> set:
    return {tuple(round(x, 6) + 0.0 for x in p) for p in points}


def _seam_lines(f) -> set:
    """Each LINE edge's ends (mm, rounded), as a set of point pairs."""
    out = set()
    for e in f.of("EDGE_CURVE"):
        if f.get(e.params[3]).name == "LINE":
            a = tuple(round(x, 9) + 0.0 for x in T.point_of_vertex(f, e.params[1]))
            b = tuple(round(x, 9) + 0.0 for x in T.point_of_vertex(f, e.params[2]))
            out.add(tuple(sorted((a, b))))
    return out


def test_o11_curved_converts():
    """o11's hole (a cylinder) and its rounded rim (a torus) go all the way round: each is
    written as two faces cut at u = 0 and u = pi, as SOLIDWORKS 2024 writes them in its
    own STEP of o11 (Split periodic faces on). That file has 14 faces (6 planes, 6
    cylinders, 2 tori), 34 edges, 22 vertices and 16 loops, the same point sets as here:
    the hole's seams the lines x = 15 and x = 25 at y = 15 from z = 0 to 9, the rim's the
    circles of its cross-section through (14, 15, 10) and (26, 15, 10)."""
    got = checked("o11_curved.SLDPRT")
    assert_sound(got)
    f = got["file"]
    kinds = sorted(f.get(e.params[2]).name for e in f.of("ADVANCED_FACE"))
    assert kinds == ["CYLINDRICAL_SURFACE"] * 6 + ["PLANE"] * 6 + ["TOROIDAL_SURFACE"] * 2
    assert len(f.of("EDGE_CURVE")) == 34 and len(f.of("VERTEX_POINT")) == 22
    (solid,) = f.of("MANIFOLD_SOLID_BREP")
    assert solid.params[0] == "Fillet2"
    (s,) = got["solids"]
    assert (s.V, s.E, s.F, s.L, s.genus) == (22, 34, 14, 16, 1)
    assert len(f.of("FACE_OUTER_BOUND")) == 14 and len(f.of("FACE_BOUND")) == 2
    assert {(15.0, 15.0, 0.0), (25.0, 15.0, 0.0), (15.0, 15.0, 9.0), (25.0, 15.0, 9.0)} <= {
        tuple(round(x, 9) + 0.0 for x in T.point_of_vertex(f, v.id)) for v in f.of("VERTEX_POINT")
    }
    assert {((15.0, 15.0, 0.0), (15.0, 15.0, 9.0)), ((25.0, 15.0, 0.0), (25.0, 15.0, 9.0))} <= _seam_lines(f)
    rim = {
        tuple(round(x, 9) + 0.0 for x in T.Frame(f, f.get(e.params[3]).params[1]).o)
        for e in f.of("EDGE_CURVE")
        if f.get(e.params[3]).name == "CIRCLE" and f.get(e.params[3]).params[2] == pytest.approx(1.0)
    }
    assert rim == {(14.0, 15.0, 9.0), (26.0, 15.0, 9.0)}  # the torus's seams: its cross-sections
    m = got["model"]
    assert m.counts["split_faces"] == 2 and m.counts["edges_added"] == 7  # 4 seams, 3 rings now 6 arcs
    # Each seam takes its own arc: the hole's halfway up the hole, the rim's the quarter of
    # its cross-section between the hole's wall and the top face (SOLIDWORKS' middle points).
    q = math.sqrt(0.5)
    assert {_midpoint(f, e) for e in _seams(f, m)} == _rounded(
        (15.0, 15.0, 4.5), (25.0, 15.0, 4.5), (14.0 + q, 15.0, 9.0 + q), (26.0 - q, 15.0, 9.0 + q)
    )
    # The fillets' eight arcs are whole source edges; the three rings were cut in two, each
    # source ring covered once by its two pieces.
    assert got["arcs"]["edges"] == 8 and got["arcs"]["right"] == 8
    assert got["pieces"]["sources"] == 3 and got["pieces"]["right"] == 3 and got["pieces"]["pieces"] == 6
    lo, hi = T.extent(f)
    assert lo == pytest.approx((0.0, 0.0, 0.0), abs=1e-9) and hi == pytest.approx(
        (40.0, 30.0, 10.0), abs=1e-9
    )


def test_o10_hole_is_cut_at_its_seams_as_solidworks_writes_it():
    """o10's hole is written as two half cylinders, like SOLIDWORKS' own STEP of o10: 8
    faces, 18 edges, 12 vertices, the seams along the hole at x = 7.5 and x = 2.5."""
    got = checked("o10_import_step_cut.SLDPRT")
    assert_sound(got)
    f = got["file"]
    (s,) = got["solids"]
    assert (s.V, s.E, s.F, s.genus) == (12, 18, 8, 1)
    assert {((2.5, 10.0, 0.0), (2.5, 10.0, 30.0)), ((7.5, 10.0, 0.0), (7.5, 10.0, 30.0))} <= _seam_lines(f)
    kinds = sorted(f.get(e.params[2]).name for e in f.of("ADVANCED_FACE"))
    assert kinds == ["CYLINDRICAL_SURFACE"] * 2 + ["PLANE"] * 6


def test_split_periodic_off_writes_closed_faces_whole():
    m, data = export("o11_curved.SLDPRT", split_periodic=False)
    f = T.read(data)
    assert len(f.of("ADVANCED_FACE")) == 12 and len(f.of("EDGE_CURVE")) == 27
    assert m.counts["split_faces"] == 0 and m.counts["edges_added"] == 0 and not m.edge_pieces


def _data_lines(
    data: bytes, drop=("PRODUCT(", "ADVANCED_BREP_SHAPE_REPRESENTATION(", "MANIFOLD_SOLID_BREP(")
) -> list[str]:
    text = data.decode("ascii").split("DATA;\n", 1)[1]
    return [
        ln.split("=", 1)[1]
        for ln in text.splitlines()
        if ln.startswith("#") and not ln.split("=", 1)[1].startswith(drop)
    ]


@pytest.mark.parametrize(
    "part, exported",
    [
        ("o11_curved.SLDPRT", "o11_curved.x_b"),
        ("o02_boxA.SLDPRT", "o02_boxA.x_b"),
        ("o02_boxA.SLDPRT", "o02_boxA.x_t"),
        ("o07_boxB_h31.SLDPRT", "o07_boxB_h31.x_b"),
        ("o12_multibody.SLDPRT", "o12_multibody.x_b"),
    ],
)
def test_the_part_and_solidworks_own_parasolid_export_give_the_same_step(part, exported):
    """The partition's bodies and SOLIDWORKS' own .x_b or .x_t of them map to the same
    entities, in the same order (only the names differ)."""
    _m, data = export(part)
    xt = read_file((FIXTURES / exported).read_bytes())
    m2 = step_transmit(xt, name="x")
    data2 = step_bytes(m2, time_stamp=STAMP)
    if part.startswith("o12"):  # two bodies: compare as sets of solids
        a, b = T.box_model(T.read(data)), T.box_model(T.read(data2))
        assert (a["vertices"], a["edges"], a["faces"]) == (b["vertices"], b["edges"], b["faces"])
        assert T.planar_volume(T.read(data2)) == pytest.approx(8000.0, rel=1e-12)
    else:
        assert _data_lines(data) == _data_lines(data2)


def test_o12_two_solids_with_their_body_names():
    """Both of o12's bodies are shown in SOLIDWORKS, and the part says so: both are
    written, with no warning that one might be hidden."""
    got = checked("o12_multibody.SLDPRT")
    assert_sound(got)
    m = got["model"]
    assert sorted(s.name for s in got["solids"]) == ["Boss-Extrude1", "Boss-Extrude2"]
    assert m.warnings == ()
    assert T.planar_volume(got["file"]) == pytest.approx(8000.0, rel=1e-12)


# --------------------------------------------------------------------------- hidden bodies
def _ident(xt, node) -> str | None:
    target = xt.by_index().get(xt.get(node, "identifier"))
    s = xt.get(target, "string") if target is not None else None
    if isinstance(s, list):
        s = "".join(x if isinstance(x, str) else chr(x) for x in s)
    return s


def _set_shown(xt, flag) -> None:
    """Set the BODY's shown flag (FORMAT.md 10.9) to ``flag``, or take the attribute off
    the body (None)."""
    from solidseas.formats.solidworks.parasolid import SHOWN_ATTRIBUTE

    xt._hidden = None  # body_hidden works the flags out once per transmit: again after a change
    idx = xt.by_index()
    body = next(n for n in xt.nodes if n.type == 12)
    defs = {n.index for n in xt.nodes if n.type == 80 and _ident(xt, n) == SHOWN_ATTRIBUTE}
    for n in xt.nodes:
        if n.type == 81 and xt.get(n, "definition") in defs and xt.get(n, "owner") == body.index:
            if flag is None:
                n.vals[xt.field_names(81).index("owner")] = 0
                return
            for ref in xt.get(n, "fields"):
                v = idx.get(ref)
                if v is not None and v.type == 82:
                    v.vals[xt.field_names(82).index("values")] = [flag]
            return
    raise AssertionError("no shown attribute on the body")


def _with_flags(monkeypatch, flags, sheets=()) -> None:
    """Every part opened from now gives its bodies these shown flags, in order; a body
    whose index is in ``sheets`` is replaced, under its own name, by a sheet (a band of a
    torus, :func:`xt_bodies.torus_band`), which carries no shown flag."""
    import dataclasses

    import solidseas.tessellate as tess

    real = getattr(tess.bodies_of, "unflagged", tess.bodies_of)  # called again: the flags replace the last

    def flagged(doc, configuration=None, **kw):
        cfg, bodies, *rest = real(doc, configuration, **kw)
        out = []
        for k, b in enumerate(bodies):
            if k < len(flags):
                _set_shown(b.transmit, flags[k])
            if k in sheets:
                b = dataclasses.replace(b, body_type="sheet", transmit=X.torus_band(0.01, 0.003, -1.0, 1.0))
            out.append(b)
        return (cfg, out, *rest)

    flagged.unflagged = real
    monkeypatch.setattr(tess, "bodies_of", flagged)


def test_a_bodys_hidden_state_is_its_shown_attribute():
    """BODY_IN_LIGHTWEIGHT_PERM's integer: 1 shown, 0 hidden; anything else, or no such
    attribute (most imported bodies), is not known."""
    from solidseas.formats.solidworks.parasolid import body_hidden

    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        bodies = doc.parasolid().bodies
    for b in bodies:
        xt = b.transmit
        body = next(n for n in xt.nodes if n.type == 12)
        assert body_hidden(xt, body) is False
        for flag, want in ((0, True), (1, False), (2, None), (None, None)):
            _set_shown(xt, flag)
            assert body_hidden(xt, body) is want
    with open_document(fixture_path("o09_import_step.SLDPRT")) as doc:
        (b,) = doc.parasolid().bodies  # an imported (local) body: no such attribute
    assert body_hidden(b.transmit, next(n for n in b.transmit.nodes if n.type == 12)) is None


def test_hidden_bodies_are_worked_out_once_per_transmit_and_survive_crafted_text(monkeypatch):
    """One pass over a transmit's attributes answers for all its bodies; a code unit
    outside Unicode in an attribute's name (a crafted file) is dropped, never a bare
    ValueError out of the export."""
    from solidseas.formats.solidworks import parasolid as ps

    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        xt = doc.parasolid().bodies[0].transmit
    body = next(n for n in xt.nodes if n.type == 12)
    calls = []
    real = ps._text
    monkeypatch.setattr(ps, "_text", lambda *a: calls.append(1) or real(*a))
    assert ps.body_hidden(xt, body) is False
    first = len(calls)
    assert ps.body_hidden(xt, body) is False and len(calls) == first  # not read again
    monkeypatch.undo()

    class Crafted:  # a name stored as code units, two of them outside Unicode
        def get(self, _node, _field):
            return [ord("O"), 0x110000, ord("K"), -5, 0]

    assert ps._text(Crafted(), object()) == "OK"


def test_hidden_bodies_are_left_out_as_solidworks_leaves_them_out(monkeypatch):
    """A part whose second body is hidden: SOLIDWORKS' STEP holds the first only, and so
    does this one, saying so; include_hidden writes both."""
    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        both = T.planar_volume(T.read(step_bytes(step_model(doc), time_stamp=STAMP)))
    _with_flags(monkeypatch, [1, 0])
    m, data = export("o12_multibody.SLDPRT")
    f = T.read(data)
    assert [(b.name, b.written, b.reason) for b in m.bodies] == [
        ("Boss-Extrude2", True, None),
        ("Boss-Extrude1", False, "hidden"),
    ]
    assert m.counts["solids"] == 1 and m.counts["bodies_left_out"] == 1 and not m.partial
    assert [s.params[0] for s in f.of("MANIFOLD_SOLID_BREP")] == ["Boss-Extrude2"]
    # (o12's display mesh shows both bodies, as they are shown there: the box warning is this
    # test's own doing, a part with a hidden body does not display it)
    assert [w.code for w in m.warnings] == ["bodies_left_out", "step_differs_from_display"]
    w = m.warnings[0]
    assert "1 body is hidden in SOLIDWORKS and not written" in w
    first = T.planar_volume(f)
    _with_flags(monkeypatch, [0, 1])
    _m, data = export("o12_multibody.SLDPRT")
    assert first + T.planar_volume(T.read(data)) == pytest.approx(both, rel=1e-12) and 0 < first < both
    m, data = export("o12_multibody.SLDPRT", include_hidden=True)
    assert m.counts["solids"] == 2 and m.warnings == ()
    assert T.planar_volume(T.read(data)) == pytest.approx(both, rel=1e-12)


def test_a_part_whose_every_body_is_hidden_has_nothing_to_export(monkeypatch):
    """Said in words the viewer can show: no option of the library is named."""
    _with_flags(monkeypatch, [0, 0])
    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        with pytest.raises(NothingToExportError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "hidden"} and "hidden in SOLIDWORKS" in str(exc.value)
    assert "include_hidden" not in str(exc.value)


def test_a_part_that_shows_only_sheets_asks_for_sheets_whatever_it_hides(monkeypatch):
    """o12 with one body a sheet, shown, and the other, a solid, hidden. Asked for solids
    only (the viewer's and 3D Print's first try), the export says that the bodies the
    part shows are sheets (rule sheets_not_asked, on which File > Export STEP asks again
    with sheets), not that every body is hidden; asked for sheets too, it writes the
    sheet and leaves the hidden solid out."""
    _with_flags(monkeypatch, [1, 0], sheets=(0,))
    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        with pytest.raises(NothingToExportError) as exc:
            step_model(doc)
        assert exc.value.detail == {"rule": "sheets_not_asked"}
        assert "the bodies it shows are sheets" in str(exc.value)
        m, data = export("o12_multibody.SLDPRT", body_types=("solid", "sheet"))
    assert [(b.name, b.kind, b.written, b.reason) for b in m.bodies] == [
        ("Body", "sheet", True, None),  # the stand-in sheet carries no body name
        ("Boss-Extrude1", "solid", False, "hidden"),
    ]
    f = T.read(data)
    assert m.counts["sheets"] == 1 and m.counts["solids"] == 0 and len(f.of("SHELL_BASED_SURFACE_MODEL")) == 1
    # A part with no solid shown and none hidden says the same, as before.
    _with_flags(monkeypatch, [1, 1], sheets=(0, 1))
    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        with pytest.raises(NothingToExportError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "sheets_not_asked"}
    assert "the part's bodies are sheets" in str(exc.value)


def test_several_bodies_of_unknown_state_are_warned_about(monkeypatch):
    """Only where the part does not say whether a body is hidden, and it has several,
    is the export warned that it may write one SOLIDWORKS would leave out."""
    _with_flags(monkeypatch, [1, None])
    m, _data = export("o12_multibody.SLDPRT")
    assert m.counts["solids"] == 2
    (w,) = m.warnings
    assert w.code == "step_hidden_bodies_unknown" and "whether one of them is hidden" in w
    m, _data = export("o12_multibody.SLDPRT", include_hidden=True)
    assert m.warnings == ()


def test_cli_include_hidden(capsys, tmp_path, monkeypatch):
    import solidseas.step as S

    seen = {}
    real = S.step_model

    def spy(doc, configuration=None, **options):
        seen.update(options)
        return real(doc, configuration, **options)

    monkeypatch.setattr(S, "step_model", spy)
    part = str(fixture_path("o12_multibody.SLDPRT"))
    code, _env = _run(capsys, "export", part, "--format", "step", "--include-hidden", "-o", str(tmp_path))
    assert code == 0 and seen["include_hidden"] is True


def test_o10_and_o11_outer_bounds_come_from_orientation_not_order():
    """Their planar faces with a hole list the hole's ring loop first; the outer bound
    is the loop that runs counter-clockwise about the outward normal."""
    for name in ("o10_import_step_cut.SLDPRT", "o11_curved.SLDPRT"):
        f = checked(name)["file"]
        holed = 0
        for face in f.of("ADVANCED_FACE"):
            bounds = [f.get(b) for b in face.params[1]]
            if len(bounds) < 2:
                continue
            surface = f.get(face.params[2]).name
            outer = [b for b in bounds if b.name == "FACE_OUTER_BOUND"]
            if surface != "PLANE":
                assert outer == []  # a cylinder's or a torus's two rings: neither is outer
                continue
            holed += 1
            (ob,) = outer
            loop = f.get(ob.params[1])
            assert len(loop.params[1]) >= 4  # the rectangle's, not the hole's
            first = f.get(bounds[0].params[1])
            # The file's order put the hole first: its ring, cut in two arcs at the seams of
            # the hole's cylinder.
            assert len(first.params[1]) == 2
        assert holed == 2


def test_o13_configurations_give_their_own_heights():
    for cfg, height in (("Default", 30.0), ("Tall", 45.0)):
        _m, data = export("o13_two_geometry_configs.SLDPRT", cfg)
        lo, hi = T.extent(T.read(data))
        assert hi[2] - lo[2] == pytest.approx(height, abs=1e-9)
    with open_document(fixture_path("o13_two_geometry_configs.SLDPRT")) as doc:
        assert step_configurations(doc) == ["Default", "Tall"]
    with open_document(fixture_path("o06_boxA_props_mat_cfg.SLDPRT")) as doc:
        assert step_configurations(doc) == ["Default"]


def test_o17_names_are_encoded():
    _m, data = export(O17)
    assert data.isascii()
    f = T.read(data)
    stem = O17[: -len(".SLDPRT")]
    (prod,) = f.of("PRODUCT")
    assert prod.params[0] == stem
    assert "\\X2\\" in data.decode("ascii")
    assert f.header_record("FILE_NAME")[0] == f"{stem}.step"


def test_refusals_of_documents_without_bodies():
    with open_document(fixture_path("o01_empty.SLDPRT")) as doc, pytest.raises(NothingToExportError):
        step_model(doc)
    with open_document(fixture_path("o18_drw_boxA.SLDDRW")) as doc, pytest.raises(NothingToExportError):
        step_model(doc)
    with open_document(fixture_path("o16_asm_features.SLDASM")) as doc:  # an instance with no bodies to write
        with pytest.raises(NotRepresentableError, match="o06_boxA_props_mat_cfg-1"):
            step_model(doc)  # assemblies: tests/test_step_assembly.py
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        with pytest.raises(ConfigurationNotFoundError):
            step_model(doc, "Nope")
        for bad in (
            {"body_types": ("wire",)},
            {"body_types": "solid"},
            {"max_faces": 0},
            {"max_seconds": -1},
            {"fit_tolerance_m": 0.0},
            {"name": 3},
        ):
            with pytest.raises(InvalidArgumentError):
                step_model(doc, **bad)


# --------------------------------------------------------------------------- the file
def test_header_and_writing_rules(tmp_path):
    m, _data = export("o02_boxA.SLDPRT")
    out = tmp_path / "box.stp"
    res = write_step(m, out, time_stamp=STAMP)
    data = out.read_bytes()
    assert res.bytes == len(data) and res.format == "step" and res.path == str(out)
    f = T.read(data)
    desc = f.header_record("FILE_DESCRIPTION")
    assert desc == [["STEP AP214"], "2;1"]
    name = f.header_record("FILE_NAME")
    assert name[0] == "box.stp" and name[1] == STAMP and name[2] == [""] and name[3] == [""]
    assert name[4].startswith("SolidSeas ") and name[5] == "SOLIDWORKS 2024"
    with pytest.raises(OutputRefusedError) as exc:
        write_step(m, out)
    assert exc.value.detail["rule"] == "exists"
    write_step(m, out, overwrite=True)
    with pytest.raises(OutputRefusedError):
        write_step(m, tmp_path)
    with pytest.raises(SldLimitError) as exc:
        write_step(m, tmp_path / "small.step", max_bytes=100)
    assert exc.value.detail["limit"] == "max_bytes" and not (tmp_path / "small.step").exists()
    assert sorted(os.listdir(tmp_path)) == ["box.stp"]
    # the time stamp is the time of writing unless fixed
    stamp = T.read(step_bytes(m)).header_record("FILE_NAME")[1]
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T"


def test_same_model_same_bytes():
    a = export("o11_curved.SLDPRT")[1]
    b = export("o11_curved.SLDPRT")[1]
    assert a == b


def test_limits():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        for options, limit in (
            ({"max_faces": 5}, "max_faces"),
            ({"max_entities": 50}, "max_entities"),
            ({"max_seconds": 0.0}, "max_seconds"),
        ):
            with pytest.raises(SldLimitError) as exc:
                step_model(doc, **options)
            assert exc.value.detail["limit"] == limit


def test_numbers_and_strings_as_part21_writes_them():
    assert [p21.real(x) for x in (0.0, -0.0, 20.0, 1e-5, -2.5, 0.1, 1234.5, 1e20)] == [
        "0.",
        "0.",
        "20.",
        "1.E-05",
        "-2.5",
        "0.1",
        "1234.5",
        "1.E+20",
    ]
    assert p21.real(0.1 + 0.2) == "0.3"  # 15 digits: no binary noise
    assert p21.mm(0.0123) == 12.3
    with pytest.raises(ValueError):
        p21.real(math.nan)
    for s in ("plain", "it's", "back\\slash", "Ð´ÐµÑ‚Ð°Ð»ÑŒ", "mixed Ã© and ðŸ˜€ and ä¸­", "tab\there"):
        lit = p21.text(s)
        assert lit.isascii()
        assert T.decode_string(lit) == s.replace("\t", "")
    assert p21.text("x" * 300) == "'" + "x" * 256 + "'"


def test_uncertainty_covers_the_deviation():
    assert uncertainty(None) == 1e-8
    assert uncertainty(1e-9) == 1e-8
    assert uncertainty(1e-8) == 2e-8  # 1.5e-8 rounded up
    assert uncertainty(9e-8) == 2e-7
    assert uncertainty(4e-7) == 1e-6
    assert uncertainty(1e-6) == 2e-6


# --------------------------------------------------------------------------- synthetic bodies
@pytest.mark.parametrize(
    "shape, genus, kinds",
    [
        (X.sphere, 0, {"SPHERICAL_SURFACE"}),
        (X.torus, 1, {"TOROIDAL_SURFACE"}),
        (X.cylinder, 0, {"CYLINDRICAL_SURFACE", "PLANE"}),
        (X.hemisphere, 0, {"SPHERICAL_SURFACE", "PLANE"}),
        (X.cone, 0, {"CONICAL_SURFACE", "PLANE"}),
        (X.nurbs_cylinder, 0, {"B_SPLINE_SURFACE", "PLANE"}),
        (X.split_box, 0, {"PLANE"}),
    ],
)
def test_synthetic_solids(shape, genus, kinds):
    got = synthetic(shape())
    assert_sound(got)
    (s,) = got["solids"]
    assert s.genus == genus
    f = got["file"]
    assert {
        f.get(face.params[2]).name if not f.get(face.params[2]).complex else "B_SPLINE_SURFACE"
        for face in f.of("ADVANCED_FACE")
    } == kinds


def test_faces_without_loops_get_seams():
    for shape, edges in ((X.sphere, 1), (X.torus, 2)):
        got = synthetic(shape())
        f = got["file"]
        (face,) = f.of("ADVANCED_FACE")
        (bound,) = face.params[1]
        loop = f.get(f.get(bound).params[1])
        uses = [f.get(r).params[3] for r in loop.params[1]]
        assert len(uses) == 2 * edges and len(set(uses)) == edges  # each seam edge once each way
        assert got["model"].counts["faces"] == 1


Q = 10.0 * math.sqrt(0.5)
SIDE = ((5.0, 0.0, 10.0), (-5.0, 0.0, 10.0))  # halfway up the side at u = 0 and pi
CUT_SHAPES = [
    # a band between two rings: the seams the lines along the side at u = 0 and pi
    (X.cylinder, {}, "CYLINDRICAL_SURFACE", "LINE", SIDE),
    # closed rows of control points: the B-spline's own iso-curves at u = 0 and half its range
    (X.nurbs_cylinder, {}, "B_SPLINE_SURFACE", "B_SPLINE_CURVE_WITH_KNOTS", SIDE),
    # a cap to the north pole: the quarter meridians from the rim up, not round under the sphere
    (X.hemisphere, {}, "SPHERICAL_SURFACE", "CIRCLE", ((Q, 0.0, Q), (-Q, 0.0, Q))),
    # a cap to the apex: the lines from the rim up to it
    (X.cone, {}, "CONICAL_SURFACE", "LINE", ((2.5, 0.0, 5.0), (-2.5, 0.0, 5.0))),
    # a sheet, a band of a ring torus round its outside (minor angles -1 to 1): the arcs of
    # its cross-sections across the outside, not round the inside of the torus
    (
        lambda: X.torus_band(0.01, 0.003, -1.0, 1.0),
        {"body_types": ("solid", "sheet")},
        "TOROIDAL_SURFACE",
        "CIRCLE",
        ((13.0, 0.0, 0.0), (-13.0, 0.0, 0.0)),
    ),
]


@pytest.mark.parametrize("shape, options, kind, seam, middles", CUT_SHAPES)
def test_faces_round_a_closed_surface_are_cut_at_their_seams(shape, options, kind, seam, middles):
    """A face that goes all the way round its surface is written as two, cut along the
    surface's own iso-parameter curves at u = 0 and u = pi: each half has one outer
    bound, each seam is used once each way and takes the arc of its curve that crosses
    the face, and every check holds."""
    got = synthetic(shape(), **options)
    assert_sound(got)
    f, m = got["file"], got["model"]
    faces = [e for e in f.of("ADVANCED_FACE") if _surface_kind(f, e) == kind]
    assert len(faces) == 2 and m.counts["split_faces"] == 1
    for face in faces:
        (bound,) = face.params[1]
        assert f.get(bound).name == "FACE_OUTER_BOUND"
    seams = _seams(f, m)
    assert len(seams) == 2 and {_curve_kind(f, e) for e in seams} == {seam}
    assert {_midpoint(f, e) for e in seams} == _rounded(*middles)
    assert got["pieces"]["wrong"] == [] and got["pieces"]["sources"] == len(m.edge_pieces) // 2


def _read_back(data: bytes) -> tuple[float, float, int]:
    """SolidSeas' own STEP reader on an exported file: its area (mm2) and volume (mm3)
    over every object, and the faces it skipped."""
    from solidseas.formats import open_model

    with open_model(data, name="t.step") as doc:
        s = doc.scene()
        ms = [s.objects[it.object].measures() for it in s.items]
        skipped = (s.counts.get("faces") or 0) - (s.counts.get("faces_done") or 0)
    return sum(x["area_m2"] for x in ms) * 1e6, sum(x["volume_m3"] for x in ms) * 1e9, skipped


@pytest.mark.parametrize(
    "name, area, volume",
    [
        ("cylinder", 2 * math.pi * 5 * 20 + 2 * math.pi * 25, math.pi * 25 * 20),
        ("hemisphere", 3 * math.pi * 100, 2 / 3 * math.pi * 1000),
        ("cone", math.pi * 5 * math.hypot(5, 10) + math.pi * 25, math.pi * 25 * 10 / 3),
        ("torus_band", 2 * math.pi * 3 * (20 + 6 * math.sin(1.0)), None),
        ("window", 2 * math.pi * 5 * 20 - 5 * 0.6 * 20 / 3, None),
        ("windows", 2 * math.pi * 5 * 20 - 16 * 5 * 0.24 * 20 / 3, None),
    ],
)
def test_cut_faces_read_back_to_their_true_area_and_volume(name, area, volume):
    """Read back by SolidSeas' own STEP reader, which shares no code with the writer, the
    halves of each cut face cover the face once: the file's area (and a solid's volume)
    is the shape's own, within the reader's chord, and no face is skipped. A seam taken
    the wrong way round its circle, or a window given to the half that does not hold it,
    adds or takes away a piece of surface."""
    sheets = {"body_types": ("solid", "sheet")}
    xt, options = {
        "cylinder": (X.cylinder(), {}),
        "hemisphere": (X.hemisphere(), {}),
        "cone": (X.cone(), {}),
        "torus_band": (X.torus_band(0.01, 0.003, -1.0, 1.0), sheets),
        "window": (windowed_band(), sheets),
        "windows": (windowed_band(tuple((k * math.pi / 8, 0.12) for k in range(16))), sheets),
    }[name]
    got = synthetic(xt, **options)
    assert got["model"].counts["split_faces"] == 1
    a, v, skipped = _read_back(got["data"])
    assert skipped == 0 and a == pytest.approx(area, rel=1e-2)
    if volume is not None:
        assert v == pytest.approx(volume, rel=1e-2)


def swept_cylinder(r: float = 0.005, h: float = 0.02):
    """:func:`xt_bodies.cylinder` with its side a SWEPT_SURF: the bottom circle swept up
    the axis, written as a SURFACE_OF_LINEAR_EXTRUSION of a closed curve."""
    b = X.XtBuilder()
    section = b.circle((0, 0, 0), X.Z, X.X, r)
    side = b.node(67, section=section, sweep=(0.0, 0.0, h), scale=1.0, sense="+")
    bottom = b.edge(b.circle((0, 0, 0), X.Z, X.X, r))
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r))
    b.face(side, "+", [[(bottom, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), X.Z, X.X), "-", [[(bottom, "-")]])
    b.face(b.plane((0, 0, h), X.Z, X.X), "+", [[(top, "+")]])
    return b.body([bottom, top])


def test_a_band_on_an_extrusion_of_a_closed_curve_is_cut():
    got = synthetic(swept_cylinder())
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert len(f.of("SURFACE_OF_LINEAR_EXTRUSION")) == 1 and m.counts["split_faces"] == 1
    assert {_curve_kind(f, e) for e in _seams(f, m)} == {"LINE"}
    assert {((5.0, 0.0, 0.0), (5.0, 0.0, 20.0)), ((-5.0, 0.0, 0.0), (-5.0, 0.0, 20.0))} <= _seam_lines(f)


def _seams(f, m) -> list:
    """The edges that are no source edge or piece of one: the seams the cuts made."""
    return [e for e in f.of("EDGE_CURVE") if e.id not in m.edge_map and e.id not in m.edge_pieces]


def _surface_kind(f, face) -> str:
    s = f.get(face.params[2])
    return s.name if not s.complex else "B_SPLINE_SURFACE"


def _curve_kind(f, ec) -> str:
    c = f.get(ec.params[3])
    return c.name if not c.complex else "B_SPLINE_CURVE_WITH_KNOTS"


def test_a_cap_meets_its_seams_at_the_pole():
    got = synthetic(X.hemisphere())
    f = got["file"]
    north = (0.0, 0.0, 10.0)
    seams = _seams(f, got["model"])
    ends = {tuple(round(x, 9) + 0.0 for x in T.point_of_vertex(f, e.params[2])) for e in seams}
    assert ends == {north}  # both seams run from the rim up to the pole


def tilted_cap(R: float, gap: float, alpha: float, theta: float = 0.6):
    """A sphere of radius ``R`` (axis z) cut by a tilted plane: the cap round its south
    pole and the disc that closes it. The cap's centre lies ``theta`` from the pole
    towards the angle ``alpha`` round z, and its rim passes ``gap`` (metres, along the
    sphere) from the pole on the far side, at the angle ``alpha + pi``."""
    n = (math.sin(theta) * math.cos(alpha), math.sin(theta) * math.sin(alpha), -math.cos(theta))
    c = tuple(R * math.cos(theta + gap / R) * x for x in n)
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    k = sum(p * q for p, q in zip(a, n, strict=True))
    x = tuple(p - k * q for p, q in zip(a, n, strict=True))
    x = tuple(p / math.hypot(*x) for p in x)
    b = X.XtBuilder()
    rim = b.edge(b.circle(c, n, x, R * math.sin(theta + gap / R)))
    b.face(b.sphere((0, 0, 0), R, X.Z, X.X), "+", [[(rim, "+")]])
    b.face(b.plane(c, n, x), "-", [[(rim, "-")]])
    return b.body([rim])


@pytest.mark.parametrize("alpha", [0.0, math.pi / 2])
def test_a_cap_whose_rim_passes_close_to_its_pole_is_written_whole(alpha):
    """A cap of a 1.27 mm sphere whose rim passes half a micrometre from the pole (two
    corpus parts have such caps 50 nm off). Cut at u = 0 and pi, one seam would be that
    short, or one half a sliver no wider (alpha pi/2), and OCCT read such files with
    faces of no area, one of them invalid: it is written whole. The same cap with its
    rim 0.3 mm off the pole is cut, its seams the meridians from the rim to the pole."""
    from solidseas.step.mapper import FACTS

    before = FACTS["seam_near_pole:SPHERICAL_SURFACE"]
    got = synthetic(tilted_cap(1.27e-3, 0.5e-6, alpha))
    assert_sound(got)
    assert got["model"].counts["split_faces"] == 0 and len(got["file"].of("ADVANCED_FACE")) == 2
    assert FACTS["seam_near_pole:SPHERICAL_SURFACE"] == before + 1
    got = synthetic(tilted_cap(1.27e-3, 3e-4, alpha))
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert m.counts["split_faces"] == 1
    south = (0.0, 0.0, -1.27)
    seams = _seams(f, m)
    assert len(seams) == 2
    for e in seams:  # from the rim to the pole along the meridians at u = 0 and pi
        assert _rounded(T.point_of_vertex(f, e.params[2])) == _rounded(south)
        p = _midpoint(f, e)
        assert p[1] == 0.0 and math.dist(p, (0.0, 0.0, 0.0)) == pytest.approx(1.27, abs=1e-6)  # rounded
    assert _read_back(got["data"])[2] == 0  # SolidSeas' reader draws both halves


@pytest.mark.parametrize("share, cut", [(3e-4, False), (0.05, False), (0.1, False), (0.25, True)])
def test_a_cap_is_cut_only_when_its_pole_keeps_15_percent_of_its_reach_from_its_rim(share, cut):
    """A cap of a 50 mm sphere whose rim passes 28 um to 23 mm from its pole, more than a
    micrometre but a share of the 93 mm the rim reaches from it. OCCT read the halves of
    such caps, cut, with edges it had to correct or meshes left open up to 7 % of that
    reach (this one, at 5 %, with thousands of open mesh edges), and none from 8.4 %:
    within 15 % the cap is written whole; at 25 % it is cut."""
    R, theta = 0.05, 1.2
    got = synthetic(tilted_cap(R, share * 2.0 * R * math.sin(theta), 1.1, theta))
    assert_sound(got)
    assert got["model"].counts["split_faces"] == (1 if cut else 0)


def test_a_cap_whose_rim_passes_close_to_the_other_pole_is_cut():
    """A cap round a 50 mm sphere's south pole, keeping a quarter of its reach from it,
    whose rim passes 50 um outside the north pole: the rule is the cap's own pole's.
    OCCT read the halves of such caps without a message, an open mesh or a face of no
    area, as it did those whose rim passed close to the other pole and kept 8 % of its
    reach from its own."""
    R, theta = 0.05, 1.3
    got = synthetic(tilted_cap(R, R * (math.pi - 2.0 * theta - 1e-3), 1.1, theta))
    assert_sound(got)
    assert got["model"].counts["split_faces"] == 1


def notched_band(gap: float, a: float = 0.3, r: float = 0.005, h: float = 0.02):
    """A sheet: a cylinder's band from z = 0 to h whose top edge dips, between the angles
    -a and a, to ``gap`` above the bottom ring: down a line along the axis, along an
    arc and back up."""
    b = X.XtBuilder()

    def at(ang, z):
        return b.vertex((r * math.cos(ang), r * math.sin(ang), z))

    tm, tp, gm, gp = at(-a, h), at(a, h), at(-a, gap), at(a, gap)
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r), tp, tm)  # the long way round, +a to -a
    low = b.edge(b.circle((0, 0, gap), X.Z, X.X, r), gm, gp)  # across u = 0
    left = b.edge(b.line((r * math.cos(-a), r * math.sin(-a), 0), X.Z), gm, tm)
    right = b.edge(b.line((r * math.cos(a), r * math.sin(a), 0), X.Z), gp, tp)
    bottom = b.edge(b.circle((0, 0, 0), X.Z, X.X, r))
    upper = [(top, "-"), (right, "-"), (low, "-"), (left, "+")]
    b.face(b.cylinder((0, 0, 0), X.Z, r, X.X), "+", [[(bottom, "+")], upper])
    return b.body([top, low, left, right, bottom], body_type=3)


def test_a_seam_shorter_than_a_micrometre_moves():
    """A band whose top edge dips to half a micrometre above its bottom ring at u = 0: the
    seam there would be that short, so the seams go to u = pi/2 and 3 pi/2, whole
    lengths of the band. Dipping to 0.1 mm above it, the seam at u = 0 stays."""
    sheets = {"body_types": ("solid", "sheet")}
    got = synthetic(notched_band(0.5e-6), **sheets)
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert m.counts["split_faces"] == 1
    assert {_midpoint(f, e) for e in _seams(f, m)} == _rounded((0.0, 5.0, 10.0), (0.0, -5.0, 10.0))
    got = synthetic(notched_band(1e-4), **sheets)
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert {_midpoint(f, e) for e in _seams(f, m)} == _rounded((5.0, 0.0, 0.05), (-5.0, 0.0, 10.0))


@pytest.mark.parametrize(
    "wrong, shape",
    [
        ("far_end", "torus_band"),  # a band's seam to the far loop the other way round the torus
        ("seam_sense", "torus_band"),  # a seam's sense turned: the other arc of its circle
        ("seam_sense", "hemisphere"),
        ("holes", "window"),  # each hole given to the other half
    ],
)
def test_the_halves_check_undoes_a_cut_made_wrong(monkeypatch, wrong, shape):
    """The export's own check that the halves of a cut tile its face, each enclosing an
    area on the face's side of its loop and holding the holes it was given: with the cut
    made wrong in one of three ways (each a one-line change to the splitter that the
    other checks pass), the cut fails it and the face is written whole."""
    from solidseas.step import split
    from solidseas.step.mapper import FACTS

    if wrong == "far_end":
        real_far = split.Splitter._far_end

        def far_end(self, chart, plan, wa, wb):
            period = chart.periods[1 - plan.d]
            return real_far(self, chart, plan, wa, wb) - plan.side * period

        monkeypatch.setattr(split.Splitter, "_far_end", far_end)
    elif wrong == "seam_sense":
        real_seam = split._seam

        def seam(*args):
            e = real_seam(*args)
            return split.E.Edge(e.start, e.end, e.curve, not e.same_sense, e.tolerance, e.deviation, e.source)

        monkeypatch.setattr(split, "_seam", seam)
    else:
        real_at = split._loop_coordinate

        def at(chart, lp, d):
            x = real_at(chart, lp, d)
            return None if x is None else x + 0.5 * chart.periods[d]

        monkeypatch.setattr(split, "_loop_coordinate", at)
    sheets = {"body_types": ("solid", "sheet")}
    xt, options, kind = {
        "torus_band": (X.torus_band(0.01, 0.003, -1.0, 1.0), sheets, "TOROIDAL_SURFACE"),
        "hemisphere": (X.hemisphere(), {}, "SPHERICAL_SURFACE"),
        "window": (windowed_band(), sheets, "CYLINDRICAL_SURFACE"),
    }[shape]
    before = FACTS[f"seam_cut_undone:{kind}"]
    got = synthetic(xt, **options)
    assert_sound(got)
    assert got["model"].counts["split_faces"] == 0
    assert FACTS[f"seam_cut_undone:{kind}"] == before + 1


def cylinder_with_rim_vertices(angle: float, r: float = 0.005, h: float = 0.02):
    """:func:`xt_bodies.cylinder` with its bottom ring made of two half circles whose
    vertices are at ``angle`` and ``angle + pi`` round the axis."""
    b = X.XtBuilder()
    c = b.circle((0, 0, 0), X.Z, X.X, r)
    p0 = (r * math.cos(angle), r * math.sin(angle), 0.0)
    p1 = (-p0[0], -p0[1], 0.0)
    v0, v1 = b.vertex(p0), b.vertex(p1)
    e1 = b.edge(c, v0, v1)
    e2 = b.edge(c, v1, v0)
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r))
    b.face(b.cylinder((0, 0, 0), X.Z, r, X.X), "+", [[(e1, "+"), (e2, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), X.Z, X.X), "-", [[(e2, "-"), (e1, "-")]])
    b.face(b.plane((0, 0, h), X.Z, X.X), "+", [[(top, "+")]])
    return b.body([e1, e2, top])


def test_a_seam_meets_a_vertex_on_its_line_or_keeps_clear_of_it():
    """A rim vertex on the line u = 0: the seam ends on it and no edge is cut there. One
    a hair off that line (under a micrometre away): the seams move to the next pair of
    values clear of it, u = pi/2 and 3 pi/2, rather than leave a sliver of an edge."""
    got = synthetic(cylinder_with_rim_vertices(0.0))
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert m.counts["split_faces"] == 1
    lines = _seam_lines(f)
    assert ((5.0, 0.0, 0.0), (5.0, 0.0, 20.0)) in lines and ((-5.0, 0.0, 0.0), (-5.0, 0.0, 20.0)) in lines
    assert len(f.of("VERTEX_POINT")) == 4  # the rim's two, and the top ring's two seam ends
    got = synthetic(cylinder_with_rim_vertices(1e-4))  # 0.5 um from the line u = 0
    assert_sound(got)
    lines = {tuple(sorted((a[:2], b[:2]))) for a, b in _seam_lines(got["file"])}
    assert lines == {((0.0, -5.0), (0.0, -5.0)), ((0.0, 5.0), (0.0, 5.0))}


def windowed_band(windows=((0.0, 0.3),), r: float = 0.005, h: float = 0.02):
    """A sheet: a cylinder's band between two rings, with windows in it, each from angle
    c - a to c + a (``windows`` the (c, a)) and from h/3 to 2h/3, bounded by two arcs
    and two lines along the axis."""
    b = X.XtBuilder()
    z1, z2 = h / 3, 2 * h / 3
    edges = []
    holes = []
    for c, a in windows:

        def corner(ang, z):
            return b.vertex((r * math.cos(ang), r * math.sin(ang), z))

        v = {(s, k): corner(c + s * a, z) for s in (-1, 1) for k, z in ((1, z1), (2, z2))}
        lo = b.edge(b.circle((0, 0, z1), X.Z, X.X, r), v[(-1, 1)], v[(1, 1)])
        hi = b.edge(b.circle((0, 0, z2), X.Z, X.X, r), v[(-1, 2)], v[(1, 2)])
        p, q = c - a, c + a
        left = b.edge(b.line((r * math.cos(p), r * math.sin(p), 0), X.Z), v[(-1, 1)], v[(-1, 2)])
        right = b.edge(b.line((r * math.cos(q), r * math.sin(q), 0), X.Z), v[(1, 1)], v[(1, 2)])
        edges += [lo, hi, left, right]
        holes.append([(left, "+"), (hi, "+"), (right, "-"), (lo, "-")])  # clockwise in (u, v)
    bottom = b.edge(b.circle((0, 0, 0), X.Z, X.X, r))
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r))
    b.face(b.cylinder((0, 0, 0), X.Z, r, X.X), "+", [[(bottom, "+")], [(top, "-")], *holes])
    return b.body([*edges, bottom, top], body_type=3)


def _angle(p) -> float:
    return math.atan2(p[1], p[0]) % (2.0 * math.pi)


def _holes_in_their_halves(f) -> int:
    """For each half of a band of a cylinder about z holding holes: the angles its outer
    bound spans (between its two seam lines, the side its arcs' middles lie on) hold
    every vertex of each of its holes. Returns the holes seen."""
    seen = 0
    for face in f.of("ADVANCED_FACE"):
        bounds = [f.get(b) for b in face.params[1]]
        holes = [b for b in bounds if b.name == "FACE_BOUND"]
        if not holes:
            continue
        (outer,) = [b for b in bounds if b.name == "FACE_OUTER_BOUND"]
        lines, arcs = [], []
        for oe in f.get(outer.params[1]).params[1]:
            ec = f.get(f.get(oe).params[3])
            (lines if _curve_kind(f, ec) == "LINE" else arcs).append(_angle(_midpoint(f, ec)))
        a, b = lines
        width = (b - a) % (2.0 * math.pi)
        if not all(0.0 < (t - a) % (2.0 * math.pi) < width for t in arcs):
            a, width = b, 2.0 * math.pi - width  # the half runs from the other seam
        assert all(0.0 < (t - a) % (2.0 * math.pi) < width for t in arcs)
        for hole in holes:
            for oe in f.get(hole.params[1]).params[1]:
                ec = f.get(f.get(oe).params[3])
                for v in ec.params[1:3]:
                    assert 0.0 < (_angle(T.point_of_vertex(f, v)) - a) % (2.0 * math.pi) < width
            seen += 1
    return seen


def test_a_hole_on_the_line_u_0_moves_the_seams_clear_of_it():
    """The window spans u = 0, so the seams go to u = pi/2 and 3 pi/2, and the window
    stays a hole of the half that holds it: the half round u = 0."""
    got = synthetic(windowed_band(), body_types=("solid", "sheet"))
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert m.counts["split_faces"] == 1
    seams = {tuple(sorted((a[:2], b[:2]))) for a, b in _seam_lines(f) if {a[2], b[2]} == {0.0, 20.0}}
    assert seams == {((0.0, -5.0), (0.0, -5.0)), ((0.0, 5.0), (0.0, 5.0))}  # the window's sides are not
    bounds = sorted(sorted(f.get(b).name for b in face.params[1]) for face in f.of("ADVANCED_FACE"))
    assert bounds == [["FACE_BOUND", "FACE_OUTER_BOUND"], ["FACE_OUTER_BOUND"]]
    assert _holes_in_their_halves(f) == 1


def _splitters(monkeypatch) -> list:
    """The seam cutters an export makes, kept to look at their bookkeeping after."""
    from solidseas.step import split

    made = []
    real = split.Splitter.__init__

    def init(self, *args):
        real(self, *args)
        made.append(self)

    monkeypatch.setattr(split.Splitter, "__init__", init)
    return made


def _recounted(splitter) -> dict:
    """Each shell's edges by how many times its loops use each one each way, counted
    afresh from the shells as written, beside the cutter's own counts."""
    from collections import Counter

    from solidseas.step import split

    fresh, kept = {}, {}
    for item in splitter.m.items:
        for shell in item.shells:
            c: Counter = Counter()
            for f in shell.faces:
                for lp, _o in f.bounds:
                    if isinstance(lp, split.E.EdgeLoop):
                        for e, o in lp.edges:
                            c[(id(e), o)] += 1
            fresh[id(shell)] = +c
            kept[id(shell)] = +splitter.uses[id(shell)]
    return {"fresh": fresh, "kept": kept}


def test_the_seam_cuts_keep_the_shells_edge_uses_and_check_only_what_they_changed(monkeypatch):
    """Each cut takes what it changed into its shells' counts of how often each edge is
    used each way and checks those edges alone, where it checked the whole shell again:
    after the nine cuts of a plate's holes the counts agree with a recount, and each cut
    checked the 8 edges it changed (two rings cut in two pieces each, and two seams) of a
    shell that ends with 66."""
    from solidseas.step import split

    made = _splitters(monkeypatch)
    sizes = []
    real = split.Splitter._check

    def check(self, *args, **kw):
        sizes.append(len(self.changed))
        return real(self, *args, **kw)

    monkeypatch.setattr(split.Splitter, "_check", check)
    got = synthetic(X.holed_plate(3))
    assert_sound(got)
    assert got["model"].counts["split_faces"] == 9
    (cutter,) = made
    counts = _recounted(cutter)
    assert counts["kept"] == counts["fresh"]
    assert sizes == [8] * 9
    (shell,) = counts["fresh"].values()
    assert len({e for e, _o in shell}) == 66


def test_a_cut_that_fails_is_taken_back_from_its_journal(monkeypatch):
    """The second of four cuts fails its checks: everything it changed (the edges it cut,
    their pieces, its vertices, the halves, the loops' edges and the counts of edge uses)
    is taken back from its journal, so the other three are written, the fourth wall whole
    on its two rings, and the counts agree with a recount."""
    from solidseas.step import split
    from solidseas.step.mapper import FACTS

    made = _splitters(monkeypatch)
    calls = []
    real = split.Splitter._check

    def check(self, *args, **kw):
        calls.append(len(calls))
        if len(calls) == 2:
            raise split.Refused("check_failed", "a cut that does not check")
        return real(self, *args, **kw)

    monkeypatch.setattr(split.Splitter, "_check", check)
    before = FACTS["seam_cut_undone:CYLINDRICAL_SURFACE"]
    got = synthetic(X.holed_plate(2))
    assert_sound(got)
    assert got["model"].counts["split_faces"] == 3
    assert FACTS["seam_cut_undone:CYLINDRICAL_SURFACE"] == before + 1
    f = got["file"]
    assert len(f.of("ADVANCED_FACE")) == 6 + 4 + 3  # the plate, four walls, three cut in two
    assert len(f.of("EDGE_CURVE")) == 12 + 2 + 3 * 6  # sides, one wall's rings, three cut walls'
    (cutter,) = made
    counts = _recounted(cutter)
    assert counts["kept"] == counts["fresh"]


def test_the_seam_cuts_of_many_holes_cost_in_proportion_to_them(monkeypatch):
    """Each hole's cut splits a ring of the plate's top and bottom faces, which hold every
    hole. A cut checks the loops it rewrote and its new vertices on those faces, not every
    loop of the shell and every vertex of those faces again, so four times the holes cost
    about four times the loops looked at and the vertices checked on a surface (3.8 and
    3.6 times; 13 and 10 times when each cut checked its shell and faces whole)."""
    from collections import Counter

    from solidseas.step import checks, split

    calls: Counter = Counter()
    distance, ends = checks._surface_distance, split.E.EdgeLoop.ends

    def counted_distance(*args):
        calls["vertices"] += 1
        return distance(*args)

    def counted_ends(self):
        calls["loops"] += 1
        return ends(self)

    monkeypatch.setattr(checks, "_surface_distance", counted_distance)
    monkeypatch.setattr(split.E.EdgeLoop, "ends", counted_ends)
    cost = {}
    for n in (3, 6):
        calls.clear()
        m = step_transmit(_numbered(X.holed_plate(n)))
        assert m.counts["split_faces"] == n * n
        cost[n] = dict(calls)
    for what in ("vertices", "loops"):
        assert cost[6][what] < 5 * cost[3][what], (what, cost)


def test_holes_on_every_evenly_spaced_line_send_the_seams_into_the_gaps():
    """Sixteen windows, one on each of the sixteen evenly spaced lines the seams are tried
    on first: the seams go through the middles of the gaps between them instead, and each
    window stays a hole of one half."""
    windows = tuple((k * math.pi / 8, 0.12) for k in range(16))
    got = synthetic(windowed_band(windows), body_types=("solid", "sheet"))
    assert_sound(got)
    f, m = got["file"], got["model"]
    assert m.counts["split_faces"] == 1
    seams = [(a, b) for a, b in _seam_lines(f) if {a[2], b[2]} == {0.0, 20.0}]
    assert len(seams) == 2
    for a, _b in seams:  # in the middle of a gap: an odd multiple of pi / 16
        k = math.atan2(a[1], a[0]) / (math.pi / 16)
        assert abs(k - round(k)) < 1e-6 and round(k) % 2 == 1
    faces = f.of("ADVANCED_FACE")
    holes = [sum(1 for b in face.params[1] if f.get(b).name == "FACE_BOUND") for face in faces]
    assert sum(holes) == 16 and len(holes) == 2
    assert _holes_in_their_halves(f) == 16


def test_a_cut_that_fails_the_checks_leaves_its_face_whole(monkeypatch):
    from solidseas.step import split
    from solidseas.step.mapper import FACTS

    def fail(self, *_a):
        raise split.Refused("check_failed", "a cut that does not check")

    monkeypatch.setattr(split.Splitter, "_check", fail)
    before = FACTS["seam_cut_undone:CYLINDRICAL_SURFACE"]
    got = synthetic(X.cylinder())
    assert_sound(got)
    assert len(got["file"].of("ADVANCED_FACE")) == 3 and got["model"].counts["split_faces"] == 0
    assert len(got["file"].of("EDGE_CURVE")) == 2  # the rings as they were, whole
    assert FACTS["seam_cut_undone:CYLINDRICAL_SURFACE"] == before + 1


def test_a_cone_with_a_negative_half_angle_is_written_about_the_reversed_axis():
    got = synthetic(X.cone())
    f = got["file"]
    (cone,) = f.of("CONICAL_SURFACE")
    assert 0.0 < cone.params[3] < math.pi / 2
    assert T.Frame(f, cone.params[1]).z == pytest.approx((0.0, 0.0, -1.0))


@pytest.mark.parametrize(
    "R, r, kind, outer",
    [
        (-0.002, 0.005, "DEGENERATE_TOROIDAL_SURFACE", "F"),
        (0.002, 0.005, "DEGENERATE_TOROIDAL_SURFACE", "T"),
        (0.01, 0.003, "TOROIDAL_SURFACE", None),
    ],
)
def test_torus_bands_lemon_apple_and_ring_face_the_right_way(R, r, kind, outer):
    """A sheet of each kind of torus: the lemon (R < 0) is ISO's torus with x reversed
    read at (u, pi - v), whose natural normal is Parasolid's turned round; upstream
    kept it, which the orientation oracle refuses (below)."""
    got = synthetic(X.torus_band(R, r, -1.0, 1.0), body_types=("solid", "sheet"))
    assert_sound(got)
    f = got["file"]
    (surface,) = f.of(kind)
    if outer is not None:
        assert surface.params[4] == outer
    assert [e.name for e in f.of("SHELL_BASED_SURFACE_MODEL")] == ["SHELL_BASED_SURFACE_MODEL"]
    assert f.of("MANIFOLD_SURFACE_SHAPE_REPRESENTATION") and not f.of("ADVANCED_BREP_SHAPE_REPRESENTATION")
    assert got["model"].counts["sheets"] == 1


def test_the_oracle_catches_upstreams_lemon(monkeypatch):
    """With the lemon's natural normal taken as Parasolid's, as upstream takes it, the
    face points the wrong way and the independent oracle says so."""
    from solidseas.step import mapper

    real = mapper.BodyMapper.torus

    def upstream(self, s):
        got = real(self, s)
        got.match = True
        return got

    monkeypatch.setattr(mapper.BodyMapper, "torus", upstream)
    got = synthetic(X.torus_band(-0.002, 0.005, -1.0, 1.0), body_types=("solid", "sheet"))
    assert got["orientation"]["disagree"] and got["orientation"]["agree"] == 0


def test_the_writer_samples_its_edges_as_they_are(monkeypatch):
    """The writer checks its curves against the tessellator's edge sampler, with a chord of
    1 m. The sampler's rule against halving a short segment for its turn alone, meant for a
    tessellation's chord, then kept it from halving any segment under 20 mm, and a part
    whose check had refused it was written. The writer's sampler says ``corners=False`` and
    samples as it always did."""
    from solidseas.step import mapper

    seen = []
    real = mapper.EdgeSampler.__init__

    def spy(self, topo, geom, pts, opts, clock):
        seen.append(opts)
        real(self, topo, geom, pts, opts, clock)

    monkeypatch.setattr(mapper.EdgeSampler, "__init__", spy)
    step_transmit(_numbered(X.cylinder(0.005, 0.02)))
    assert seen and all(getattr(o, "corners", True) is False for o in seen)


def test_sheets_only_when_asked():
    xt = _numbered(X.torus_band(0.01, 0.003, -1.0, 1.0))
    with pytest.raises(NothingToExportError) as exc:
        step_transmit(xt)
    assert "ask for sheets" in str(exc.value)
    assert exc.value.detail == {"rule": "sheets_not_asked"}


def _shell_volumes(f) -> list[list[float]]:
    """Each solid's shells' signed volumes (mm^3), the outer shell first, as ISO 10303-42
    reads them: a void is an ORIENTED_CLOSED_SHELL whose ``.F.`` turns its faces round.
    By the divergence theorem over plane faces bounded by lines (``T.planar_volume``, shell
    by shell)."""
    out = []
    for solid in f.of("MANIFOLD_SOLID_BREP") + f.of("BREP_WITH_VOIDS"):
        shells = [(solid.params[1], 1.0)]
        for r in solid.params[2] if solid.name == "BREP_WITH_VOIDS" else []:
            void = f.get(r)
            shells.append((void.params[2], 1.0 if void.params[3] == "T" else -1.0))
        volumes = []
        for ref, sign in shells:
            total = 0.0
            for face in T.shell_faces(f, f.get(ref)):
                frame = T.Frame(f, f.get(face.params[2]).params[1])
                n = frame.z if face.params[3] == "T" else tuple(-c for c in frame.z)
                for b in face.params[1]:
                    bound = f.get(b)
                    pts = []
                    for oe in (f.get(x) for x in f.get(bound.params[1]).params[1]):
                        edge = f.get(oe.params[3])
                        start = edge.params[1] if oe.params[4] == "T" else edge.params[2]
                        pts.append(T.point_of_vertex(f, start))
                    if bound.params[2] != "T":
                        pts.reverse()
                    area = [0.0, 0.0, 0.0]
                    for p, q in zip(pts, pts[1:] + pts[:1], strict=True):
                        area = [area[0] + p[1] * q[2] - p[2] * q[1], area[1] + p[2] * q[0] - p[0] * q[2],
                                area[2] + p[0] * q[1] - p[1] * q[0]]  # fmt: skip
                    along = 0.5 * sum(a * c for a, c in zip(area, n, strict=True))
                    total += along * sum(c * x for c, x in zip(n, pts[0], strict=True)) / 3.0
            volumes.append(sign * total)
        out.append(volumes)
    return out


def test_a_cavity_is_written_facing_into_itself():
    """ISO 10303-42 takes a BREP_WITH_VOIDS' void as its ORIENTED_CLOSED_SHELL says: its
    faces, turned round when the orientation is ``.F.``, must look into the void, away
    from the material, so that the void's volume is negative. SolidSeas writes a cavity
    as Parasolid holds it, its faces already looking into it, with ``.T.``. OCCT orients
    voids by their geometry whatever the file says, so only a check of the file itself
    sees a void written inside out, which a strict reader would add to the solid."""
    got = synthetic(X.void_box())
    assert_sound(got)
    f = got["file"]
    (solid,) = f.of("BREP_WITH_VOIDS")
    (void,) = (f.get(r) for r in solid.params[2])
    assert void.name == "ORIENTED_CLOSED_SHELL" and void.params[3] == "T"
    assert _shell_volumes(f) == [pytest.approx([27000.0, -1000.0], rel=1e-12)]
    assert T.planar_volume(f) == pytest.approx(26000.0, rel=1e-12)
    with open_model(got["data"]) as doc:
        scene = doc.scene(chord_m=1e-6)
    (obj,) = scene.objects
    assert obj.measures()["volume_m3"] == pytest.approx(26000e-9, rel=1e-12)
    assert "void_reoriented" not in {w.code for w in scene.warnings}  # read as written


def test_the_cavity_check_sees_a_void_written_inside_out(monkeypatch):
    """The same cavity with its shell marked ``.F.`` (its faces still looking into it, as
    the corpus files the oracle found wrong store theirs): the check finds the void adding
    its volume, as a strict reader reads it. SolidSeas' own reader turns each closed shell
    of a solid by its signed volume (``void_reoriented``), so it reads the true 26,000
    cubic millimetres all the same and says what it turned."""
    from solidseas.step import entities as E

    def inside_out(self, w):
        outer = self.outer.write(w)
        voids = [w.add(f"ORIENTED_CLOSED_SHELL({E.NONE},*,#{v.write(w)},.F.)") for v in self.voids]
        return w.add(f"BREP_WITH_VOIDS({p21.text(self.name)},#{outer},{p21.refs(voids)})")

    monkeypatch.setattr(E.Solid, "_write", inside_out)
    got = synthetic(X.void_box())
    assert _shell_volumes(got["file"]) == [pytest.approx([27000.0, 1000.0], rel=1e-12)]
    with open_model(got["data"]) as doc:
        scene = doc.scene(chord_m=1e-6)
    (obj,) = scene.objects
    assert obj.measures()["volume_m3"] == pytest.approx(26000e-9, rel=1e-12)
    assert "void_reoriented" in {w.code for w in scene.warnings}


def test_a_body_with_no_seam_for_its_loopless_face_is_refused():
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(X.nurbs_sphere()))
    (b,) = exc.value.bodies
    assert b.reason == "unsupported_surface" and not b.written
    assert exc.value.code == "not_representable" and exc.value.detail == {
        "rule": "unsupported_surface",
        "value": 1,
    }


def _with_surface_of(xt, ntype: int):
    """``xt`` with its first PLANE node turned into a node of type ``ntype``."""
    for n in xt.nodes:
        if n.type == 50:
            n.type = ntype
            xt.layouts.setdefault(ntype, xt.layouts[50])
            return xt
    raise AssertionError("no plane")


def test_allow_partial_leaves_refused_bodies_out_whole():
    good = _numbered(X.cylinder())
    bad = _with_surface_of(_numbered(X.split_box()), 120)  # a foreign (PE) surface
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit([good, bad])
    assert [b.reason for b in exc.value.bodies] == ["foreign_geometry"]
    m = step_transmit([good, bad], allow_partial=True)
    assert m.partial and m.counts["bodies"] == 1 and m.counts["bodies_left_out"] == 1
    assert [w.code for w in m.warnings] == ["step_bodies_left_out"]
    f = T.read(step_bytes(m, time_stamp=STAMP))
    desc = f.header_record("FILE_DESCRIPTION")[0]
    assert desc == ["STEP AP214", "incomplete: 1 of 2 bodies left out (foreign_geometry 1)"]
    assert len(f.of("MANIFOLD_SOLID_BREP")) == 1 and len(f.of("ADVANCED_FACE")) == 4  # the side cut in two
    with pytest.raises(NothingToExportError):
        step_transmit([bad], allow_partial=True)


@pytest.mark.parametrize(
    "ntype, reason",
    [
        (120, "foreign_geometry"),
        (201, "mesh_geometry"),
        (59, "unsupported_surface"),
        (99, "unsupported_surface"),
    ],
)
def test_surfaces_that_cannot_be_written_are_refused(ntype, reason):
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_with_surface_of(_numbered(X.cylinder()), ntype))
    assert [b.reason for b in exc.value.bodies] == [reason]


def test_damaged_bodies_are_refused_with_a_reason():
    def first(xt, ntype):
        return next(n for n in xt.nodes if n.type == ntype)

    def field(xt, node, name):
        return xt.field_names(node.type).index(name)

    cases = []
    xt = _numbered(X.cylinder())
    circle = first(xt, 31)
    circle.vals[field(xt, circle, "radius")] = math.nan
    cases.append((xt, "bad_geometry"))
    xt = _numbered(X.cylinder())
    fin = first(xt, 17)
    fin.vals[field(xt, fin, "forward")] = 0  # a fin ring that never closes
    cases.append((xt, "bad_reference"))
    xt = _numbered(X.split_box())
    shell = first(xt, 13)
    face = first(xt, 14)
    shell.vals[field(xt, shell, "front_face")] = face.index
    cases.append((xt, "front_face_in_solid"))
    xt = _numbered(X.split_box())
    body = first(xt, 12)
    body.vals[field(xt, body, "body_type")] = 6
    cases.append((xt, "non_manifold"))
    for xt, reason in cases:
        with pytest.raises(NotRepresentableError) as exc:
            step_transmit(xt)
        assert [b.reason for b in exc.value.bodies] == [reason]


def test_a_two_dimensional_b_curve_on_an_edge_is_refused():
    xt = _numbered(X.cylinder())
    circle = next(n for n in xt.nodes if n.type == 31)
    # point an edge at a 2D B-curve: borrow the NURBS of the side surface's own shape
    b = X.XtBuilder()
    verts = b.node(45, vertices=[0.0, 0.0, 1.0, 0.0])
    knots = b.node(128, knots=[0.0, 1.0])
    mult = b.node(127, mult=[2, 2])
    nc = b.node(
        136, degree=1, n_vertices=2, vertex_dim=2, bspline_vertices=verts, knot_mult=mult, knots=knots
    )
    bc = b.node(134, nurbs=nc)
    extra = b.transmit()
    base = max(n.index for n in xt.nodes)
    for n in extra.nodes:
        n.index += base
        for i, (_name, kind, _n) in enumerate(extra.layouts[n.type]):
            if kind == "p" and isinstance(n.vals[i], int) and n.vals[i]:
                n.vals[i] += base
        xt.nodes.append(n)
        xt.layouts.setdefault(n.type, extra.layouts[n.type])
    xt._by_index = None
    edge = next(
        n for n in xt.nodes if n.type == 16 and n.vals[xt.field_names(16).index("curve")] == circle.index
    )
    edge.vals[xt.field_names(16).index("curve")] = bc + base
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(xt)
    assert [b.reason for b in exc.value.bodies] == ["unsupported_curve"]


def trimmed_ring_cylinder(p1: float, p2: float, periodic: bool = True, r: float = 0.005, h: float = 0.02):
    """The synthetic cylinder with its bottom ring edge on a TRIMMED_CURVE from ``p1`` to
    ``p2`` of a closed rational B-curve circle of four quarter spans (parameters 0 to 4),
    flagged periodic or not."""
    w = math.sqrt(0.5)
    ring = [
        (1, 0, 1),
        (1, 1, w),
        (0, 1, 1),
        (-1, 1, w),
        (-1, 0, 1),
        (-1, -1, w),
        (0, -1, 1),
        (1, -1, w),
        (1, 0, 1),
    ]
    b = X.XtBuilder()
    flat = [v for x, y, wt in ring for v in (x * r * wt, y * r * wt, 0.0, wt)]
    verts = b.node(45, vertices=flat)
    knots = b.node(128, knots=[0.0, 1.0, 2.0, 3.0, 4.0])
    mult = b.node(127, mult=[3, 2, 2, 2, 3])
    nc = b.node(
        136,
        degree=2,
        n_vertices=9,
        vertex_dim=4,
        n_knots=5,
        periodic=1 if periodic else 0,
        closed=1,
        rational=1,
        bspline_vertices=verts,
        knot_mult=mult,
        knots=knots,
    )
    bc = b.node(134, nurbs=nc)
    tc = b.node(133, basis_curve=bc, point_1=(r, 0.0, 0.0), point_2=(r, 0.0, 0.0), parm_1=p1, parm_2=p2)
    bottom = b.edge(tc)
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r))
    b.face(b.cylinder((0, 0, 0), X.Z, r, X.X), "+", [[(bottom, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), X.Z, X.X), "-", [[(bottom, "-")]])
    b.face(b.plane((0, 0, h), X.Z, X.X), "+", [[(top, "+")]])
    return b.body([bottom, top])


@pytest.mark.parametrize("p1, p2", [(0.0, 4.0), (1.0, 5.0), (-3.0, 1.0)])
def test_a_ring_edge_on_a_trimmed_curve_round_its_basis_is_written(p1, p2):
    got = synthetic(trimmed_ring_cylinder(p1, p2))
    assert_sound(got)
    assert got["model"].exact and T.uncertainty_mm(got["file"]) == 1e-5


@pytest.mark.parametrize("p1, p2, periodic", [(0.0, 0.5, True), (0.0, 2.0, True), (0.0, 2.0, False)])
def test_a_ring_edge_on_a_trimmed_curve_that_does_not_close_is_refused(p1, p2, periodic):
    """A ring is one vertex at both ends of its curve: on an eighth or half of the circle
    the loop would be an open arc."""
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(trimmed_ring_cylinder(p1, p2, periodic)))
    (b,) = exc.value.bodies
    assert b.reason == "bad_geometry" and "does not close" in b.message


def test_the_checks_refuse_a_ring_on_an_open_curve_the_mapping_let_through(monkeypatch):
    from solidseas.step import mapper

    monkeypatch.setattr(mapper, "_ring_closes", lambda point, lo, hi: None)
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(trimmed_ring_cylinder(0.0, 2.0)))
    (b,) = exc.value.bodies
    assert b.reason == "check_failed" and "does not close at its vertex" in b.message


@pytest.mark.parametrize("p1", [-1e9, -1e17, 1e300])
def test_a_trim_far_from_its_periodic_curve_is_refused_at_once(p1):
    """Moving the range a period at a time took 19 s for -1e9 and never ended for -1e17
    (a + period == a): the range is moved in one step, and a range many periods away is
    refused."""
    import time

    t0 = time.perf_counter()
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(trimmed_ring_cylinder(p1, p1 + 4.0)), max_seconds=5)
    assert time.perf_counter() - t0 < 2.0
    assert [b.reason for b in exc.value.bodies] == ["bad_geometry"]


def test_many_bodies_on_one_long_face_chain_stop_at_max_faces_at_once():
    """Counting each BODY's faces on a shared chain cost bodies times faces before the
    limit was compared: the count now stops as soon as it passes the limit."""
    import time

    from solidseas.formats.solidworks.parasolid import Node

    xt = X.split_box()
    lay = xt.field_names
    by = {n.index: n for n in xt.nodes}
    body = by[1]
    region = by[body.vals[lay(12).index("region")]]
    shell = by[region.vals[lay(19).index("shell")]]
    face0 = by[shell.vals[lay(13).index("face")]]
    nxt = lay(14).index("next")
    top = max(by) + 1
    prev = face0
    for _ in range(10_000):
        vals = list(face0.vals)
        vals[nxt] = 0
        node = Node(14, top, vals, face0.count)
        xt.nodes.append(node)
        prev.vals[nxt] = top
        prev, top = node, top + 1
    for _ in range(10_000):
        xt.nodes.append(Node(12, top, list(body.vals), body.count))
        top += 1
    xt._by_index = None
    t0 = time.perf_counter()
    with pytest.raises(SldLimitError) as exc:
        step_transmit(xt, max_seconds=60)
    assert exc.value.detail == {"limit": "max_faces"}
    assert time.perf_counter() - t0 < 10.0


def test_bodies_left_out_and_refused_by_kind():
    """A sheet not asked for and a wire body are left out, each said so in its own words;
    a general body and one of an unknown type refuse the export."""
    solid = _numbered(X.split_box())

    def typed(code):
        xt = _numbered(X.split_box())
        body = next(n for n in xt.nodes if n.type == 12)
        body.vals[xt.field_names(12).index("body_type")] = code
        return xt

    sheet = _numbered(X.torus_band(0.01, 0.003, -1.0, 1.0))
    m = step_transmit([solid, sheet])
    assert not m.partial and m.incomplete is None
    assert [(b.kind, b.written, b.reason) for b in m.bodies] == [
        ("solid", True, None),
        ("sheet", False, "not_asked"),
    ]
    (w,) = [w for w in m.warnings if w.code == "bodies_left_out"]
    assert "1 sheet (surface) body is not written" in w and "ask for sheets" in w and "wire" not in w
    m = step_transmit([solid, typed(2)])
    assert [(b.kind, b.reason) for b in m.bodies] == [("solid", None), ("wire", "unsupported_body")]
    (w,) = [w for w in m.warnings if w.code == "bodies_left_out"]
    assert "1 wire body is not written" in w and "sheet (surface)" not in w
    for code, kind, reason in ((6, "general", "non_manifold"), (99, "unknown", "bad_reference")):
        with pytest.raises(NotRepresentableError) as exc:
            step_transmit([solid, typed(code)])
        assert [(b.kind, b.reason) for b in exc.value.bodies] == [(kind, reason)]
        m = step_transmit([solid, typed(code)], allow_partial=True)
        assert m.partial and f"({reason} 1)" in m.incomplete
    from solidseas.step import REASONS

    assert "unsupported_body" in REASONS


def test_the_checks_search_harder_before_failing_a_point_near_a_side():
    """A point of an edge along a B-spline surface's side, where Newton's method from the
    seeds can stall: before a check fails on a distance, the side itself is searched. On
    a corpus part this turned a reported 0.6 mm into the true few micrometres."""
    from solidseas.step import checks
    from solidseas.tessellate import nurbs
    from solidseas.tessellate.surfaces import BSurface
    from solidseas.tessellate.topology import Clock

    # a curved patch: z = x^2 / 10 over the unit square, degree 2 in u, 1 in v
    rows = [
        [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0.5, 0.0, 0.0), (0.5, 1.0, 0.0)],
        [(1.0, 0.0, 0.1), (1.0, 1.0, 0.1)],
    ]
    ev = BSurface(
        nurbs.BSplineSurface(2, 1, rows, [0, 0, 0, 1, 1, 1], [0, 0, 1, 1], False, False, False), 1e-9
    )
    p = (1.0 + 1e-6, 0.37, 0.1)  # a micrometre beyond the side u = 1
    d = checks._closer(ev, p, 1.0, Clock(10.0))
    assert d == pytest.approx(1e-6, rel=1e-3)  # the side ends at x = 1: its point (1, 0.37, 0.1)


@pytest.mark.parametrize("tol, warned", [(9e-7, False), (1e-6, True), (3e-6, True)])
def test_tolerant_edges_of_a_micrometre_and_more_are_warned_about(tol, warned):
    """A tolerant edge may lie up to its tolerance off its faces, which the file's
    uncertainty (1e-5 mm here) does not cover: from 1e-3 mm the export says so."""
    xt = _numbered(X.cylinder())
    edge = next(n for n in xt.nodes if n.type == 16)
    edge.vals[xt.field_names(16).index("tolerance")] = tol
    m = step_transmit(xt)
    assert m.max_tolerance_m == tol and m.uncertainty_m == 1e-8
    got = [w for w in m.warnings if w.code == "step_tolerant_geometry"]
    assert bool(got) == warned
    if warned:
        assert f"gaps up to {tol * 1000:.3g} mm" in got[0] and "uncertainty of 1e-05 mm" in got[0]


# --------------------------------------------------------------------------- the command line and JSON
def _run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr()
    return code, json.loads(out.out)


def test_cli_export_step(capsys, tmp_path):
    from jsonschema_subset import validate

    part = str(fixture_path("o11_curved.SLDPRT"))
    code, env = _run(capsys, "export", part, "--format", "step", "-o", str(tmp_path))
    assert code == 0 and env["ok"] and env["kind"] == "export_result"
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []
    d = env["data"]
    assert (
        d["format"] == "step" and d["mime"] == "model/step" and d["objects"] == [] and d["chord_mm"] is None
    )
    assert d["output"].endswith("o11_curved.step") and os.path.getsize(d["output"]) == d["bytes"]
    assert d["counts"]["faces"] == 14 and d["counts"]["solids"] == 1 and d["closed"] is True
    assert d["counts"]["split_faces"] == 2 and d["step"]["bodies"][0]["split_faces"] == 2
    st = d["step"]
    assert st["schema"] == "AP214" and st["exact"] is True and st["partial"] is False
    assert st["uncertainty_mm"] == pytest.approx(1e-5) and st["max_deviation_mm"] is None
    assert [b["name"] for b in st["bodies"]] == ["Fillet2"] and st["bodies"][0]["written"] is True
    assert T.syntax_problems(T.read(open(d["output"], "rb").read())) == []
    code, env = _run(capsys, "export", part, "--format", "step", "-o", str(tmp_path / "x.stp"))
    assert code == 0 and env["data"]["output"].endswith("x.stp")
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(tmp_path / "x.3mf"))
    assert code == 0 and env["data"]["step"] is None
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []


def test_cli_export_step_refusals(capsys, tmp_path, monkeypatch):
    part = str(fixture_path("o02_boxA.SLDPRT"))
    for extra, parameter in ((["--merge"], "--merge"), (["--chord", "0.01"], "--chord")):
        code, env = _run(capsys, "export", part, "--format", "step", *extra, "-o", str(tmp_path))
        assert code == 2 and env["error"]["code"] == "invalid_argument"
        assert env["error"]["detail"]["parameter"] == parameter
    for flag in ("--sheets", "--allow-partial", "--exact-only", "--include-hidden"):
        code, env = _run(capsys, "export", part, "--format", "stl", flag, "-o", str(tmp_path))
        assert code == 2 and env["error"]["detail"]["parameter"] == flag
    code, env = _run(capsys, "export", part, "--format", "step", "-o", str(tmp_path / "x.stl"))
    assert code == 3 and env["error"]["detail"]["rule"] == "output_extension"
    o06 = str(fixture_path("o06_boxA_props_mat_cfg.SLDPRT"))
    code, env = _run(
        capsys, "export", o06, "--format", "step", "--configuration", "OracleAlt", "-o", str(tmp_path)
    )
    assert code == 1 and env["error"]["code"] == "nothing_to_export"
    asm = str(fixture_path("o16_asm_features.SLDASM"))  # an instance whose configuration has no bodies
    code, env = _run(capsys, "export", asm, "--format", "step", "-o", str(tmp_path))
    assert code == 1 and env["error"]["code"] == "not_representable"
    assert env["error"]["detail"] == {"rule": "instances_left_out", "value": 1}
    assert os.listdir(tmp_path) == []
    code, env = _run(capsys, "export", asm, "--format", "step", "--allow-partial", "-o", str(tmp_path))
    assert code == 4 and env["data"]["output"].endswith("o16_asm_features.step")  # partial, and says so
    assert [s["id"] for s in env["data"]["skipped"]] == ["o06_boxA_props_mat_cfg-1"]
    os.remove(env["data"]["output"])

    import solidseas.step as S

    def refuse(*_a, **_k):
        raise NotRepresentableError("refused", detail={"rule": "foreign_geometry", "value": 1})

    monkeypatch.setattr(S, "step_model", refuse)
    code, env = _run(capsys, "export", part, "--format", "step", "-o", str(tmp_path))
    assert code == 1 and env["error"]["code"] == "not_representable"
    assert env["error"]["detail"] == {"rule": "foreign_geometry", "value": 1}
    assert env["error"]["retryable"] is False
    assert os.listdir(tmp_path) == []


def test_cli_partial_export_exits_4(capsys, tmp_path, monkeypatch):
    import solidseas.step as S

    good = _numbered(X.cylinder())
    bad = _with_surface_of(_numbered(X.split_box()), 120)
    partial = step_transmit([good, bad], allow_partial=True, name="o02_boxA")
    seen = {}

    def fake(doc, configuration=None, **options):
        seen.update(options)
        return partial

    monkeypatch.setattr(S, "step_model", fake)
    part = str(fixture_path("o02_boxA.SLDPRT"))
    code, env = _run(
        capsys, "export", part, "--format", "step", "--allow-partial", "--sheets", "-o", str(tmp_path)
    )
    assert code == 4 and seen["allow_partial"] is True and seen["body_types"] == ("solid", "sheet")
    st = env["data"]["step"]
    assert st["partial"] is True and [b["written"] for b in st["bodies"]] == [True, False]
    assert st["bodies"][1]["reason"] == "foreign_geometry"
    assert [w["code"] for w in env["data"]["warnings"]] == ["step_bodies_left_out"]


def test_export_document_dispatches_step(tmp_path):
    from solidseas.export import export_document

    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        res = export_document(doc, tmp_path / "a.step", "step")
        assert res.format == "step" and (tmp_path / "a.step").stat().st_size == res.bytes
        with pytest.raises(InvalidArgumentError):
            export_document(doc, tmp_path / "b.step", "step", merge=True)
        with pytest.raises(InvalidArgumentError) as exc:
            export_document(doc, tmp_path / "c.igs", "iges")
        assert "3mf, step, stl" in str(exc.value) and not (tmp_path / "c.igs").exists()


# --------------------------------------------------------------------------- the licence
DERIVED = ("part21.py", "entities.py", "mapper.py", "bspline.py", "approx.py", "blend.py", "product.py")
DERIVED_TESSELLATE = ("fit.py", "blend.py")  # shared by the export and the tessellator


def test_files_adapted_from_sldprt2step_say_so_and_notice_lists_them():
    """Apache-2.0 section 4(b): each adapted file names the upstream file it derives
    from and says it was modified; NOTICE's sldprt2step entry lists them."""
    import solidseas.step as S
    import solidseas.tessellate as TS

    here = os.path.dirname(S.__file__)
    shared = os.path.dirname(TS.__file__)
    paths = [os.path.join(here, n) for n in DERIVED] + [os.path.join(shared, n) for n in DERIVED_TESSELLATE]
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4000)
        name = os.path.basename(path)
        assert "Derived work." in head and "BlinkingSun/sldprt2step" in head, name
        assert "sldprt2step_lib/" in head and "Licensed under the Apache License, Version 2.0" in head, name
        assert "Modified for SolidSeas" in head, name
    root = os.path.dirname(os.path.dirname(here))
    with open(os.path.join(os.path.dirname(root), "NOTICE"), encoding="utf-8") as fh:
        notice = " ".join(fh.read().split())
    entry = notice[notice.index("sldprt2step Source:") :]
    listed = (
        "src/solidseas/step/part21.py, entities.py, mapper.py, bspline.py, approx.py, blend.py and product.py"
    )
    assert listed in entry
    assert "src/solidseas/tessellate/fit.py and blend.py" in entry
