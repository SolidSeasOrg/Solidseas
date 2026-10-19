"""Hostile STEP files: each ends in a documented exception, or a face or an item left out
with a reason, within a short time (``docs/formats/step.md``, ``docs/API.md`` 3.20.7)."""

import io
import time
import zipfile

import pytest

import p21_writers as W
import solidseas.tessellate
from solidseas.errors import FormatNotSupportedError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model
from solidseas.formats._source import ReadCancelledError
from solidseas.formats.step import part21
from support import within

HEADER = (
    b"ISO-10303-21;\nHEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','',(''),(''),'','','');"
    b"FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;\nDATA;\n"
)
TAIL = b"ENDSEC;\nEND-ISO-10303-21;\n"
SECONDS = 10.0


def _file(body: bytes) -> bytes:
    return HEADER + body + TAIL


def _open(data: bytes, **limits):
    return open_model(data, name="hostile.step", limits=Limits(**limits) if limits else None)


def _full(data: bytes, **limits):
    """Open, then read the whole model: the tree and the scene."""
    with _open(data, **limits) as doc:
        doc.tree()
        return doc.scene()


@pytest.fixture(autouse=True)
def _quick():
    t0 = time.perf_counter()
    yield
    assert time.perf_counter() - t0 < within(SECONDS)


# --------------------------------------------------------------------------- the exchange structure
@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"ISO-10303-22;\n",
        b"\x00\x01binary junk",
        b"ISO-10303-21;\nHEADER;FILE_NAME('unterminated",
        b"ISO-10303-21;\nHEADER;FILE_SCHEMA(('X'));\n",  # no ENDSEC
        b"ISO-10303-21;\nDATA;\n#1=X();\nENDSEC;\nEND-ISO-10303-21;\n",  # no HEADER
        HEADER + b"#1=X('unterminated);\n" + TAIL,
        HEADER + b"#1=X(); /* unterminated comment\n" + TAIL,
        HEADER + b"#1=X(1,2;\n" + TAIL,  # a list not closed before the semicolon
        HEADER + b"#1=X((1,2);\n" + TAIL,
        HEADER + b"#1=X(1,2));\n" + TAIL,
        HEADER + b"#1=X(1)Y;\n" + TAIL,  # text after the parameters
        HEADER + b"#1=X(%);\n" + TAIL,  # not a token
        HEADER + b"#1=X();\n#1=Y();\n" + TAIL,  # an id twice
        HEADER + b"#2=X();\n#1=Y();\n#2=Z();\n" + TAIL,  # an id twice, out of order
        HEADER + b"#1=X();\n",  # no ENDSEC
        HEADER + b"#1=X();\nENDSEC;\n",  # no END-ISO-10303-21
        HEADER + b"#1=X();\nENDSEC;\nGARBAGE;\nEND-ISO-10303-21;\n",
        HEADER + b"X();\n" + TAIL,  # not an entity instance
        HEADER + b"#1=();\n" + TAIL,  # an empty complex instance
        HEADER + b"#1=(A()5);\n" + TAIL,
        HEADER + b"#1=X(#" + b"9" * 30 + b");\n" + TAIL,  # an id too long
    ],
)
def test_malformed_exchange_structures_are_refused(data):
    """Refused when the file is opened, indexed or its instances parsed (a record is
    parsed when something reads it)."""
    with pytest.raises(SldFormatError):
        p = part21.open(data, limits=Limits())
        for rid in p.ids:
            p.record(rid)


@pytest.mark.parametrize(
    ("body", "limit", "limits"),
    [
        (b"#1=X('" + b"a" * 5000 + b"');\n", "p21_string_bytes", {"p21_string_bytes": 4096}),
        (b"#1=X(" + b"(" * 40 + b")" * 40 + b");\n", "p21_list_depth", {}),
        (b"#1=X((" + b"1," * 2000 + b"1));\n", "p21_list_items", {"p21_list_items": 1000}),
        (b"#1=X(" + b"1," * 3000 + b"1);\n", "p21_record_bytes", {"p21_record_bytes": 4096}),
        (b"".join(b"#%d=X();\n" % i for i in range(1, 300)), "p21_records", {"p21_records": 100}),
        (b"#1=(" + b"A()" * 100 + b");\n", "p21_complex_parts", {}),
    ],
)
def test_every_part21_bound(body, limit, limits):
    with pytest.raises(SldLimitError) as exc:
        p = part21.open(_file(body), limits=Limits(**limits))
        for rid in p.ids:
            p.record(rid)
    assert exc.value.detail["limit"] == limit


