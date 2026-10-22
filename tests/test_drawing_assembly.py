"""Drawings of assemblies (docs/drawings/assemblies.md): the source read from o08, o15
and o16, each part tessellated once and placed for every instance, the views, the
parts list and the balloons laid out, the checks, the files and editing.

o16 holds seven parts list lines: two instances of o02 (item 1), o06 in its
configuration OracleAlt (item 2, whose bodies the part does not store, so it is
not drawn), the sub-assembly o15 (item 3), three instances of o07 (item 4), the
STEP import o09, o17 and a virtual part; a third instance of o02 is excluded from
the bill of materials and drawn without a balloon.

A synthetic assembly of two ``drawing_parts`` boxes, a key inside a block, shows a
part hidden behind others ballooned on its hidden lines.
"""

from __future__ import annotations

import functools
import io
import math
import shutil
from dataclasses import replace

import pytest

from drawing_support import fixture
from pdf_reader import PdfDocument
from solidseas.drawing import assembly, document, edit, facegraph, make_drawing, merge, pipeline
from solidseas.drawing import display as D
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.drawing.checks import run_checks
from solidseas.drawing.dxf import write_dxf
from solidseas.drawing.layout.index import Box, segments_cross
from solidseas.drawing.layout.sheet import frame
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.pdf import write_pdf
from solidseas.drawing.plan import assembly as plan_assembly
from solidseas.drawing.source import open_source
from solidseas.errors import DrawingTooComplexError, InvalidArgumentError, UnsupportedOperationError
from solidseas.formats.solidworks import open_document
from solidseas.formats.solidworks.components import Placement
from support import parts_at_stored_paths

O16 = "o16_asm_features.SLDASM"
FIELDS = {"drawn_by": "Ann Example"}


def _settings() -> S.DrawingSettings:
    s = S.DrawingSettings()
    return replace(s, company=replace(s.company, name="Example Engineering Co."))


@functools.cache
def source(name: str = O16):
    return open_source(fixture(name))


@functools.cache
def drawn(name: str = O16, views: tuple[str, ...] | None = None):
    options = T.DrawingOptions(views=views) if views else None
    return pipeline.run(fixture(name), settings=_settings(), fields=FIELDS, options=options)


def annotations(d, cls):
    return [a for a in d.sheet.annotations if isinstance(a, cls)]


# --------------------------------------------------------------------------- the source


def test_an_assembly_is_read_with_its_instances_and_parts_list():
    s = source()
    assert s.format == "sldasm" and assembly.is_assembly(s) and s.name == O16
    assert s.configuration == "Default" and s.units.unit == "mm" and s.material is None
    a = s.assembly
    assert [(line.item, line.part_number, line.quantity) for line in a.bom] == [
        ("1", "o02_boxA", 2),
        ("2", "o06_boxA_props_mat_cfg", 1),
        ("3", "o15_sub_asm", 1),
        ("4", "o07_boxB_h31", 3),
        ("5", "o09_import_step", 1),
        ("6", "o17_деталь", 1),
        ("7", "Part12^o16_asm_features", 1),
    ]
    assert a.bom[1].description == "Oracle test box"
    items = {i.id: i.item for i in a.instances}
    assert items["o02_boxA-1"] == "1" and items["o02_boxA-3"] is None  # excluded from the BOM, still drawn
    assert items["o15_sub_asm-1/o07_boxB_h31-1"] == "3"  # a part inside the sub-assembly: its line
    assert len(a.instances) == 11 and len(a.bodies) == 11 == len(s.selected_bodies())
    assert all(isinstance(b, assembly.PlacedBody) and b.name.startswith(b.instance + "/") for b in a.bodies)
    assert a.left_out == (
        ("o06_boxA_props_mat_cfg-1", "its part stores no solid body for configuration 'OracleAlt'"),
    )
    assert any(w.startswith("o06_boxA_props_mat_cfg-1 is not drawn") for w in s.warnings)
    assert [i.id for i in a.instances_of(a.bom[2])] == [
        "o15_sub_asm-1/o02_boxA-1",
        "o15_sub_asm-1/o07_boxB_h31-1",
    ]


def test_the_geometry_digest_covers_parts_and_placements():
    a, b = open_source(fixture(O16)), source()
    assert a.geometry_digest == b.geometry_digest and a.sha256 == b.sha256
    assert source("o15_sub_asm.SLDASM").geometry_digest != b.geometry_digest
    moved = Placement(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 1e-6))
    still = Placement(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))
    assert assembly._placement_text(moved) != assembly._placement_text(still)


def test_an_open_assembly_document_is_read_and_left_open():
    with open_document(fixture("o08_asm_2x_boxA.SLDASM")) as doc:
        s = open_source(doc)
        assert s.format == "sldasm" and [line.quantity for line in s.assembly.bom] == [2]
        assert doc.doc_type == "assembly"  # still usable


def test_bodies_name_the_instances_to_draw():
    s = open_source(fixture(O16), bodies=("o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1"))
    assert [i.id for i in s.assembly.instances] == ["o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1"]
    assert sum(b.selected for b in s.bodies) == 2 and len(s.bodies) == 11
    with pytest.raises(InvalidArgumentError):
        open_source(fixture(O16), bodies=("nothing-1",))


def test_an_assembly_none_of_whose_parts_is_found_has_nothing_to_draw(tmp_path):
    if parts_at_stored_paths("o08_asm_2x_boxA.SLDASM"):
        pytest.skip("the fixture kit's output here holds the parts at their stored paths")
    lone = tmp_path / "o08_asm_2x_boxA.SLDASM"
    shutil.copyfile(fixture("o08_asm_2x_boxA.SLDASM"), lone)
    with pytest.raises(UnsupportedOperationError) as info:
        open_source(lone)
    assert info.value.detail["rule"] == "no_instances" and "o02_boxA-1" in str(info.value)


