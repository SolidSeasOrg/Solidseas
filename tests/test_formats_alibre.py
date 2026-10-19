"""Alibre Design parts and assemblies (``docs/formats/alibre.md``, ``docs/API.md``
3.20.8), on synthetic files written by ``tests/alibre_writers.py``: the head, the stored
thumbnail, both sources of a part's triangles, exports, assemblies whose components
are found by GUID, and every surface (listing, jobs, command line, REST)."""

import datetime
import json
import os
import struct

import pytest

import alibre_writers as A
import sab_writers as W
from builders import build_cfb
from jsonschema_subset import validate
from serve_support import Running
from solidseas import cli, export, jobs, model, scan
from solidseas.errors import (
    FormatNotSupportedError,
    NothingToExportError,
    UnknownFormatError,
)
from solidseas.formats import is_model, open_any, open_model
from solidseas.formats._source import preview_png
from solidseas.formats.alibre.design import base_axis

pytestmark = pytest.mark.usefixtures("outbound_guard")
UTC = datetime.UTC


@pytest.fixture
def folder(tmp_path):
    """A part saved under another name than the assembly stores, and the assembly."""
    base = tmp_path / "project"
    base.mkdir()
    (base / "block.AD_PRT").write_bytes(A.part())
    placed = [
        A.Placed(A.CUBE_GUID),
        A.Placed(
            A.CUBE_GUID,
            origin=(5.0, 0.0, 0.0),
            axis1=A.QUARTER_Z[0],
            axis2=A.QUARTER_Z[1],
            axis3=A.QUARTER_Z[2],
        ),
        A.Placed(A.CUBE_GUID, share_placement_with=0),
    ]
    (base / "pair.AD_ASM").write_bytes(A.assembly(placed))
    return base


# --------------------------------------------------------------------------- a part's head
def test_a_part_and_its_head():
    with open_model(A.part(), name="cube.AD_PRT") as doc:
        assert (doc.format, doc.format_name, doc.variant, doc.doc_type, doc.kind) == (
            "alibre",
            "Alibre Design",
            "part",
            "part",
            "brep",
        )
        assert doc.units == {"length": "cm", "scale_m": 0.01, "source": "file"}
        assert doc.application == {"name": "Alibre Design", "version": "9.1.22"}
        assert doc.active_configuration == "Config<0>"
        assert doc.color == pytest.approx((200 / 255, 100 / 255, 50 / 255, 1.0))
        f = doc.fields
        assert (f.title, f.author, f.comments, f.last_saved_by) == (
            "Test cube",
            "Test Author",
            "A cube for the tests",
            "Test Saver",
        )
        assert f.created_utc == datetime.datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        assert f.last_saved_utc == datetime.datetime(2026, 1, 2, 17, 30, tzinfo=UTC)  # 12:30 EST
        props = {p.name: p for p in doc.properties}
        assert set(props) == {
            "number",
            "name",
            "Last_Modification_Time",
            "Creation_Time",
            "Last_Modification_Author",
            "description",
            "Creation_Author",
            "stepFileVersion",
            "Weight",
        }
        assert props["Weight"].type == "number" and props["Weight"].value == 7
        assert props["number"].type == "text" and props["number"].value == "TC-1"
        assert all(p.scope == "file" for p in doc.properties)
        assert doc.counts()["faces"] == 6 and doc.counts()["bodies"] == 1
        assert doc.identity.guid == A.CUBE_GUID and doc.identity.version == 1
        assert doc.warnings == []


def test_the_stored_thumbnail_is_a_bitmap_passed_on_as_png():
    with open_model(A.part(), name="cube.AD_PRT") as doc:
        pv = doc.preview()
        assert (pv.mime, pv.width, pv.height, pv.stream) == ("image/bmp", 8, 8, "PROP_DATA")
        png, w, h, stream = preview_png(pv, doc.limits)
    assert png.startswith(b"\x89PNG") and (w, h, stream) == (8, 8, "PROP_DATA")
    with open_model(A.part(snapshot=b""), name="cube.AD_PRT") as doc:
        assert doc.preview() is None
        assert doc.summary()["preview"]["renderable"] is True