def test_a_header_past_its_bound_is_refused():
    data = b"ISO-10303-21;\nHEADER;FILE_DESCRIPTION(('" + b"x" * 5000 + b"'),'2;1');" + TAIL
    with pytest.raises(SldLimitError) as exc:
        _open(data, p21_header_bytes=1024)
    assert exc.value.detail["limit"] == "p21_header_bytes"


def test_a_huge_unterminated_list_fails_fast():
    data = HEADER + b"#1=X(" + b"1," * 2_000_000
    with pytest.raises(SldFormatError):
        _full(data)


def test_a_reference_to_a_missing_instance_leaves_its_face_out():
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    data = f.bytes()
    plane = data.index(b"PLANE('',#")
    end = data.index(b")", plane)
    data = data[: plane + 10] + b"99999" + data[end:]
    s = _full(data)
    assert s.counts["faces_done"] == 5 and [x.reason for x in s.skipped] == ["bad_reference"]


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"CARTESIAN_POINT('',(0.0,0.0,0.0))", b"CARTESIAN_POINT('',(1E999,0.0,0.0))", "non_finite"),
        (b"DIRECTION('',(0.0,0.0,-1.0))", b"DIRECTION('',(0.0,0.0,0.0))", "bad_geometry"),
        (b"DIRECTION('',(0.0,0.0,-1.0))", b"DIRECTION('',('x',0.0,0.0))", "bad_geometry"),
    ],
)
def test_bad_numbers_leave_their_faces_out(old, new, reason):
    data = W.box_file()
    assert old in data
    s = _full(data.replace(old, new, 1))
    assert s.counts["faces_done"] < 6 and {x.reason for x in s.skipped} == {reason}


def test_a_bspline_whose_counts_disagree_is_left_out():
    f, _ids = W.part_file(lambda f: [W.bspline_box_brep(f)])
    data = f.bytes().replace(b"(4,4),(4,4),(0.0,1.0),(0.0,1.0)", b"(4,5),(4,4),(0.0,1.0),(0.0,1.0)", 1)
    assert data != f.bytes()
    s = _full(data)
    assert s.counts["faces_done"] == 5 and {x.reason for x in s.skipped} == {"bad_geometry"}


def test_bspline_knots_past_their_bound():
    f, _ids = W.part_file(lambda f: [W.bspline_box_brep(f)])
    with pytest.raises(SldLimitError) as exc:
        _full(f.bytes(), bspline_knots=1)
    assert exc.value.detail["limit"] == "bspline_knots"


def test_a_body_past_the_node_bound():
    with pytest.raises(SldLimitError) as exc:
        _full(W.box_file(), brep_nodes=20)
    assert exc.value.detail["limit"] == "brep_nodes"


def test_loops_of_references_end():
    # an oriented face of itself, an oriented edge of itself, a shell of itself
    body = (
        b"#1=ORIENTED_FACE('',*,#1,.F.);\n#2=CLOSED_SHELL('',(#1));\n#3=MANIFOLD_SOLID_BREP('',#2);\n"
        b"#4=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNIT_ASSIGNED_CONTEXT((#5))REPRESENTATION_CONTEXT('',''));\n"
        b"#5=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));\n"
        b"#6=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#3,#7),#4);\n"
        b"#7=ORIENTED_CLOSED_SHELL('',*,#7,.F.);\n"
        b"#8=MAPPED_ITEM('',#9,#10);\n#9=REPRESENTATION_MAP(#10,#11);\n"
        b"#10=AXIS2_PLACEMENT_3D('',#12,$,$);\n#11=SHAPE_REPRESENTATION('',(#8),#4);\n"
        b"#12=CARTESIAN_POINT('',(0.,0.,0.));\n#13=SHAPE_REPRESENTATION_RELATIONSHIP('','',#6,#11);\n"
    )
    with _open(_file(body)) as doc:
        doc.tree()
        s = doc.scene()
        assert s.counts["faces_done"] == 0
        assert "assembly_cycle" in {w.code for w in doc.warnings}