def test_parts_kept_elsewhere_in_the_opened_folder_are_found(tmp_path):
    if parts_at_stored_paths("o08_asm_2x_boxA.SLDASM"):
        pytest.skip("the fixture kit's output here holds the parts at their stored paths")
    project = tmp_path / "project"
    (project / "asm").mkdir(parents=True)
    (project / "parts").mkdir()
    asm = project / "asm" / "o08_asm_2x_boxA.SLDASM"
    shutil.copyfile(fixture("o08_asm_2x_boxA.SLDASM"), asm)
    shutil.copyfile(fixture("o02_boxA.SLDPRT"), project / "parts" / "o02_boxA.SLDPRT")
    with pytest.raises(UnsupportedOperationError):
        open_source(asm)  # its own folder alone, as SOLIDWORKS looks
    with assembly.searching([project]):
        src = open_source(asm)
    assert len(src.assembly.instances) == 2
    # the assembly's own folder is searched too when the folder given does not hold it
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.copyfile(fixture("o02_boxA.SLDPRT"), project / "asm" / "o02_boxA.SLDPRT")
    with assembly.searching([elsewhere]):
        assert len(open_source(asm).assembly.instances) == 2


def test_the_drawing_process_looks_in_the_folder_the_request_names(tmp_path):
    import json

    from solidseas_app.viewer.drawingproc import _answer

    if parts_at_stored_paths("o08_asm_2x_boxA.SLDASM"):
        pytest.skip("the fixture kit's output here holds the parts at their stored paths")
    project = tmp_path / "project"
    (project / "asm").mkdir(parents=True)
    (project / "parts").mkdir()
    asm = project / "asm" / "o08_asm_2x_boxA.SLDASM"
    shutil.copyfile(fixture("o08_asm_2x_boxA.SLDASM"), asm)
    shutil.copyfile(fixture("o02_boxA.SLDPRT"), project / "parts" / "o02_boxA.SLDPRT")

    def probe(**extra):
        header, _frames = _answer(json.dumps({"op": "probe", "part": str(asm), **extra}).encode())
        return json.loads(header)["result"]

    assert probe()["refused"]
    assert probe(folder=str(project))["refused"] is None


# --------------------------------------------------------------------------- placing a part


def _box_model():
    return facegraph.from_document(open_document(fixture("o02_boxA.SLDPRT")))


TURN = Placement(((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), (0.1, 0.2, 0.3))
MIRROR = Placement(((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))


def test_a_placed_model_is_moved_whole():
    m = _box_model()
    p = facegraph.place(m, TURN)
    assert [TURN.apply(q) for q in m.points] == pytest.approx(list(p.points))
    assert p.diagonal == pytest.approx(m.diagonal) and p.tolerance == m.tolerance
    for f, g in zip(m.faces, p.faces, strict=True):
        assert TURN.apply(f.surface.origin) == pytest.approx(g.surface.origin)
        n = g.surface.normal
        assert g.surface.offset == pytest.approx(sum(a * b for a, b in zip(n, g.surface.origin, strict=True)))
    assert {f.signature for f in p.faces}.isdisjoint({f.signature for f in m.faces})
    for e in m.edges.values():
        q = p.edges[e.key]
        assert [TURN.apply(x) for x in e.points] == pytest.approx(list(q.points))
    assert p.signatures() == facegraph.place(m, TURN).signatures()  # the same placement, the same names
    same = facegraph.place(m, Placement(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)))
    assert same.signatures() == m.signatures() and same.points == m.points


def test_a_mirrored_placement_keeps_the_faces_outward():
    m = _box_model()
    p = facegraph.place(m, MIRROR)
    assert p.triangles == tuple((a, c, b) for a, b, c in m.triangles)
    lo, hi = p.box
    centre = tuple((lo[k] + hi[k]) / 2 for k in range(3))
    for f in p.faces:
        out = tuple(f.surface.origin[k] - centre[k] for k in range(3))
        assert sum(a * b for a, b in zip(f.surface.normal, out, strict=True)) > 0  # still outward


def test_each_part_is_tessellated_once_however_many_instances_use_it(monkeypatch):
    calls = []
    real = facegraph.tessellate_body
    monkeypatch.setattr(
        facegraph, "tessellate_body", lambda body, **kw: calls.append(body) or real(body, **kw)
    )
    s = source()
    model = facegraph.from_bodies(s.selected_bodies(), name=s.name)
    assert len(model.bodies) == 11 and len(calls) == len({id(b.body) for b in s.assembly.bodies}) == 5
    assert [b.name for b in model.bodies] == [b.name for b in s.assembly.bodies]
    # a part's bodies count once against the bound; its faces each time
    facegraph.from_bodies(s.selected_bodies(), limits=DrawingLimits(bodies=5))
    with pytest.raises(DrawingTooComplexError):
        facegraph.from_bodies(s.selected_bodies(), limits=DrawingLimits(bodies=4))
    with pytest.raises(DrawingTooComplexError):
        facegraph.from_bodies(s.selected_bodies(), limits=DrawingLimits(faces=60))


# --------------------------------------------------------------------------- the drawing


def test_an_assembly_drawing_has_views_a_parts_list_and_balloons():
    run = drawn()
    d = run.drawing
    assert d.model["format"] == "sldasm" and d.features == () and d.dimensions == ()
    o = d.options
    assert (o.views, o.hidden, o.front) == (("front", "top", "right", "isometric"), False, "+z")
    assert run.features == T.FeatureSet()
    plan = run.plan[0]
    assert [line.item for line in plan.bom] == ["1", "2", "3", "4", "5", "6", "7"]
    assert [b.item for b in plan.balloons] == ["1", "3", "4", "5", "6", "7"]  # o06 is not drawn
    iso = next(s.id for s in plan.views if s.kind == "isometric")
    assert {b.view for b in plan.balloons} == {iso}
    (parts,) = annotations(d, D.PartsList)
    assert parts.columns == ("ITEM", "PART NO.", "DWG NO.", "DESCRIPTION", "QTY.")
    assert parts.rows[0] == ("1", "O02_BOXA", "O02_BOXA", "", "2") and parts.rows[1][3] == "ORACLE TEST BOX"
    assert parts.rows[6][:3] == ("7", "PART12^O16_ASM_FEATURES", "")  # a virtual part: no drawing of its own
    assert [r[0] for r in parts.rows] == ["1", "2", "3", "4", "5", "6", "7"]
    f = frame(d.sheet.name, d.settings, parts_height=parts.height)
    # it stands on the title block, its right edge the title block's, grown leftward to
    # the width its longest part numbers need, so no cell is cut
    from solidseas.drawing.layout import partslist as PL

    assert (parts.at[0] + parts.width, parts.at[1]) == pytest.approx((f.title.x1, f.title.y1))
    from solidseas.drawing.layout.arrange import text_height

    need = PL.natural_width(parts.rows, text_height(run.plan.done.planned.detail.ctx.unit), parts.columns)
    assert parts.width == pytest.approx(min(max(f.title.width, need), f.title.width * PL.MAX_GROW))
    assert parts.width > f.title.width
    assert [b.item for b in annotations(d, D.Balloon)] == ["1", "3", "4", "5", "6", "7"]
    assert [c for c in d.checks if c.level != "information"] == [
        c for c in d.checks if c.code in ("ASM.balloons", "R10.text") and c.level != "information"
    ]
    assert any(c.code == "ASM.balloons" and c.item == "balloon-2" for c in d.checks)


def test_the_overall_size_is_three_reference_dimensions():
    run = drawn("o15_sub_asm.SLDASM")
    plan = run.plan[0]
    got = {d.key: (round(d.value * 1000, 3), d.tolerance, d.role) for d in plan.dimensions}
    assert got == {
        "overall/x": (40.0, "reference", "envelope"),
        "overall/y": (51.0, "reference", "envelope"),
        "overall/z": (30.0, "reference", "envelope"),
    }
    texts = [a.text.value for a in annotations(run.drawing, D.Dimension)]
    assert sorted(texts) == ["(30.0)", "(40.0)", "(51.0)"]
    assert plan.dimensions[0].view == plan.views[0].id, "the main view first"
    assert not plan.notes


def test_an_overall_size_ending_on_a_curved_face_is_a_note():
    # o16's highest point is on a curved part: no straight line ends there in any view
    plan = drawn().plan[0]
    assert plan.dimensions == ()
    assert [n.text for n in plan.notes][0] == "OVERALL SIZE (REF): 220.0 X 241.4 X 60.0"


def test_balloons_stand_outside_their_view_on_leaders_that_do_not_cross():
    d = drawn().drawing
    placed = {p.view: p for p in d.sheet.views}
    boxes = {}
    for g in d.sheet.geometry:
        x0, y0, x1, y1 = g.bounds()
        b = boxes.get(g.src.view)
        boxes[g.src.view] = (
            (x0, y0, x1, y1) if b is None else (min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1))
        )
    balloons = annotations(d, D.Balloon)
    for b in balloons:
        assert b.view in placed
        box = Box(*boxes[b.view])
        circle = Box(
            b.centre[0] - b.radius, b.centre[1] - b.radius, b.centre[0] + b.radius, b.centre[1] + b.radius
        )
        assert not circle.hits(box)
        anchor, end = b.leader
        assert math.dist(end, b.centre) == pytest.approx(b.radius)
        angle = math.degrees(math.atan2(abs(end[1] - anchor[1]), abs(end[0] - anchor[0])))
        assert 15.0 - 1e-6 <= angle <= 75.0 + 1e-6
    for i, a in enumerate(balloons):
        for b in balloons[i + 1 :]:
            assert not segments_cross(*a.leader, *b.leader)
            assert math.dist(a.centre, b.centre) >= a.radius + b.radius