def test_the_display_mesh_and_the_bodies():
    with open_model(A.part(), name="cube.AD_PRT") as doc:
        display = doc.scene(prefer="display")
        (obj,) = display.objects
        assert obj.source == "display_mesh" and obj.n_triangles == 12 and obj.normals is not None
        assert obj.color == doc.color and obj.node == "1"
        assert obj.measures()["volume_m3"] == pytest.approx(1e-6, rel=1e-6)
        bodies = doc.scene(prefer="bodies")
        (obj,) = bodies.objects
        assert obj.source == "bodies" and bodies.counts["faces_done"] == 6
        (ref,) = doc.bodies()
        assert ref.body_type == "solid" and ref.color == doc.color


def test_export_prefers_the_bodies_and_falls_back_to_the_display_mesh():
    with open_model(A.part(), name="cube.AD_PRT") as doc:
        pm = export.print_model(doc)
    assert pm.closed and pm.objects[0].source == "bodies" and pm.source_format == "alibre"
    assert pm.measures()["volume_m3"] == pytest.approx(1e-6, rel=1e-9)
    with open_model(A.part(with_sab=False), name="cube.AD_PRT") as doc:
        assert doc.bodies() == [] and doc.counts()["bodies"] == 0
        pm = export.print_model(doc)
    assert pm.objects[0].source == "display_mesh"
    assert "display_mesh_fallback" in {w.code for w in pm.objects[0].warnings}


def test_an_unverified_acis_version_uses_the_display_mesh():
    with open_model(A.part(sab_version=700), name="cube.AD_PRT") as doc:
        scene = doc.scene(prefer="bodies")
    assert [o.source for o in scene.objects] == ["display_mesh"]
    assert "acis_version_unverified" in {w.code for w in scene.warnings}


def test_units_come_from_the_body_and_a_disagreement_is_warned():
    with open_model(A.part(mesh=A.cube_mesh(1.0, units="inches")), name="cube.AD_PRT") as doc:
        assert doc.units["length"] == "cm"
        assert [w.code for w in doc.warnings] == ["units_disagree"]
    with open_model(A.part(with_sab=False, mesh=A.cube_mesh(1.0, units="inches")), name="c.AD_PRT") as doc:
        assert doc.units == {"length": "in", "scale_m": 0.0254, "source": "file"}
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(0.0254**3, rel=1e-6)


def test_a_cylinder_part_from_both_sources():
    data = A.part(solid=W.cylinder(1.0, 2.0), mesh=A.cylinder_mesh(1.0, 2.0))
    with open_model(data, name="cyl.AD_PRT") as doc:
        assert doc.scene(prefer="display").objects[0].n_triangles == 96
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(2 * 3.141592653589793e-6, rel=2e-3)


def test_a_sheet_metal_part_is_read_as_a_part():
    with open_model(A.part(), name="sheet.AD_SMP") as doc:
        assert (doc.variant, doc.doc_type) == ("sheet_metal", "part")
        assert "variant_unverified" in {w.code for w in doc.warnings}


def test_a_compound_file_of_another_program_is_not_alibre():
    with pytest.raises(UnknownFormatError):
        open_model(build_cfb({"Contents/Config-0": b"x"}, A.ZERO_CLSID), name="other.AD_PRT")
    other_schema = A.p21(["#1=DESIGNPART();"], schema="('AUTOMOTIVE_DESIGN')")
    with pytest.raises(UnknownFormatError):
        open_model(A.part(streams={"STEP_DATA": other_schema}), name="x.AD_PRT")


def test_a_document_that_is_neither_part_nor_assembly_is_refused():
    drawing = A.p21(["#1=SCHEMAVERSION('a','b');", "#2=DESIGNDRAWING();"])
    data = A.part(with_sab=False, with_mesh=False, streams={"STEP_DATA": drawing})
    with pytest.raises(FormatNotSupportedError) as err:
        open_model(data, name="x.AD_PRT")
    assert err.value.detail == {"rule": "unsupported_variant", "value": "alibre"}


def test_open_any_reads_alibre_files():
    with open_any(A.part(), name="cube.AD_PRT") as doc:
        assert is_model(doc) and doc.format == "alibre"


def test_the_summary_is_valid_json_of_its_kind():
    with open_model(A.part(), name="cube.AD_PRT") as doc:
        data = model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
    env = model.envelope("model_summary", data)
    assert validate(json.loads(json.dumps(env)), model.envelope_schema("model_summary"), strict=True) == []
    assert data["preview"]["available"] and data["preview"]["mime"] == "image/bmp"
    assert data["tree"]["nodes"][0]["kind"] == "object" and data["references"] == []