def test_a_cycle_of_assemblies_is_not_followed_twice():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    a, b, c = f.product("a"), f.product("b"), f.product("c")
    ra, _ = f.shape(a, [box], ctx)
    rb, _ = f.shape(b, [], ctx)
    rc, _ = f.shape(c, [], ctx)
    f.occurrence(a, b, ra, rb, at=(1, 0, 0))
    f.occurrence(b, c, rb, rc, at=(0, 1, 0))
    f.occurrence(c, a, rc, ra, at=(0, 0, 1))
    with _open(f.bytes()) as doc:
        doc.scene()
        assert "assembly_cycle" in {w.code for w in doc.warnings}


def test_an_assembly_deeper_than_its_bound_is_cut():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    pds = [f.product(f"p{k}") for k in range(12)]
    reps = [f.shape(pd, [box] if k == 11 else [], ctx)[0] for k, pd in enumerate(pds)]
    for k in range(11):
        f.occurrence(pds[k], pds[k + 1], reps[k], reps[k + 1], at=(1, 0, 0))
    with _open(f.bytes(), depth=5) as doc:
        assert doc.tree().truncated
        assert doc.scene().items == ()


@pytest.mark.parametrize(
    ("limit", "value"),
    [("step_products", 1), ("step_occurrences", 1), ("step_styled_items", 1)],
)
def test_every_step_bound(limit, value):
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    f.colour(box, (1, 0, 0))
    f.colour(box, (0, 1, 0))
    part = f.product("part")
    top = f.product("top")
    rp, _ = f.shape(part, [box], ctx)
    rt, _ = f.shape(top, [], ctx)
    f.occurrence(top, part, rt, rp, at=(0, 0, 0))
    f.occurrence(top, part, rt, rp, at=(50, 0, 0))
    with pytest.raises(SldLimitError) as exc:
        _full(f.bytes(), **{limit: value})
    assert exc.value.detail["limit"] == limit


def test_a_zip_bomb_stops_at_its_bound():
    buf = io.BytesIO()
    filler = b"/* " + b"0" * (4 << 20) + b" */"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.stp", W.box_file()[:-30] + filler)
    with pytest.raises(SldLimitError) as exc:
        _open(buf.getvalue())
    assert exc.value.detail["limit"] == "zip_ratio"
    with pytest.raises(SldLimitError) as exc:
        _open(buf.getvalue(), whole_read_bytes=1 << 20, zip_ratio=100_000)
    assert exc.value.detail["limit"] == "zip_member_bytes"


def test_a_zip_without_a_step_file_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", b"nothing")
    with pytest.raises(FormatNotSupportedError):
        _open(buf.getvalue())


def test_a_time_bound_stops_the_index():
    data = _file(b"".join(b"#%d=X('a',(1.,2.,3.));\n" % i for i in range(1, 200_000)))
    with pytest.raises(SldLimitError) as exc:
        with _open(data, seconds=0.01) as doc:
            doc.tree()
    assert exc.value.detail["limit"] == "seconds"


# --------------------------------------------------------------------------- the time bound
def _related(transformed: bool, count: int = 60, products: int = 4) -> bytes:
    """A box part, ``count`` empty shape representations each related to every other
    (by a translation each, when ``transformed``), and ``products`` products whose
    shapes are related to the first of them."""
    f = W.P21()
    ctx = f.units()
    pd = f.product("box")
    f.shape(pd, [W.box_brep(f)], ctx)
    reps = [f.add(f"SHAPE_REPRESENTATION('',(),#{ctx})") for _ in range(count)]
    origin = f.axis2()
    for i in range(count):
        for j in range(i + 1, count):
            if transformed:
                idt = f.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{origin},#{f.axis2((2.0**i, 2.0**j, 0))})")
                f.add(
                    f"(REPRESENTATION_RELATIONSHIP('','',#{reps[i]},#{reps[j]})"
                    f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{idt})SHAPE_REPRESENTATION_RELATIONSHIP())"
                )
            else:
                f.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{reps[i]},#{reps[j]})")
    for k in range(products):
        other = f.product(f"p{k}")
        pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{other})")
        sr = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()}),#{ctx})")
        f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{sr})")
        f.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{sr},#{reps[0]})")
    return f.bytes()