def test_a_balloon_goes_to_the_next_view_when_its_own_is_not_drawn():
    run = drawn("o15_sub_asm.SLDASM", views=("front", "top", "right"))
    front = next(s.id for s in run.plan[0].views if s.kind == "base")
    assert {b.view for b in annotations(run.drawing, D.Balloon)} == {front}
    plan = drawn("o15_sub_asm.SLDASM").plan[0]
    assert all(b.others and b.others[0][0] == front for b in plan.balloons)


def test_an_assembly_drawing_is_saved_and_written():
    d = drawn().drawing
    back, problems = document.loads(document.dumps(d))
    assert problems == [] and assembly.is_assembly(back)
    assert annotations(back, D.PartsList)[0].rows == annotations(d, D.PartsList)[0].rows
    was, now = annotations(d, D.Balloon), annotations(back, D.Balloon)
    assert [b.item for b in now] == [b.item for b in was]
    assert [c for b in now for c in b.centre] == pytest.approx([c for b in was for c in b.centre], abs=1e-3)
    assert document.dumps(back) == document.dumps(document.loads(document.dumps(back))[0])
    pdf, dxf = io.BytesIO(), io.BytesIO()
    write_pdf(d, pdf)
    write_dxf(d, dxf)
    text = dxf.getvalue().decode("ascii", "replace")
    assert "DWG NO." in text and "O09_IMPORT_STEP" in text
    words = [r.text for r in PdfDocument(pdf.getvalue()).text_runs()]
    assert "DWG NO." in words and "O09_IMPORT_STEP" in words and "7" in words


def test_a_parts_list_set_in_the_bom_editor_is_drawn_and_kept():
    from solidseas.bomtable import row_keys, spec

    with open_document(fixture(O16)) as doc:
        from solidseas.bom import build_bom

        keys = row_keys(build_bom(doc, bom_type="indented"))
    edited = spec(
        "indented",
        ["item", "part_number", ("drawing", "DRAWING"), "description", "property:PartNo", "quantity"],
        order=[keys["4"]],
        hidden=[keys["6"]],
        overrides={(keys["2"], "description"): "Anodised oracle box", (keys["5"], "drawing"): "SK-12"},
    )
    options = T.DrawingOptions(parts_list=T.parts_list_text(edited))
    run = pipeline.run(fixture(O16), settings=_settings(), fields=FIELDS, options=options)
    d, plan = run.drawing, run.plan[0]
    assert plan.bom_columns == ("ITEM NO.", "PART NUMBER", "DRAWING", "DESCRIPTION", "PARTNO", "QTY.")
    (parts,) = annotations(d, D.PartsList)
    assert parts.columns == ("ITEM NO.", "PART NUMBER", "DRAWING", "DESCRIPTION", "PARTNO", "QTY.")
    rows = {r[1].strip(): r for r in parts.rows}
    assert parts.rows[0][:2] == ("1", "O07_BOXB_H31"), "the order the editor set, numbered as shown"
    assert "O17_ДЕТАЛЬ" not in rows, "a hidden row is not on the list"
    assert rows["O06_BOXA_PROPS_MAT_CFG"][3:5] == ("ANODISED ORACLE BOX", "ORACLE-PN-123")
    assert rows["O09_IMPORT_STEP"][2] == "SK-12" and rows["O02_BOXA"][2] == "O02_BOXA"
    assert any(r[0] == "4.1" and r[1].strip() == "O02_BOXA" for r in parts.rows), "indented, under o15"
    items = {line.item for line in plan.bom}
    assert {b.item for b in plan.balloons} <= items and len(plan.bom) == 8
    back, problems = document.loads(document.dumps(d))
    assert problems == [] and back.options.parts_list == options.parts_list
    plain = document.dumps(drawn().drawing)
    assert b"parts_list" not in plain, "a drawing with the default parts list is written as before"