# --------------------------------------------------------------------------- assemblies
def test_an_assembly_places_its_parts_found_by_guid(folder):
    with open_model(folder / "pair.AD_ASM") as doc:
        assert (doc.variant, doc.doc_type) == ("assembly", "assembly")
        assert doc.units == {"length": "cm", "scale_m": 0.01, "source": "assumed"}
        assert doc.counts()["components"] == 3 and doc.counts()["references"] == 1
        nodes = doc.tree().nodes
        assert [(n.id, n.parent, n.kind, n.name, n.file) for n in nodes] == [
            ("1", None, "assembly", "pair", None),
            ("2", "1", "component", "block", A.CUBE_GUID),
            ("3", "1", "component", "block", A.CUBE_GUID),
            ("4", "1", "component", "block", A.CUBE_GUID),
        ]
        assert nodes[2].placement.translation_m == pytest.approx((0.05, 0.0, 0.0))
        (ref,) = doc.references()
        assert (ref.key, ref.kind, ref.name) == (A.CUBE_GUID, "component", "cube")
        assert ref.stored == "C:/Repository/Parts/cube"
        assert ref.resolution == {
            "status": "found",
            "path": "block.AD_PRT",
            "found_by": "document_guid",
            "version": "1",
        }
        scene = doc.scene(prefer="display")
        assert len(scene.objects) == 1 and [it.instance for it in scene.items] == ["2", "3", "4"]
        turned = scene.items[1].placement
        assert [x for row in turned.rotation for x in row] == pytest.approx([0, -1, 0, 1, 0, 0, 0, 0, 1])
        assert scene.items[2].placement == scene.items[0].placement
        assert "placement_unit_assumed" in {w.code for w in doc.warnings}
        pm = export.print_model(doc)
    assert pm.closed and pm.counts["items"] == 3 and pm.doc_type == "assembly"
    assert pm.measures()["volume_m3"] == pytest.approx(3e-6, rel=1e-9)


def test_base_axis_completes_the_axes():
    u1, u2, u3 = base_axis((1.0, 1.0, 0.0), None, (0.0, 0.0, 2.0))
    s = 2**-0.5
    assert u1 == pytest.approx((s, s, 0)) and u2 == pytest.approx((-s, s, 0)) and u3 == (0.0, 0.0, 1.0)
    assert base_axis(None, None, None) == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _assembly_with(tmp_path, files: dict[str, bytes], placed, **kw):
    base = tmp_path / "asm"
    base.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (base / "top.AD_ASM").write_bytes(A.assembly(placed, **kw))
    return base / "top.AD_ASM"


def test_a_component_whose_identity_is_unreadable_is_found_by_its_name(tmp_path):
    damaged = A.part(streams={"VERSION": b"\x00\x05junk!"})
    asm = _assembly_with(tmp_path, {"cube.AD_PRT": damaged}, [A.Placed(A.CUBE_GUID)])
    with open_model(asm) as doc:
        (ref,) = doc.references()
        assert ref.resolution["found_by"] == "name" and ref.resolution["status"] == "found"
        assert "component_found_by_name" in {w.code for w in doc.warnings}


def test_a_file_of_the_same_name_but_another_document_is_not_used(tmp_path):
    other = A.part(guid="12345678-1234-1234-1234-123456789abc")
    asm = _assembly_with(tmp_path, {"cube.AD_PRT": other}, [A.Placed(A.CUBE_GUID)])
    with open_model(asm) as doc:
        assert doc.references()[0].resolution["status"] == "not_found"
        scene = doc.scene()
        assert scene.items == () and "component_not_found" in {w.code for w in scene.warnings}
        with pytest.raises(NothingToExportError):
            export.print_model(doc)


def test_several_copies_and_versions(tmp_path):
    files = {"near.AD_PRT": A.part(version=2), "sub/far.AD_PRT": A.part(version=1)}
    asm = _assembly_with(tmp_path, files, [A.Placed(A.CUBE_GUID, version=1)])
    with open_model(asm) as doc:
        (ref,) = doc.references()
        assert ref.resolution["path"] == "near.AD_PRT" and ref.resolution["version"] == "2"
        assert {"component_ambiguous", "component_newer"} <= {w.code for w in doc.warnings}
    asm = _assembly_with(
        tmp_path / "b", {"sub/old.AD_PRT": A.part(version=1)}, [A.Placed(A.CUBE_GUID, version=4)]
    )
    with open_model(asm) as doc:
        assert doc.references()[0].resolution["path"] == "sub/old.AD_PRT"
        assert "component_older" in {w.code for w in doc.warnings}