def test_a_dense_graph_of_relationships_is_walked_once():
    """Relationships without transformations share one space: each representation is
    visited once for each product, not once for each path through the graph."""
    with _open(_related(False)) as doc:
        doc.tree()
        assert len(doc.scene().objects) == 1


def test_relationships_that_place_without_end_keep_the_time_bound():
    """Every visit and every link ticks the clock, so a graph whose paths all give new
    placements ends at the time bound, though its representations hold no items."""
    with pytest.raises(SldLimitError) as exc:
        with _open(_related(True, count=24, products=1), seconds=0.5) as doc:
            doc.tree()
    assert exc.value.detail["limit"] == "seconds"


def _fanned(levels: int, width: int = 10) -> bytes:
    """A box placed ``width`` times in an assembly, that one ``width`` times in another,
    ``levels`` deep: ``width ** levels`` paths."""
    f = W.P21()
    ctx = f.units()
    child = f.product("leaf")
    child_rep, _ = f.shape(child, [W.box_brep(f)], ctx)
    for d in range(levels):
        pd = f.product(f"level {d}")
        rep, _ = f.shape(pd, [], ctx)
        for k in range(width):
            f.occurrence(pd, child, rep, child_rep, at=(2.0 * k, 0, 0))
        child, child_rep = pd, rep
    return f.bytes()


def test_a_wide_assembly_keeps_no_node_for_every_path():
    with _open(_fanned(4)) as doc:
        tree = doc.tree()
        assert len(tree.nodes) == 10_000 and tree.truncated
        assert doc.counts()["items"] == 10_000 and doc.counts()["components"] == 11_110
        s = doc.scene()
        assert len(s.items) == 10_000 and len({it.instance for it in s.items}) == 10_000


def test_a_wide_assembly_keeps_the_time_bound_and_its_items_bound():
    data = _fanned(6)  # a million paths in 50 KB
    with pytest.raises(SldLimitError) as exc:
        with _open(data, seconds=0.3) as doc:
            doc.tree()
    assert exc.value.detail["limit"] == "seconds"
    with _open(data) as doc:
        assert doc.tree().truncated
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
        assert exc.value.detail["limit"] == "items"