def test_an_assembly_drawing_is_edited_and_updated():
    d = make_drawing(fixture("o15_sub_asm.SLDASM"), settings=_settings(), fields=FIELDS)
    titled, checks = edit.set_title(d, "title", "FRAME, WELDED")
    assert ("title", "FRAME, WELDED") in {(k, f.text) for k, f in titled.title}
    assert len(annotations(titled, D.PartsList)) == 1 and len(annotations(titled, D.Balloon)) == 2
    assert [c for c in checks if c.level != "information"] == []
    noted, _checks = edit.edit_notes(titled, ["ASSEMBLE WITH THE PARTS CLEAN AND DRY."])
    assert [n.text for _i, n in noted.notes] == ["ASSEMBLE WITH THE PARTS CLEAN AND DRY."]
    assert len(annotations(noted, D.Balloon)) == 2
    fewer, _checks = edit.remove_view(noted, "isometric")
    assert len(annotations(fewer, D.Balloon)) == 2  # on the front now
    same, report = merge.regenerate(fewer, fixture("o15_sub_asm.SLDASM"))
    assert report.model_unchanged and annotations(same, D.PartsList) == annotations(fewer, D.PartsList)


def test_a_part_changed_under_the_same_assembly_file_changes_the_model(tmp_path):
    if parts_at_stored_paths("o15_sub_asm.SLDASM"):
        pytest.skip("the fixture kit's output here holds the parts at their stored paths")
    for name in ("o15_sub_asm.SLDASM", "o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT"):
        shutil.copyfile(fixture(name), tmp_path / name)
    asm = tmp_path / "o15_sub_asm.SLDASM"
    d = make_drawing(asm, settings=_settings(), fields=FIELDS)
    edit.forget(d)
    assert assembly.same_file(d.model, open_source(asm))
    shutil.copyfile(
        fixture("o06_boxA_props_mat_cfg.SLDPRT"), tmp_path / "o07_boxB_h31.SLDPRT"
    )  # another shape
    changed = open_source(asm)
    assert changed.sha256 == d.model["sha256"] and changed.geometry_digest != d.model["geometry"]
    assert not assembly.same_file(d.model, changed) and not assembly.same_file(
        d.model, dict(d.model, geometry="0")
    )
    with pytest.raises(InvalidArgumentError) as info:
        edit.attach(d, asm)
    assert info.value.detail["rule"] == "model_changed"
    updated, report = merge.regenerate(d, asm)
    assert not report.model_unchanged and updated.model["geometry"] == changed.geometry_digest
    assert len(annotations(updated, D.Balloon)) == 2


def test_each_item_names_its_own_drawing():
    s = _settings()
    lines = drawn().plan[0].bom
    assert [line.drawing for line in lines] == [
        "o02_boxA",
        "o06_boxA_props_mat_cfg",
        "o15_sub_asm",
        "o07_boxB_h31",
        "o09_import_step",
        "o17_деталь",
        "",  # a virtual part has no file, so no drawing, of its own
    ]
    # as a component's own drawing is numbered: its property among the Settings' names first
    named = replace(s, title_sources=replace(s.title_sources, number=("PartNo", *s.title_sources.number)))
    line = source().assembly.bom[1]
    assert plan_assembly.drawing_number(line, named) == "ORACLE-PN-123"
    assert plan_assembly.drawing_number(line, s) == "o06_boxA_props_mat_cfg"
    own = make_drawing(fixture("o06_boxA_props_mat_cfg.SLDPRT"), settings=named)
    assert document.title_text(own, "number").upper() == "ORACLE-PN-123"