def test_components_keep_the_rules_the_assembly_was_opened_with(tmp_path):
    """A component file with a second name outside the folder is no candidate when the
    assembly refuses hard links (as the REST service opens it), and a component larger
    than ``max_file_bytes`` is not read."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "cube.AD_PRT").write_bytes(A.part())
    asm = _assembly_with(tmp_path, {}, [A.Placed(A.CUBE_GUID), A.Placed(A.CUBE_GUID, origin=(2.0, 0.0, 0.0))])
    os.link(outside / "cube.AD_PRT", asm.parent / "cube.AD_PRT")
    with open_model(asm, within=asm.parent) as doc:  # not asked: found and placed as before
        assert doc.references()[0].resolution["status"] == "found"
        assert len(doc.scene().items) == 2
    with open_model(asm, within=asm.parent, refuse_hard_links=True) as doc:
        assert doc.references()[0].resolution["status"] == "not_found"
        scene = doc.scene()
        assert scene.items == () and "component_not_found" in {w.code for w in scene.warnings}
    (asm.parent / "cube.AD_PRT").unlink()
    (asm.parent / "cube.AD_PRT").write_bytes(A.part())
    size = os.path.getsize(asm.parent / "cube.AD_PRT")
    with open_model(asm, max_file_bytes=max(os.path.getsize(asm), size - 1)) as doc:
        assert doc.scene().items == ()  # found, but larger than the assembly's caller allows
    with open_model(asm, max_file_bytes=max(os.path.getsize(asm), size)) as doc:
        assert len(doc.scene().items) == 2


def test_a_stored_path_is_never_opened_but_a_root_is_searched(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "cube.AD_PRT").write_bytes(A.part())
    stored = str(outside / "cube").replace("\\", "/")
    asm = _assembly_with(tmp_path, {}, [A.Placed(A.CUBE_GUID, stored_path=stored)])
    with open_model(asm) as doc:
        assert doc.references()[0].resolution["status"] == "not_found"
        assert doc.scene().items == ()
        found = doc.scene(roots=[str(outside)])
        assert len(found.items) == 1 and found.objects[0].source == "bodies"


def test_a_sub_assembly_is_placed_and_a_cycle_refused(tmp_path):
    sub = A.assembly([A.Placed(A.CUBE_GUID, origin=(1.0, 0.0, 0.0))], guid=A.SUB_GUID)
    files = {"cube.AD_PRT": A.part(), "sub.AD_ASM": sub}
    placed = [A.Placed(A.SUB_GUID, stored_path="C:/R/sub", origin=(10.0, 0.0, 0.0)), A.Placed(A.ASM_GUID)]
    asm = _assembly_with(tmp_path, files, placed)
    with open_model(asm) as doc:
        scene = doc.scene(prefer="display")
    assert len(scene.items) == 1 and scene.items[0].instance == "2"
    assert scene.items[0].placement.translation_m == pytest.approx((0.11, 0.0, 0.0))
    assert [(s.instance, s.reason) for s in scene.skipped] == [("3", "cycle")]
    assert scene.counts["components"] == 2


def test_constituents_that_disagree_are_warned(tmp_path):
    lying = A.constituents([A.Placed("12345678-1234-1234-1234-123456789abc")])
    asm = _assembly_with(
        tmp_path, {"cube.AD_PRT": A.part()}, [A.Placed(A.CUBE_GUID)], streams={"CONSTITUENTS": lying}
    )
    with open_model(asm) as doc:
        doc.references()
        assert "constituents_disagree" in {w.code for w in doc.warnings}


def test_an_assembly_opened_from_bytes_has_no_folder_to_search():
    with open_model(A.assembly([A.Placed(A.CUBE_GUID)]), name="x.AD_ASM") as doc:
        assert doc.references()[0].resolution["status"] == "not_found"
        assert doc.preview().mime == "image/bmp"


# --------------------------------------------------------------------------- every surface
def test_a_listing_reads_alibre_files_in_workers(folder):
    entries = {e["path"]: e for e in scan(folder, formats="all") if e["type"] == "file"}
    for name in ("block.AD_PRT", "pair.AD_ASM"):
        e = entries[name]
        assert e["status"] == "ok" and e["model"]["format"] == "alibre" and e["model"]["readable"]
    assert entries["block.AD_PRT"]["model"]["counts"]["faces"] == 6
    assert entries["pair.AD_ASM"]["model"]["counts"]["components"] == 3


def test_an_alibre_file_named_as_a_solidworks_part_is_listed_as_one(tmp_path):
    """A compound file is a SOLIDWORKS container to open_document, so an Alibre part
    renamed .SLDPRT is listed as the SOLIDWORKS document its name says, read where
    SOLIDWORKS documents are read (docs/API.md 3.6), not as an Alibre file."""
    (tmp_path / "renamed.SLDPRT").write_bytes(A.part())
    (entry,) = [e for e in scan(tmp_path, formats="all") if e["type"] == "file"]
    assert entry["status"] == "ok" and (entry.get("model") or {}).get("format") is None


def test_the_preview_job_sends_the_stored_thumbnail_as_png(folder):
    jobs.configure({"roots": [str(folder)]})
    try:
        base = {"path": str(folder / "block.AD_PRT"), "within": str(folder), "name": "block.AD_PRT"}
        meta, png = jobs.model_preview(base)
        assert meta["source"] == "stored" and png.startswith(b"\x89PNG")
        assert (meta["width"], meta["height"]) == (8, 8)
        meta, png = jobs.model_preview({**base, "render": "always", "width": 64, "height": 48})
        assert meta["source"] == "rendered" and (meta["width"], meta["height"]) == (64, 48)
    finally:
        jobs.configure({})


def _run(capsys, *argv):
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_the_command_line_reads_and_exports_alibre_files(folder, capsys, tmp_path):
    code, env = _run(capsys, "info", str(folder / "block.AD_PRT"))
    assert code == 0 and env["kind"] == "model_summary" and env["data"]["format"] == "alibre"
    out = tmp_path / "out"
    out.mkdir()
    code, env = _run(
        capsys, "export", str(folder / "pair.AD_ASM"), "--format", "3mf", "-o", str(out / "pair.3mf")
    )
    assert code == 0 and env["data"]["source_format"] == "alibre"
    assert os.path.getsize(out / "pair.3mf") > 0


def test_python_the_command_line_and_rest_give_the_same_summary(folder, capsys):
    running = Running({"f": folder}, workers=1, formats=("solidworks", "alibre"))
    try:
        for name in ("block.AD_PRT", "pair.AD_ASM"):
            with open_model(folder / name) as doc:
                python = doc.summary(include=model.MODEL_SUMMARY_PARTS)
            _code, cli_env = _run(capsys, "info", str(folder / name))
            rest = running.get("document", root="f", path=name)
            assert rest.status == 200, name
            assert cli_env["data"] == python == rest.json()["data"], name
    finally:
        running.close()


def test_the_bitmap_writer_is_bottom_up():
    data = A.bmp(4, 2)
    assert data[:2] == b"BM" and struct.unpack_from("<ii", data, 18) == (4, 2)


def test_the_design_database_reader():
    from solidseas.formats.alibre._p21 import DERIVED, Enum, Part21, Ref, Typed
    from solidseas.formats.limits import Limits

    data = A.p21(
        [
            r"#1=FIRST('it''s','\X\E9t\X2\00E9\X0\','\X4\0001F600\X0\','\S\i','a\\b',.T.,$,*,#2,(1,2.5,-3.E2),SIZE(4));",
            "#2=(PART_A(1)PART_B('x'));",
            "/* a comment */ #3=WRAPPED('long\r\nline');",
        ]
    )
    p = Part21(data, Limits())
    assert p.schemas == ["ALIBRE_SCHEMA", "CONFIG_CONTROL_DESIGN"]
    assert p.ids_of_type("first") == [1] and p.type_of(3) == "WRAPPED"
    name, params = p.record(1)
    assert name == "FIRST"
    assert params[:5] == ("it's", "\u00e9t\u00e9", "\U0001f600", "\u00e9", "a\\b")
    assert params[5:] == (Enum("T"), None, DERIVED, Ref(2), (1, 2.5, -300.0), Typed("SIZE", (4,)))
    assert p.record(2) == ("", (Typed("PART_A", (1,)), Typed("PART_B", ("x",))))
    assert p.record(3)[1] == ("longline",)