def test_nested_composite_curves_end_at_their_bound():
    """A composite curve of composite curves, six deep and ten wide, the same polyline a
    million times over: sampled once a record and bounded in points, its face is left
    out at once (``edge_too_long``)."""
    f = W.P21()
    ctx = f.units()
    q = f.point((10, 0, 0))
    curve = f.add(f"POLYLINE('',(#{q},#{q}))")
    for _ in range(6):
        seg = f.add(f"COMPOSITE_CURVE_SEGMENT(.CONTINUOUS.,.T.,#{curve})")
        curve = f.add(f"COMPOSITE_CURVE('',({','.join([f'#{seg}'] * 10)}),.F.)")
    b = W.Brep(f)
    corners = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
    edges = [b.edge(curve, corners[0], corners[1])]
    for k in (1, 2, 3):
        a, c = corners[k], corners[(k + 1) % 4]
        edges.append(b.edge(f.line(a, tuple(c[i] - a[i] for i in range(3))), a, c))
    b.face(f.plane((0, 0, 0), (0, 0, 1), (1, 0, 0)), [[(e, True) for e in edges]])
    shell = b.shell("OPEN_SHELL")
    model = f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{shell}))")
    f.shape(f.product("sheet"), [model], ctx, kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION")
    s = _full(f.bytes())
    assert s.counts["faces_done"] == 0 and [x.reason for x in s.skipped] == ["edge_too_long"]


def test_control_points_tick_the_clock():
    """A B-spline face of 14,400 control points: the scene's clock is consulted while the
    body is mapped, before any tessellation, so the call's time bound and its
    cancellation hold there too."""
    n = 120
    grid = [[(10.0 * i / (n - 1), 20.0 * j / (n - 1), 30.0) for j in range(n)] for i in range(n)]
    knots = [float(k) for k in range(n)]
    mults = [2] + [1] * (n - 2) + [2]

    def top(f):
        return f.bspline_surface(1, 1, grid, mults, knots, mults, knots), True

    data = W.part_file(lambda f: [W.box_brep(f, top=top)])[0].bytes()
    calls = []
    real = solidseas.tessellate.tessellate_transmit

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    with _open(data) as doc:
        doc.tree()
        solidseas.tessellate.tessellate_transmit = counted
        try:
            with pytest.raises(ReadCancelledError):
                doc.scene(cancelled=lambda: True)
        finally:
            solidseas.tessellate.tessellate_transmit = real
    assert calls == []


def test_the_scene_keeps_what_it_did_when_mapping_runs_out_of_time():
    """A body whose mapping outlasts the scene's ``max_seconds`` is a skipped item
    (``max_seconds``) with the warning ``faces_left_out``, not a failed scene."""
    n = 200
    grid = [[(10.0 * i / (n - 1), 20.0 * j / (n - 1), 30.0) for j in range(n)] for i in range(n)]
    knots = [float(k) for k in range(n)]
    mults = [2] + [1] * (n - 2) + [2]

    def top(f):
        return f.bspline_surface(1, 1, grid, mults, knots, mults, knots), True

    data = W.part_file(lambda f: [W.box_brep(f, top=top)])[0].bytes()
    with _open(data) as doc:
        doc.tree()
        t0 = time.perf_counter()
        s = doc.scene(max_seconds=0.05)
        bounded = time.perf_counter() - t0
    assert s.items == () and [x.reason for x in s.skipped] == ["max_seconds"]
    assert "faces_left_out" in {w.code for w in s.warnings}
    with _open(data) as doc:
        doc.tree()
        t0 = time.perf_counter()
        doc.scene()
        whole = time.perf_counter() - t0
    assert bounded < 0.5 * whole  # the mapping stopped near the bound, not at its end


# --------------------------------------------------------------------------- damaged records
def test_a_damaged_record_leaves_out_only_what_needs_it():
    """Records are parsed when read: one that cannot be parsed leaves out the faces of
    the second box that use it (``bad_reference``); the first box is whole."""
    f, _ids = W.part_file(lambda f: [W.box_brep(f), W.box_brep(f, origin=(50, 0, 0))])
    data = f.bytes()
    at = data.index(b"CARTESIAN_POINT('',(50.0,0.0,0.0))")
    data = data[:at] + data[at:].replace(b"(50.0,0.0,0.0)", b"(50.0,0.0,0.0 @)", 1)
    s = _full(data)
    assert len(s.objects) == 2 and s.skipped and {x.reason for x in s.skipped} == {"bad_reference"}
    assert s.counts["faces_done"] == 12 - len(s.skipped)
    first = s.objects[0].measures()
    assert first["volume_m3"] == pytest.approx(6e-6, rel=1e-9)


def test_a_damaged_solid_record_is_left_out_and_warned():
    f, _ids = W.part_file(lambda f: [W.box_brep(f), W.box_brep(f, origin=(50, 0, 0), name="second")])
    data = f.bytes().replace(b"MANIFOLD_SOLID_BREP('second',", b"MANIFOLD_SOLID_BREP('second' @,", 1)
    with _open(data) as doc:
        s = doc.scene()
        assert len(s.objects) == 1
        assert "representation_skipped" in {w.code for w in doc.warnings}


def test_entity_names_inside_strings_do_not_confuse_the_index():
    body = b"#1=X('#2=Y(); ENDSEC; END-ISO-10303-21;');\n#2=Z('/* not a comment */');\n"
    p = part21.open(_file(body), limits=Limits())
    assert len(p) == 2 and p.record(1).params == ["#2=Y(); ENDSEC; END-ISO-10303-21;"]
    assert p.record(2).params == ["/* not a comment */"]