def test_a_long_parts_list_continues_in_columns_to_its_left():
    from solidseas.drawing.layout import partslist as PL
    from solidseas.drawing.layout.glyphs import Pen
    from solidseas.drawing.layout.index import Box as LBox

    h = 3.5
    rows = tuple((str(n), f"P-{n:03d}", f"P-{n:03d}", "PLATE", "1") for n in range(1, 61))
    short = PL.shape(rows[:5], h, 178.0, 200.0, 800.0)
    assert (short.columns, short.per_column, short.width) == (1, 5, 178.0)
    tall = PL.shape(rows, h, 178.0, 200.0, 1200.0)
    fit = int(200.0 * PL.PARTS_SHARE // PL.row_height(h)) - 1
    assert tall.columns == -(-60 // fit) and tall.per_column * tall.columns >= 60
    assert tall.height <= 200.0 * PL.PARTS_SHARE
    three = PL.shape(rows, h, 178.0, 200.0, 800.0)  # three columns across, so each taller
    assert (three.columns, three.per_column) == (3, 20) and three.height > 200.0 * PL.PARTS_SHARE
    narrow = PL.shape(rows, h, 178.0, 200.0, 400.0)  # a sheet as wide as two columns holds one
    assert narrow.columns == 1 and narrow.height > 200.0 * PL.PARTS_SHARE, "taller, as no more fit"
    pen = Pen()
    box = LBox(1000.0 - tall.total_width, 50.0, 1000.0, 50.0 + tall.height)
    made = PL.parts_list(pen, box, rows, h, per_column=tall.per_column)
    assert len(made) == tall.columns
    assert [m.rows[0][0] for m in made] == [str(1 + j * tall.per_column) for j in range(tall.columns)]
    assert made[0].at[0] + made[0].width == pytest.approx(1000.0), "the first column on the title block"
    assert made[1].at[0] + made[1].width == pytest.approx(made[0].at[0]), "the next to its left"
    assert all(m.columns == PL.COLUMNS and m.at[1] == 50.0 for m in made), "each with its headings"
    assert [r[0] for m in made for r in m.rows] == [str(n) for n in range(1, 61)]


def _balloon(d, item):
    return next(a for a in annotations(d, D.Balloon) if a.item == item)


def test_a_moved_balloon_stays_where_it_was_put_and_its_leader_follows():
    d = make_drawing(fixture("o15_sub_asm.SLDASM"), settings=_settings(), fields=FIELDS)
    first = annotations(d, D.Balloon)[0]
    anchor = first.leader[0]
    moved, _checks = edit.move_balloon(d, first.item, 40.0, 30.0)
    b = _balloon(moved, first.item)
    assert b.leader[0] == pytest.approx(anchor), "the leader still ends on the part"
    assert b.centre == pytest.approx((anchor[0] + 40.0, anchor[1] + 30.0))
    tip = b.leader[-1]
    assert math.hypot(tip[0] - b.centre[0], tip[1] - b.centre[1]) == pytest.approx(b.radius)
    assert moved.options.balloons == ((first.item, 40.0, 30.0),)
    # kept in the file, and through a lay out again
    assert document.loads(document.dumps(moved))[0].options.balloons == ((first.item, 40.0, 30.0),)
    again, _c = edit.relayout(moved)
    assert _balloon(again, first.item).centre == pytest.approx(b.centre)
    # too close to the part to show a leader: pushed out along the same direction
    near, _c = edit.move_balloon(d, first.item, 0.5, 0.5)
    put = _balloon(near, first.item)
    assert math.hypot(put.centre[0] - anchor[0], put.centre[1] - anchor[1]) > put.radius
    reset, _c = edit.reset_balloon(moved, first.item)
    assert reset.options.balloons == ()
    assert _balloon(reset, first.item).centre == pytest.approx(first.centre)
    with pytest.raises(InvalidArgumentError):
        edit.move_balloon(d, "99", 1.0, 1.0)


def test_a_balloon_moved_onto_the_parts_list_is_reported():
    d = make_drawing(fixture("o15_sub_asm.SLDASM"), settings=_settings(), fields=FIELDS)
    (first, *_rest) = annotations(d, D.Balloon)
    (parts,) = annotations(d, D.PartsList)
    anchor = first.leader[0]
    target = (parts.at[0] + parts.width / 2, parts.at[1] + parts.height / 2)
    onto, _checks = edit.move_balloon(d, first.item, target[0] - anchor[0], target[1] - anchor[1])
    found = [c.message for c in onto.checks if c.item == f"balloon-{first.item}"]
    assert any("where it was moved, could not be placed clear" in m for m in found), found


def test_a_balloon_with_no_clear_place_stacks_on_a_nearby_one():
    from solidseas.drawing.layout import partslist as PL
    from solidseas.drawing.layout.glyphs import Pen
    from solidseas.drawing.layout.index import HARD, Index
    from solidseas.drawing.layout.index import Box as LBox

    area = LBox(0.0, 0.0, 400.0, 300.0)
    index = Index()
    partner = D.Balloon("1", (120.0, 120.0), 4.0, ((100.0, 100.0), (117.2, 117.2)), "v-1")
    index.add(HARD, LBox(116.0, 116.0, 124.0, 124.0), "balloon-1")
    near = PL.stacked_balloon(index, area, partner, (105.0, 102.0), 4.0, "balloon-2")
    assert near is not None
    assert math.hypot(near[0] - 120.0, near[1] - 120.0) == pytest.approx(8.0), "touching it"
    assert near[0] > 120.0 and near[1] > 120.0, "beyond it, along its leader"
    # a part too far away does not stack, and a blocked place is not taken
    assert PL.stacked_balloon(index, area, partner, (200.0, 200.0), 4.0, "balloon-2") is None
    index.add(HARD, LBox(near[0] - 4, near[1] - 4, near[0] + 4, near[1] + 4), "other")
    aside = PL.stacked_balloon(index, area, partner, (105.0, 102.0), 4.0, "balloon-2")
    assert aside is not None and aside != near, "to one side instead"
    made = PL.paint_balloon(Pen(), "2", aside, None, (105.0, 102.0), 4.0, 3.5, "v-1", "balloon-2")
    assert made.leader == ((105.0, 102.0),), "no leader of its own, only the point on its part"


def test_an_item_no_view_draws_is_noted_and_the_check_says_why():
    from solidseas.drawing.plan.assembly import not_shown_items, not_shown_note

    run = drawn()
    plan, d = run.plan[0], run.drawing
    assert "ITEM 2 NOT SHOWN" in [n.text for n in plan.notes], "o06 is not drawn in any view"
    (check,) = [c for c in d.checks if c.code == "ASM.balloons"]
    assert check.level == "information" and "not drawn in any view" in check.message
    assert not_shown_note(["3", "7"]) == "ITEMS 3, 7 NOT SHOWN" and not_shown_items(
        "ITEMS 3, 7 NOT SHOWN"
    ) == {"3", "7"}
    assert not_shown_items("OVERALL SIZE (REF): 1 X 2 X 3") == set()


# --------------------------------------------------------------------------- a part hidden by others


def _synthetic_assembly(parts):
    """A stand-in for the source stage: an assembly of synthetic parts (``drawing_parts``),
    each ``(item, part number, Part, translation in metres)`` one instance and one parts
    list line, so the model stage and everything after it run as on a file."""
    import hashlib

    import drawing_parts
    from solidseas.drawing.source import DrawingSource, SourceBody, SourceUnits
    from solidseas.formats.solidworks.parasolid import ParasolidBody

    placed, instances, lines, records = [], [], [], []
    for item, number, part, at in parts:
        xt, _truth = drawing_parts.build(part)
        body = ParasolidBody("Config-0/body1", 0, "Default", "partition", None, "solid", xt)
        inst = f"{number}-1"
        name = f"{inst}/Config-0/body1"
        placement = Placement(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), at)
        instances.append(assembly.AssemblyInstance(inst, inst, number, "Default", item, (len(placed),)))
        placed.append(assembly.PlacedBody(body, name, placement, inst))
        records.append(SourceBody(name, "solid", 6, True))
        lines.append(T.BomLine(item, number.upper(), instances=(inst,), file=f"{number}.SLDPRT"))
    digest = hashlib.sha256(repr([(n, a) for _i, n, _p, a in parts]).encode()).hexdigest()

    def stage(part=None, *, configuration=None, bodies=None, units=None, title_names=(), limits=None):
        return DrawingSource(
            name="hidden_inside.SLDASM",
            format=assembly.FORMAT,
            kind="brep",
            configuration="Default",
            bodies=tuple(records),
            units=SourceUnits("mm", "file", None, "mm"),
            material=None,
            properties=(),
            hints=(),
            sha256=hashlib.sha256(digest.encode()).hexdigest(),
            geometry_digest=digest,
            properties_digest="0" * 64,
            _bodies=tuple(placed),
            assembly=assembly.AssemblyContents(tuple(instances), tuple(placed), tuple(lines)),
        )

    return stage


@functools.cache
def hidden_inside(where: str = "inside"):
    """A 100 x 80 x 60 mm block and a 20 x 10 x 10 mm key: the key inside the block, so
    hidden behind it in every view; inside it on its bottom face (``flush``); or
    standing clear of it beside it (``beside``)."""
    from drawing_parts import MM, box

    at = {"inside": (40, 35, 25), "flush": (40, 0, 25), "beside": (130, 35, 25)}[where]
    at = tuple(v * MM for v in at)
    stage = _synthetic_assembly(
        [
            ("1", "block", box(100 * MM, 80 * MM, 60 * MM), (0.0, 0.0, 0.0)),
            ("2", "key", box(20 * MM, 10 * MM, 10 * MM), at),
        ]
    )
    return pipeline.run(None, settings=_settings(), fields=FIELDS, stages={"source": stage})


def _on(segment, p, tol=1e-9) -> bool:
    """Whether point ``p`` (view metres) lies on ``segment``."""
    (x0, y0), (x1, y1) = segment.p0, segment.p1
    cross = (x1 - x0) * (p[1] - y0) - (y1 - y0) * (p[0] - x0)
    within = min(x0, x1) - tol <= p[0] <= max(x0, x1) + tol and min(y0, y1) - tol <= p[1] <= max(y0, y1) + tol
    return abs(cross) <= tol and within


def test_a_part_hidden_inside_another_is_ballooned_on_its_hidden_lines():
    run = hidden_inside()
    plan, d = run.plan[0], run.drawing
    assert d.options.hidden is False, "the drawing's hidden lines stay off"
    by_item = {b.item: b for b in plan.balloons}
    assert set(by_item) == {"1", "2"}, "the key inside the block has a balloon"
    key = by_item["2"]
    front = next(s for s in plan.views if s.kind == "base")
    assert (key.view, key.instance) == (front.id, "key-1"), "the front: the isometric draws no hidden lines"
    assert [v for v, _i, _p in key.others] == [s.id for s in plan.views if s.kind == "projected"]
    views = {s.id: g for s, g in run.orchestrated.views}
    for spec, geom in run.views:
        hidden = [r for r in views[spec.id].runs if r.style == "hidden"]
        # the views stage drew no hidden lines; only the key's are added, the rest as they were
        assert not [r for r in geom.runs if r.style == "hidden"]
        assert views[spec.id].runs[: len(geom.runs)] == geom.runs
        assert len(views[spec.id].runs) == len(geom.runs) + len(hidden)
        if spec.kind == "isometric":
            assert hidden == []
        else:
            assert len(hidden) == 4 and {r.source.body for r in hidden} == {1}, spec.name
    # the leader ends at the middle of one of the key's dashed lines in the front
    assert any(_on(r.primitive, key.at) for r in views[front.id].runs if r.style == "hidden")
    dashed = [g for g in d.sheet.geometry if g.style == "hidden"]
    assert len(dashed) == 12
    assert {g.src.view for g in dashed} == {s.id for s in plan.views if s.kind != "isometric"}
    assert [b.item for b in annotations(d, D.Balloon)] == ["1", "2"]
    assert not [c for c in d.checks if c.code == "ASM.balloons"]
    assert not [w for w in run.orchestrated.planned.detail.warnings if "no balloon" in w]
    # the dashed lines are written on the hidden layer and kept through an edit
    import dxf_reader

    dxf = io.BytesIO()
    write_dxf(d, dxf)
    assert len([e for e in dxf_reader.read(dxf.getvalue()).entities if e.layer == "HIDDEN"]) == 12
    moved, _checks = edit.move_balloon(d, "2", 12.0, 12.0)
    assert [g for g in moved.sheet.geometry if g.style == "hidden"] == dashed
    assert [b.item for b in annotations(moved, D.Balloon)] == ["1", "2"]


def test_a_hidden_line_under_a_line_the_view_draws_is_left_out():
    # the key's bottom edge lies under the block's own in the front and the right views
    run = hidden_inside("flush")
    views = {s.name: g for s, g in run.orchestrated.views}
    hidden = {name: [r for r in g.runs if r.style == "hidden"] for name, g in views.items()}
    assert {name: len(runs) for name, runs in hidden.items()} == {
        "front": 3,
        "top": 4,
        "right": 3,
        "isometric": 0,
    }
    for name in ("front", "right"):
        assert all(max(r.primitive.p0[1], r.primitive.p1[1]) > 1e-6 for r in hidden[name])
    assert {b.item for b in run.plan[0].balloons} == {"1", "2"}


def test_an_assembly_with_no_part_hidden_draws_no_hidden_lines():
    run = hidden_inside("beside")
    assert {b.item for b in run.plan[0].balloons} == {"1", "2"}
    assert run.orchestrated.views == run.views
    assert not [g for g in run.drawing.sheet.geometry if g.style == "hidden"]
    assert drawn().orchestrated.views == drawn().views  # o16, whose parts all show


# --------------------------------------------------------------------------- a parts list on more sheets


@functools.cache
def long_list(lines: int = 70, sheets: int | None = None):
    """A synthetic assembly of ``lines`` small plates, a parts list line each, drawn on
    A sheets: too long a list for the first, so it goes on to more (at most ``sheets``
    in all, by default the limit's)."""
    from drawing_parts import MM, box

    parts = [
        (
            str(k + 1),
            f"plate{k + 1:03d}",
            box(20 * MM, 10 * MM, 5 * MM),
            ((k % 8) * 25 * MM, (k // 8) * 15 * MM, 0),
        )
        for k in range(lines)
    ]
    limits = DrawingLimits(bodies=256) if sheets is None else DrawingLimits(bodies=256, sheets=sheets)
    return pipeline.run(
        None,
        settings=_settings(),
        fields=FIELDS,
        options=T.DrawingOptions(sheet="A"),
        stages={"source": _synthetic_assembly(parts)},
        limits=limits,
    )


def _title(sheet) -> dict:
    return dict(next(a for a in sheet.annotations if isinstance(a, D.TitleBlock)).fields)


def _lists(sheet):
    return [a for a in sheet.annotations if isinstance(a, D.PartsList)]


def test_a_parts_list_too_long_for_its_sheet_goes_on_to_more_sheets():
    from solidseas.drawing.layout import partslist as PL

    d = long_list().drawing
    sheets = D.sheets_of(d.sheet)
    assert len(sheets) == 3 and sheets[0] is d.sheet
    assert [_title(s)["sheet"] for s in sheets] == ["1 OF 3", "2 OF 3", "3 OF 3"]
    assert {(s.name, s.width, s.height, s.scale) for s in sheets} == {("A", 279.4, 215.9, d.sheet.scale)}
    # every line of the list once, in order, across the sheets; each column with its headings
    rows = [r for s in sheets for pl in _lists(s) for r in pl.rows]
    assert [r[0] for r in rows] == [str(n) for n in range(1, 71)]
    assert all(pl.columns == PL.COLUMNS for s in sheets for pl in _lists(s))
    assert 0 < sum(len(pl.rows) for pl in _lists(sheets[0])) < 70
    # the sheets after the first: the list, the title block, the border and the stamps; no views
    for s in sheets[1:]:
        assert s.views == () and s.geometry == () and s.continuation == ()
        assert not [a for a in s.annotations if isinstance(a, (D.Balloon, D.Dimension, D.NotesBlock))]
        assert {type(a) for a in s.annotations} >= {D.TitleBlock, D.PartsList, D.Border, D.Stamp, D.PlotStamp}
        assert not [p for p in s.painted if p.owner == "revisions"], "the revision block is on the first"
        tb = next(a for a in s.annotations if isinstance(a, D.TitleBlock))
        for pl in _lists(s):  # standing on the title block, inside the border
            assert pl.at[1] == pytest.approx(tb.at[1] + tb.height)
            assert pl.at[1] + pl.height <= s.height - 9.0
    # the sheets after the first carry the continuation block: the drawing and the sheet
    first = _title(sheets[0])
    for s in sheets[1:]:
        fields = _title(s)
        assert set(fields) == {"size", "cage", "number", "revision", "scale", "sheet"}
        assert {k: fields[k] for k in ("size", "number", "revision", "scale")} == {
            k: first[k] for k in ("size", "number", "revision", "scale")
        }
    # the checks read the list across its sheets: every balloon names an item of it
    found = [
        c for c in d.checks if c.code in ("ASM.parts", "ASM.balloons", "R8.sheet") and c.level == "error"
    ]
    assert not found, found
    assert sum(1 for s in sheets for a in s.annotations if isinstance(a, D.Balloon)) == 70


def test_the_sheets_after_the_first_are_filled_and_the_last_balanced():
    from solidseas.drawing.layout import partslist as PL

    h = 3.5
    rows = tuple((str(n), f"P-{n:03d}", f"P-{n:03d}", "PLATE", "1") for n in range(1, 61))
    # held to one sheet, as before: three columns, each taller than its share
    one = PL.shape(rows, h, 178.0, 200.0, 800.0)
    assert (one.columns, one.per_column, one.lines) == (3, 20, 60)
    # with more sheets: the columns as tall as their share, the rest left for the next sheet
    fit = int(200.0 * PL.PARTS_SHARE // PL.row_height(h)) - 1
    many = PL.shape(rows, h, 178.0, 200.0, 800.0, more=True)
    assert (many.columns, many.per_column, many.lines) == (3, fit, 3 * fit)
    assert many.height <= 200.0 * PL.PARTS_SHARE
    # a list that fits is shaped the same either way
    assert PL.shape(rows[:20], h, 178.0, 200.0, 800.0, more=True) == PL.shape(
        rows[:20], h, 178.0, 200.0, 800.0
    )
    # a sheet of its own: columns as tall as the field and as many as the width holds
    tall = int(150.0 // PL.row_height(h)) - 1
    full = PL.continued(100, h, 178.0, 150.0, 400.0)
    assert (full.columns, full.per_column, full.lines) == (2, tall, 2 * tall)
    assert PL.continued(15, h, 178.0, 150.0, 400.0) == PL.Shape(1, 15, 178.0, 16 * PL.row_height(h), 15)
    balanced = PL.continued(tall + 3, h, 178.0, 150.0, 400.0)
    assert (balanced.columns, balanced.per_column) == (2, -(-(tall + 3) // 2))
    last = PL.continued(100, h, 178.0, 150.0, 400.0, last=True)
    assert last.lines == 100 and last.per_column > tall, "the last sheet a drawing may have takes the rest"
    assert PL.continued(0, h, 178.0, 150.0, 400.0) == PL.Shape()


def test_the_sheets_after_the_first_carry_the_continuation_block():
    from solidseas.drawing.layout import titleblock

    d = long_list().drawing
    sheets = D.sheets_of(d.sheet)
    full = next(a for a in d.sheet.annotations if isinstance(a, D.TitleBlock))
    for s in sheets[1:]:
        tb = next(a for a in s.annotations if isinstance(a, D.TitleBlock))
        # in the first's corner and as wide, as tall as its rows naming the drawing and the sheet
        assert tb.at == pytest.approx(full.at) and tb.width == pytest.approx(full.width)
        assert tb.height == pytest.approx(full.height * titleblock.CONTINUATION_SHARE)
        assert tb.height < full.height / 3
        for pl in _lists(s):  # the list stands on it
            assert pl.at[1] == pytest.approx(tb.at[1] + tb.height)
    pdf = io.BytesIO()
    write_pdf(d, pdf)
    first = [r.text for r in PdfDocument(pdf.getvalue(), page_index=0).text_runs()]
    second = [r.text for r in PdfDocument(pdf.getvalue(), page_index=1).text_runs()]
    for label in ("SIZE", "CAGE", "DWG NO", "REV", "SCALE", "SHEET"):
        assert label in first and label in second, label
    number = dict(full.fields)["number"]
    assert {number, "2 OF 3"} <= set(second) and "1 OF 3" in first
    for label in ("TITLE", "MATERIAL", "FINISH", "STATUS", "CALC WT", "DRAWN", "DO NOT SCALE DRAWING"):
        assert label in first and label not in second, label
    # a sheet whose block names another drawing, or none, is reported
    one, other = sheets[1], sheets[2]
    changed = [
        replace(a, fields=tuple((k, "SS-9" if k == "number" else v) for k, v in a.fields))
        if isinstance(a, D.TitleBlock)
        else a
        for a in other.annotations
    ]
    wrong = replace(d, sheet=replace(d.sheet, continuation=(one, replace(other, annotations=tuple(changed)))))
    said = [c.message for c in run_checks(wrong) if c.code == "R8.sheet"]
    assert said == [f"sheet 3's title block gives the drawing number SS-9; the first sheet's gives {number}"]
    assert not [c for c in run_checks(d) if c.code == "R8.sheet"]


def test_a_drawing_held_to_one_sheet_stands_its_list_taller():
    d = long_list(sheets=1).drawing
    assert D.sheets_of(d.sheet) == (d.sheet,) and _title(d.sheet)["sheet"] == "1 OF 1"
    assert [r[0] for pl in _lists(d.sheet) for r in pl.rows] == [str(n) for n in range(1, 71)]
    # at the most sheets a drawing may have, the last takes every line left
    two = long_list(sheets=2).drawing
    assert [_title(s)["sheet"] for s in D.sheets_of(two.sheet)] == ["1 OF 2", "2 OF 2"]
    rows = [r[0] for s in D.sheets_of(two.sheet) for pl in _lists(s) for r in pl.rows]
    assert rows == [str(n) for n in range(1, 71)]


def test_a_drawing_of_several_sheets_is_saved_and_read_back():
    d = long_list().drawing
    data = document.dumps(d)
    back, problems = document.loads(data)
    assert problems == [] and len(D.sheets_of(back.sheet)) == 3
    assert document.dumps(back) == data
    # a one-sheet drawing's compact sheet is as before: eight values, no continuation
    one = document.loads(document.dumps(drawn().drawing))[0]
    assert len(D.to_compact(one.sheet)["sheet"]["v"]) == 8 and one.sheet.continuation == ()
    many = D.to_compact(d.sheet)
    assert len(many["sheet"]["v"]) == 9 and len(many["sheet"]["v"][8]) == 2
    # a sheet that continues another has none of its own; a drawing has at most the limit
    with pytest.raises(InvalidArgumentError):
        D.from_compact(D.to_compact(replace(d.sheet, continuation=(d.sheet,))))
    few, problems = document.loads(data, limits=DrawingLimits(sheets=2))
    assert few.sheet is None and "more than 2 sheets" in " ".join(problems)
    assert document.dumps(few) == data, "the sheet is kept as it is"


def test_a_drawing_of_several_sheets_writes_a_page_each():
    import dxf_reader
    from solidseas.drawing import svg
    from solidseas.drawing.dxf import SHEET_GAP, dxf_bytes
    from solidseas.model import drawing_summary_data

    d = long_list().drawing
    sheets = D.sheets_of(d.sheet)
    pdf = io.BytesIO()
    write_pdf(d, pdf)
    assert PdfDocument(pdf.getvalue()).page_count == 3
    for n in range(3):
        page = PdfDocument(pdf.getvalue(), page_index=n)
        words = [r.text for r in page.text_runs()]
        assert f"{n + 1} OF 3" in words and "ITEM" in words
        assert {r[0] for pl in _lists(sheets[n]) for r in pl.rows} <= set(words)
        assert page.media_box()[2] == pytest.approx(279.4 * 72 / 25.4, abs=0.01)
    # the first page is what a drawing of the first sheet alone writes
    alone = io.BytesIO()
    write_pdf(replace(d.sheet, continuation=()), alone)
    assert PdfDocument(alone.getvalue()).content() == PdfDocument(pdf.getvalue(), page_index=0).content()
    # the DXF: the sheets side by side in model space, every part number on its sheet once
    doc = dxf_reader.read(dxf_bytes(d))
    handles = doc.handles()
    assert len(handles) == len(set(handles))
    texts = [e for e in doc.entities if e.type in ("TEXT", "MTEXT")]
    numbered = [e for e in texts if e.text.endswith(" OF 3")]
    assert [e.text for e in numbered] == ["1 OF 3", "2 OF 3", "3 OF 3"]
    for n in range(1, 71):
        assert [e.text for e in texts].count(f"PLATE{n:03d}") == 2, n  # its part number and drawing's
    k = d.sheet.scale[1] / d.sheet.scale[0]  # model millimetres a sheet millimetre
    assert float(doc.var("$EXTMAX")) == pytest.approx((3 * 279.4 + 2 * SHEET_GAP) * k, abs=1e-6)
    stamps = [e for e in texts if e.text == "PRELIMINARY - NOT FOR MANUFACTURE"]
    xs = [e.point(10)[0] for e in stamps]  # the stamp stands in the same place on every sheet
    assert len(xs) == 3
    assert xs[1] - xs[0] == pytest.approx((279.4 + SHEET_GAP) * k, abs=1e-3)
    assert xs[2] - xs[1] == pytest.approx((279.4 + SHEET_GAP) * k, abs=1e-3)
    # an SVG a sheet
    svgs = svg.to_svgs(d.sheet)
    assert len(svgs) == 3 and svgs[0] == svg.to_svg(d.sheet) and "3 OF 3" in svgs[2]
    # the summary counts every line and the sheets
    counts = drawing_summary_data(d)["counts"]
    assert counts["items"] == 70 and counts["sheets"] == 3
    assert drawing_summary_data(drawn().drawing)["counts"]["sheets"] == 1


def test_an_edit_lays_the_sheets_out_again():
    d = long_list().drawing
    moved, _checks = edit.move_balloon(d, "1", 30.0, 30.0)
    sheets = D.sheets_of(moved.sheet)
    assert [_title(s)["sheet"] for s in sheets] == ["1 OF 3", "2 OF 3", "3 OF 3"]
    assert sheets[1:] == D.sheets_of(d.sheet)[1:], "the sheets after the first are as they were"
