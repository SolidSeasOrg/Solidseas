"""Bills of materials (``docs/API.md`` section 3.16, ``docs/FORMAT.md`` 12.7).

Fixture o19 is a drawing of o16 that holds two BOM tables SOLIDWORKS itself made,
top-level only and indented, recorded cell by cell in ``ground_truth.json``
(when they were made, and again after the drawing was reopened). The first tests
build o16's BOM with :mod:`solidseas.bom` and compare it with those cells
exactly, through Python and the command line. Crafted assemblies
(``builders.TreeXml``) then cover what o16 does not have: a sub-assembly excluded
from the BOM, one used twice, two configurations of one part, documents stored
inside a sub-assembly, files that are missing or lack a configuration, a
sub-assembly whose components the top tree does not list, and every limit.
"""

import csv
import io
import json
import os
import shutil
from pathlib import Path

import pytest

from builders import TreeXml, assembly_with_tree, rebuild
from jsonschema_subset import validate
from solidseas import ConfigurationNotFoundError, InvalidArgumentError, Root, Roots, cli, model, open_document
from solidseas import bom as bom_mod
from solidseas.resolve import resolve_references
from support import FIXTURES, fixture_path, ground_truth, within

GT = ground_truth()
O16 = fixture_path("o16_asm_features.SLDASM")
O15 = fixture_path("o15_sub_asm.SLDASM")
O04 = fixture_path("o04_boxA_props.SLDPRT")
O06 = fixture_path("o06_boxA_props_mat_cfg.SLDPRT")
O02 = fixture_path("o02_boxA.SLDPRT")
SW_TYPES = {2: "top", 3: "indented"}


def _o19_tables() -> list[tuple[str, dict]]:
    o19 = GT["o19_drw_asm.SLDDRW"]
    tables = [("at creation", t) for t in o19["generation"]["bom_tables_at_creation"]]
    tables += [("after reopening", t) for t in o19["api"]["bom_tables"]]
    return tables


def _schema_ok(data: dict) -> None:
    errors = validate(data, model.KINDS["bom"].schema, strict=True)
    assert errors == [], errors[:5]
    assert model.to_json_data(data) == data
    model.dumps(model.envelope("bom", data))


def _run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


# --------------------------------------------------------------------------- SOLIDWORKS' own tables
def test_o19_holds_both_tables_twice():
    tables = _o19_tables()
    assert [(when, t["bom_type"]) for when, t in tables] == [
        ("at creation", 2),
        ("at creation", 3),
        ("after reopening", 2),
        ("after reopening", 3),
    ]
    for _when, t in tables:
        assert t["column_titles"] == list(bom_mod.COLUMNS) and t["header_rows"] == 1
        assert len(t["cells"]) == t["rows"] and all(len(r) == t["columns"] == 4 for r in t["cells"])


@pytest.mark.parametrize(("when", "table"), _o19_tables(), ids=lambda v: v if isinstance(v, str) else "")
def test_o16_bom_matches_solidworks_cell_by_cell(when, table):
    bom_type = SW_TYPES[table["bom_type"]]
    configuration = table["bom_configuration"] or None  # empty: the configuration the view shows
    with open_document(O16) as doc:
        bom = doc.bom(configuration, bom_type=bom_type)
        data = model.build_bom(doc, configuration=configuration, bom_type=bom_type)
    assert bom.configuration == "Default" and bom.complete
    assert bom.table() == table["cells"], when
    assert bom_mod.table_cells(data["type"], data["property_columns"], data["rows"]) == table["cells"]
    _schema_ok(data)
    # Each row stands for the document SOLIDWORKS names for it.
    for rd, row in zip(table["row_documents"][1:], bom.rows, strict=True):
        (document,) = rd["documents"]
        assert row.file_name == document.rsplit("/", 1)[-1]
        assert rd["item_number"] == row.item


def test_o16_bom_matches_solidworks_through_the_command_line(capsys, tmp_path):
    want = {SW_TYPES[t["bom_type"]]: t["cells"] for _w, t in _o19_tables()}
    for bom_type, cells in want.items():
        code, env = _run(capsys, "bom", str(O16), "--type", bom_type)
        assert code == 0 and env["kind"] == "bom" and env["source"] == {"file": str(O16)}
        assert not validate(env, model.envelope_schema("bom"), strict=True)
        data = env["data"]
        assert bom_mod.table_cells(data["type"], data["property_columns"], data["rows"]) == cells
        # The text table prints the same cells, in columns.
        assert cli.main(["bom", str(O16), "--type", bom_type]) == 0
        out = capsys.readouterr().out
        for row in cells[1:]:
            assert any(line.startswith(row[0] + " ") and row[1] in line for line in out.splitlines()), row
        # The CSV carries the same rows without the indentation.
        target = tmp_path / f"{bom_type}.csv"
        assert cli.main(["bom", str(O16), "--type", bom_type, "--format", "csv", "-o", str(target)]) == 0
        capsys.readouterr()
        raw = target.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
        rows = list(csv.reader(io.StringIO(raw[3:].decode("utf-8"), newline="")))
        assert [r[:4] for r in rows] == [[c[0], c[1].strip(), c[2], c[3]] for c in cells]


def test_quantities_add_up_to_the_tree_counts():
    """Per file, the indented BOM's total quantities are the tree's instances in the BOM,
    the parts-only BOM's quantities those of the parts, and the top-level BOM counts the
    top assembly's own instances in the BOM (as test_components_ground_truth checks the
    counts themselves against o19)."""
    for configuration in ("Default", "Lite"):
        with open_document(O16) as doc:
            tree = doc.components(configuration)
            boms = bom_mod.build_boms(doc, configuration)
        in_bom = {k: f.instances_in_bom for k, f in tree.files.items() if f.instances_in_bom}
        totals: dict[str, int] = {}
        for r in boms["indented"].rows:
            totals[r.file] = totals.get(r.file, 0) + r.total_quantity
        assert totals == in_bom, configuration
        parts = {r.file: r.quantity for r in boms["parts"].rows}
        assert parts == {k: v for k, v in in_bom.items() if tree.files[k].doc_type == "part"}
        top = sum(1 for n in tree.children if not n.suppressed and not n.excluded_from_bom)
        assert sum(r.quantity for r in boms["top"].rows) == top
        for b in boms.values():
            assert b.counts["instances"] == sum(len(r.instances) for r in b.rows)


def test_o16_parts_only_and_lite():
    with open_document(O16) as doc:
        parts = doc.bom(bom_type="parts")
        lite = bom_mod.build_boms(doc, "Lite")
    assert [(r.item, r.part_number, r.quantity) for r in parts.rows] == [
        ("1", "o02_boxA", 3),
        ("2", "o06_boxA_props_mat_cfg", 1),
        ("3", "o07_boxB_h31", 4),  # first met inside o15, depth first
        ("4", "o09_import_step", 1),
        ("5", "o17_деталь", 1),
        ("6", "Part12^o16_asm_features", 1),
    ]
    assert all(r.level == 0 and r.parent is None for r in parts.rows)
    assert "o15_sub_asm-1/o02_boxA-1" in parts.rows[0].instances
    # In Lite, o15 is suppressed: no row for it or its components, in any type.
    for b in lite.values():
        assert b.configuration == "Lite" and b.complete
        assert "o15_sub_asm" not in [r.part_number for r in b.rows]
    assert [r.item for r in lite["indented"].rows] == ["1", "2", "3", "4", "5", "6"]


def test_o16_rows_carry_files_configurations_and_properties():
    # Only the fixtures folder: on the PC that made the fixtures, the paths o16 stores
    # hold the parts too, and each would be read for its identity as well.
    with open_document(O16) as doc:
        bom = doc.bom(bom_type="indented", columns=["PartNo", "Part Number"], allow_outside_roots=False)
    by_item = {r.item: r for r in bom.rows}
    o06 = by_item["2"]
    assert o06.configuration == "OracleAlt" and o06.description == "Oracle test box"
    assert o06.values == ("ORACLE-PN-123", None) and o06.part_number_source == "document_name"
    assert {p.name for p in o06.properties} >= {"PartNo", "Description", "CfgOnly"}
    assert by_item["5"].values == (None, "o02_boxA")  # o09's STEP import wrote it; PART NUMBER ignores it
    assert by_item["4"].instances == ("o07_boxB_h31-2", "o07_boxB_h31-3", "o07_boxB_h31-4")
    assert (by_item["3.1"].level, by_item["3.1"].parent) == (1, "3")
    assert by_item["3.1"].instances == ("o15_sub_asm-1/o02_boxA-1",)
    virtual = by_item["7"]
    assert virtual.virtual and virtual.resolution == "embedded" and virtual.location is None
    assert virtual.nested == ("VirtualComp/Part12-sldprt",) and virtual.description == ""
    disk = by_item["1"]
    assert disk.location.root == "document" and disk.location.path == "o02_boxA.SLDPRT"
    assert disk.resolution in ("resolved", "moved") and disk.stored_path.endswith("o02_boxA.SLDPRT")
    # Six files on disk: resolution reads each one's identity, then each is read once.
    assert bom.counts["unread"] == 0 and bom.counts["files_opened"] == 12


def test_part_number_from_a_property_when_asked():
    with open_document(O16) as doc:
        bom = doc.bom(part_number_property="partno")  # names compare case-insensitively
        data = model.build_bom(doc, part_number_property="PartNo")
    rows = {r.item: (r.part_number, r.part_number_source) for r in bom.rows}
    assert rows["2"] == ("ORACLE-PN-123", "property")
    assert rows["1"] == ("o02_boxA", "document_name")  # o02 has none: the document name
    assert data["part_number_property"] == "PartNo" and data["rows"][1]["part_number"] == "ORACLE-PN-123"


def test_without_reading_properties_nothing_is_opened():
    with open_document(O16) as doc:
        bom = doc.bom(bom_type="indented", read_properties=False, columns=["PartNo"])
    assert bom.complete and bom.counts["files_opened"] == 0 and bom.resolution is None
    assert all(r.properties is None and r.description is None and r.values == (None,) for r in bom.rows)
    first = [c[:2] for c in bom.table()][1:4]
    assert first == [["1", "o02_boxA"], ["2", "o06_boxA_props_mat_cfg"], ["3", "o15_sub_asm"]]


def test_parts_and_drawings_have_no_bom():
    for name in ("o02_boxA.SLDPRT", "o19_drw_asm.SLDDRW"):
        with open_document(fixture_path(name)) as doc:
            assert doc.bom() is None and bom_mod.build_boms(doc) is None
            data = model.build_bom(doc, bom_type="parts", columns=["X"])
            _schema_ok(data)
            assert data["rows"] == [] and data["children_state"] == "none" and data["columns"][-1] == "X"
    with open_document(O02) as doc, pytest.raises(ConfigurationNotFoundError):
        doc.bom("Nope")
    with open_document(O16) as doc, pytest.raises(ConfigurationNotFoundError):
        doc.bom("Nope")


@pytest.mark.parametrize(
    ("kwargs", "parameter"),
    [
        ({"bom_type": "flat"}, "bom_type"),
        ({"columns": "Description"}, "columns"),
        ({"columns": ["A", "a"]}, "columns"),
        ({"columns": ["bad\nname"]}, "columns"),
        ({"columns": [""]}, "columns"),
        ({"columns": ["c"] * 65}, "columns"),
        ({"part_number_property": ""}, "part_number_property"),
        ({"read_properties": 1}, "read_properties"),
        ({"max_instances": 0}, "max_instances"),
        ({"max_depth": 65}, "max_depth"),
        ({"max_files": -1}, "max_files"),
        ({"max_seconds": -1}, "max_seconds"),
        ({"max_file_bytes": 0}, "max_file_bytes"),
        ({"resolution": object()}, "resolution"),
        # what goes to reference resolution is checked before any work, as it checks it
        ({"path_map": ["bad"]}, "path_map"),
        ({"path_map": "S:\\=/mnt"}, "path_map"),
        ({"path_map": 12345}, "path_map"),
        ({"path_map": [("S:\\", 5)]}, "path_map"),
        ({"allow_outside_roots": "nope"}, "allow_outside_roots"),
        ({"cache": {}}, "cache"),
        ({"roots": 5}, "roots"),
        ({"opener": "open"}, "opener"),
    ],
)
def test_arguments_are_checked(kwargs, parameter):
    for name in (O16, O02):  # refused before the document type is looked at
        with open_document(name) as doc, pytest.raises(InvalidArgumentError) as info:
            doc.bom(**kwargs)
        assert info.value.detail == {"parameter": parameter}


def test_a_bad_type_is_named_as_each_surface_names_it():
    with open_document(O16) as doc:
        for call, parameter in (
            (lambda: doc.bom(bom_type="flat"), "bom_type"),
            (lambda: bom_mod.build_boms(doc, bom_types=("top", "flat")), "bom_types"),
            (lambda: bom_mod.build_boms(doc, bom_types=()), "bom_types"),
            (lambda: model.build_bom(doc, bom_type="flat"), "type"),  # the CLI's and the service's name
        ):
            with pytest.raises(InvalidArgumentError) as info:
                call()
            assert info.value.detail == {"parameter": parameter}


def test_a_bad_resolution_argument_raises_instead_of_noting_every_row(tmp_path, capsys):
    """As ``references --resolve`` does: a malformed path map is a usage error (exit 2)
    and a root folder that does not exist is not found (exit 1), never a BOM whose rows
    all say their files could not be looked for (exit 4)."""
    nowhere = tmp_path / "no" / "such" / "folder"
    with open_document(O16) as doc:
        with pytest.raises(InvalidArgumentError) as info:
            doc.bom(path_map=["bad"])
        assert info.value.detail == {"parameter": "path_map"}
        with pytest.raises(FileNotFoundError):
            doc.bom(roots={"x": str(nowhere)})
        assert doc.bom(roots={"x": str(nowhere)}, read_properties=False).complete  # nothing searched
    for flags, code in ((["--path-map", "bad"], 2), (["--root", f"x={nowhere}"], 1)):
        bom_code, env = _run(capsys, "bom", str(O16), *flags)
        refs_code, refs = _run(capsys, "references", str(O16), "--resolve", *flags)
        assert bom_code == refs_code == code, flags
        assert env["error"]["code"] == refs["error"]["code"]


# --------------------------------------------------------------------------- crafted assemblies
def _job(tmp_path: Path, tree: TreeXml, members=None, files=(), name="top.SLDASM") -> Path:
    """The assembly ``tree`` in a folder of its own, with ``files`` (name, source path)
    beside it, where reference resolution finds them by name."""
    folder = tmp_path / "job"
    folder.mkdir(exist_ok=True)
    for file_name, src in files:
        if isinstance(src, bytes):
            (folder / file_name).write_bytes(src)
        else:
            shutil.copyfile(src, folder / file_name)
    asm = folder / name
    asm.write_bytes(assembly_with_tree(tree, members))
    return asm


def test_an_excluded_subassembly_takes_its_components_with_it(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", excluded=True)
    t.ref("m2", "p", 1, "m3")
    t.ref("m1", "p", 1, "m3")
    t.ref("m1", "sub", 2, "m2", suppressed=True)
    asm = _job(tmp_path, t, files=[("p.SLDPRT", O04), ("sub.SLDASM", O15)])
    with open_document(asm) as doc:
        boms = bom_mod.build_boms(doc)
    for b in boms.values():
        assert [(r.part_number, r.quantity) for r in b.rows] == [("p", 1)], b.type
        assert b.rows[0].instances == ("p-1",) and b.rows[0].description == "Oracle test box"


def test_quantities_are_per_parent_and_totals_multiply(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.file("4", "C:\\J\\q.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.model("m4", "4")
    t.ref("m1", "q", 1, "m4")
    t.ref("m1", "sub", 1, "m2")
    t.ref("m1", "sub", 2, "m2")
    t.ref("m2", "p", 1, "m3")
    t.ref("m2", "p", 2, "m3")
    t.ref("m2", "q", 1, "m4")
    t.ref("m2", "p", 3, "m3", excluded=True)
    asm = _job(tmp_path, t, files=[("p.SLDPRT", O02), ("q.SLDPRT", O02), ("sub.SLDASM", O15)])
    with open_document(asm) as doc:
        boms = bom_mod.build_boms(doc)
    rows = boms["indented"].rows
    ind = [(r.item, r.part_number, r.quantity, r.total_quantity, len(r.instances)) for r in rows]
    assert ind == [
        ("1", "q", 1, 1, 1),
        ("2", "sub", 2, 2, 2),
        ("2.1", "p", 2, 4, 4),  # two under each of the two instances
        ("2.2", "q", 1, 2, 2),
    ]
    assert [(r.part_number, r.quantity) for r in boms["parts"].rows] == [("q", 3), ("p", 4)]
    assert [(r.part_number, r.quantity) for r in boms["top"].rows] == [("q", 1), ("sub", 2)]
    assert boms["indented"].table()[3][1] == "  p"


def test_two_configurations_of_one_part_are_two_rows(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\o06.SLDPRT")
    t.top("m1")
    t.model("m2", "2", "Default")
    t.model("m3", "2", "OracleAlt")
    t.ref("m1", "o06", 1, "m2", config="Default")
    t.ref("m1", "o06", 2, "m3", config="OracleAlt")
    t.ref("m1", "o06", 3, "m2", config="Default")
    asm = _job(tmp_path, t, files=[("o06.SLDPRT", O06)])
    with open_document(asm) as doc:
        bom = doc.bom(columns=["CfgOnly"])
    assert [(r.item, r.configuration, r.quantity, r.values) for r in bom.rows] == [
        ("1", "Default", 2, (None,)),
        ("2", "OracleAlt", 1, ("ALT-VALUE",)),  # the configuration's own property
    ]
    assert bom.counts["files_opened"] == 2  # its identity read, then one read for both configurations


def _o06_with_configuration_description() -> bytes:
    """o06 whose configuration OracleAlt has its own Description, beside the file's."""
    from builders import fixture_streams

    s = fixture_streams(O06)
    (name,) = [n for n in s if n.startswith("docProps/Config-") and b"CfgOnly" in s[n]]
    xml = s[name]
    assert xml.count(b'name="CfgOnly"') == 2  # the property and its name in the dictionary
    xml = xml.replace(b'name="CfgOnly"', b'name="description"')
    return rebuild(O06, {name: xml})


def test_a_configurations_own_description_wins(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\o06.SLDPRT")
    t.top("m1")
    t.model("m2", "2", "Default")
    t.model("m3", "2", "OracleAlt")
    t.ref("m1", "o06", 1, "m2", config="Default")
    t.ref("m1", "o06", 2, "m3", config="OracleAlt")
    asm = _job(tmp_path, t, files=[("o06.SLDPRT", _o06_with_configuration_description())])
    with open_document(asm) as doc:
        bom = doc.bom()
    assert [r.description for r in bom.rows] == ["Oracle test box", "ALT-VALUE"]


def _virtual_assembly(tmp_path: Path) -> Path:
    """Documents stored inside: a virtual part of the top assembly, one it lost, an
    imported part it stores, and a virtual part stored inside a sub-assembly's file."""
    part = O04.read_bytes()
    sub = TreeXml()
    sub.file("2", "C:\\Temp\\VC~~\\sub\\Part9^sub.SLDPRT")
    sub.top("m1")
    sub.model("m2", "2")
    sub.ref("m1", "Part9^sub", 1, "m2", virtual=True)
    sub_bytes = assembly_with_tree(sub, {"VirtualComp/Part9-sldprt": part})
    t = TreeXml()
    t.file("2", "C:\\Temp\\VC~~\\top\\Part1^top.SLDPRT")
    t.file("3", "C:\\Temp\\VC~~\\top\\Part3^top.SLDPRT")
    t.file("4", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("5", "C:\\Temp\\VC~~\\sub\\Part9^sub.SLDPRT")
    t.file("6", "C:\\J\\imported.SLDPRT", "PART", swImportedPath="C:\\Import\\imported.step")
    t.top("m1")
    for mid, fid in (("m2", "2"), ("m3", "3"), ("m4", "4"), ("m5", "5"), ("m6", "6")):
        t.model(mid, fid)
    t.ref("m1", "Part1^top", 1, "m2", virtual=True)
    t.ref("m1", "Part3^top", 1, "m3", virtual=True)
    t.ref("m1", "sub", 1, "m4")
    t.ref("m4", "Part9^sub", 1, "m5", virtual=True)
    t.ref("m1", "imported", 1, "m6")
    members = {"VirtualComp/Part1-sldprt": part, "ImportedComp/imported.SLDPRT": part}
    return _job(tmp_path, t, members, files=[("sub.SLDASM", sub_bytes)])


def test_documents_stored_inside_are_read_where_they_are(tmp_path):
    asm = _virtual_assembly(tmp_path)
    with open_document(asm) as doc:
        bom = doc.bom(bom_type="indented")
    rows = {r.part_number: r for r in bom.rows}
    assert list(rows) == ["Part1^top", "Part3^top", "sub", "Part9^sub", "imported"]
    p1 = rows["Part1^top"]
    assert (p1.resolution, p1.location, p1.nested, p1.description) == (
        "embedded",
        None,
        ("VirtualComp/Part1-sldprt",),
        "Oracle test box",
    )
    lost = rows["Part3^top"]
    assert lost.resolution == "embedded_not_found" and lost.properties is None and lost.description is None
    assert [n.code for n in lost.notes] == ["bom_properties_unread"]
    p9 = rows["Part9^sub"]
    assert p9.resolution == "embedded_in_subassembly" and p9.item == "3.1"
    assert p9.location.path == "sub.SLDASM" and p9.nested == ("VirtualComp/Part9-sldprt",)
    assert p9.description == "Oracle test box"
    imported = rows["imported"]
    assert imported.imported and imported.resolution == "embedded"
    assert imported.description == "Oracle test box"
    # sub.SLDASM's identity read, then sub.SLDASM, kept open for the part stored in it.
    assert not bom.complete and bom.counts["unread"] == 1 and bom.counts["files_opened"] == 2
    data = model.build_bom(open_document(asm), bom_type="indented")
    _schema_ok(data)
    assert data["rows"][3]["location"] == {"root": "document", "path": "sub.SLDASM"}


def test_missing_ambiguous_and_unreadable_files_keep_their_rows(tmp_path, capsys):
    t = TreeXml()
    t.file("2", "C:\\J\\gone.SLDPRT")
    t.file("3", "C:\\J\\twice.SLDPRT")
    t.file("4", "C:\\J\\broken.SLDPRT")
    t.file("5", "C:\\J\\p.SLDPRT")
    t.top("m1")
    for mid, fid in (("m2", "2"), ("m3", "3"), ("m4", "4"), ("m5", "5")):
        t.model(mid, fid)
    for name, mid in (("gone", "m2"), ("twice", "m3"), ("broken", "m4"), ("p", "m5")):
        t.ref("m1", name, 1, mid)
    asm = _job(tmp_path, t, files=[("p.SLDPRT", O04), ("broken.SLDPRT", b"not a SOLIDWORKS file")])
    for sub in ("a", "b"):
        (asm.parent / sub).mkdir()
        shutil.copyfile(O02, asm.parent / sub / "twice.SLDPRT")
    with open_document(asm) as doc:
        bom = doc.bom()
    rows = {r.part_number: r for r in bom.rows}
    assert [r.quantity for r in bom.rows] == [1, 1, 1, 1] and not bom.complete
    assert rows["gone"].resolution == "missing" and "not found" in rows["gone"].notes[0].message
    assert rows["twice"].resolution == "ambiguous"
    assert rows["broken"].resolution in ("resolved", "moved")
    assert "could not be read" in rows["broken"].notes[0]
    for name in ("gone", "twice", "broken"):
        r = rows[name]
        assert r.properties is None and r.description is None and r.stored_path == f"C:\\J\\{name}.SLDPRT"
        assert [n.code for n in r.notes] == ["bom_properties_unread"]
    assert rows["p"].description == "Oracle test box" and bom.counts == {
        **bom.counts,
        "rows": 4,
        "read": 1,
        "unread": 3,
    }
    code, env = _run(capsys, "bom", str(asm))
    assert code == cli.EXIT_PARTIAL == 4 and env["data"]["complete"] is False
    assert cli.main(["bom", str(asm)]) == 4
    out = capsys.readouterr().out
    assert "incomplete" in out and "note: 1 gone: bom_properties_unread" in out


def test_a_file_without_the_configuration_uses_its_file_properties(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.file("3", "C:\\J\\q.SLDPRT")
    t.top("m1")
    t.model("m2", "2", "Gone")
    t.model("m3", "3", "Default")
    t.ref("m1", "p", 1, "m2", config="Gone")
    t.ref("m1", "q", 1, "m3", config="Default")
    # q is o04 with the streams that name its configurations left out: SolidSeas finds
    # none, so it cannot say whether the file has "Default".
    unnamed = rebuild(O04, drop=("swXmlContents/KeyWords", "swXmlContents/Features"))
    with open_document(unnamed, name="q.SLDPRT") as q:
        assert q.configurations == []
    asm = _job(tmp_path, t, files=[("p.SLDPRT", O04), ("q.SLDPRT", unnamed)])
    with open_document(asm) as doc:
        bom = doc.bom()
    p, q = bom.rows
    assert p.configuration == "Gone" and p.description == "Oracle test box"
    assert [n.code for n in p.notes] == ["bom_configuration_missing"] and "has no configuration" in p.notes[0]
    assert q.configuration == "Default" and q.description == "Oracle test box"
    assert [n.code for n in q.notes] == ["bom_configurations_unknown"]
    assert "finds no configuration" in q.notes[0].message and bom.complete


def _screws(alternate: str | None, *, file_name: str = "screw") -> TreeXml:
    """Two instances of a part in a configuration whose model stores ``alternate`` as its
    alternate name, as library and Toolbox-like parts do."""
    t = TreeXml()
    t.file("2", f"C:\\Lib\\{file_name}.SLDPRT")
    t.top("m1")
    attrs = {} if alternate is None else {"swConfigurationAlternateName": alternate}
    t.model("m2", "2", "M6x20", **attrs)
    t.ref("m1", "screw", 1, "m2", config="M6x20")
    t.ref("m1", "screw", 2, "m2", config="M6x20")
    return t


def test_an_alternate_name_the_tree_stores_is_carried_and_flagged(tmp_path, capsys):
    """The tree stores an alternate name for a configuration, which SOLIDWORKS shows as the
    part number when the configuration says so; where it says so is unknown. The part
    number stays the document name, the row carries the name and a note, and the BOM is
    not complete (``docs/FORMAT.md`` 12.7)."""
    asm = _job(tmp_path, _screws("M6x20"), files=[("screw.SLDPRT", O04)])
    with open_document(asm) as doc:
        assert [n.alternate_name for n in doc.components().children] == ["M6x20", "M6x20"]
        bom = doc.bom()
        data = model.build_bom(doc)
        by_property = doc.bom(part_number_property="PartNo")
    (row,) = bom.rows
    assert (row.part_number, row.part_number_source) == ("screw", "document_name")
    assert row.alternate_name == "M6x20"
    assert bom.table()[1] == ["1", "screw", "Oracle test box", "2"]
    codes = [n.code for n in row.notes]
    assert codes == ["bom_configuration_missing", "bom_part_number_may_differ"] and not bom.complete
    assert "'M6x20'" in row.notes[1].message
    _schema_ok(data)
    assert data["rows"][0]["alternate_name"] == "M6x20" and data["complete"] is False
    (line,) = list(csv.reader(io.StringIO(bom_mod.csv_text(data), newline="")))[1:]
    header = [*bom_mod.COLUMNS, *bom_mod.CSV_COLUMNS]
    assert line[header.index("ALTERNATE NAME")] == "M6x20"
    assert line[header.index("NOTES")] == "bom_configuration_missing; bom_part_number_may_differ"
    assert cli.main(["bom", str(asm)]) == cli.EXIT_PARTIAL
    assert "bom_part_number_may_differ" in capsys.readouterr().out
    # A part number taken from a property is the caller's choice: no doubt about SOLIDWORKS' column.
    (row,) = by_property.rows
    assert row.part_number == "ORACLE-PN-123"
    assert "bom_part_number_may_differ" not in [n.code for n in row.notes]
    # No alternate name, or one equal to the document name: nothing to flag.
    for alternate, name in ((None, "screw"), ("", "screw"), ("M6x20", "M6x20")):
        folder = tmp_path / f"case_{alternate}_{name}"
        folder.mkdir()
        asm = _job(folder, _screws(alternate, file_name=name), files=[(f"{name}.SLDPRT", O04)])
        with open_document(asm) as doc:
            (row,) = doc.bom().rows
        assert row.alternate_name == (alternate or None)
        assert "bom_part_number_may_differ" not in [n.code for n in row.notes], (alternate, name)


def _sub_tree_without_children() -> TreeXml:
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2")  # the tree lists nothing under sub
    t.ref("m1", "p", 1, "m3")
    return t


def test_instances_of_a_subassembly_with_different_components_are_all_counted(tmp_path):
    """SOLIDWORKS stores one model per file and configuration, so every instance of a
    sub-assembly lists the same components. A damaged or crafted tree with two models of
    one file and configuration still gets every instance into a row, exact totals, and a
    note on the sub-assembly's row."""
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.file("4", "C:\\J\\q.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m2b", "2")  # the same sub-assembly file in the same configuration, a second model
    t.model("m3", "3")
    t.model("m4", "4")
    t.ref("m1", "sub", 1, "m2")
    t.ref("m1", "sub", 2, "m2b")
    t.ref("m2", "p", 1, "m3")
    t.ref("m2b", "q", 1, "m4")
    t.ref("m2b", "q", 2, "m4")
    asm = _job(tmp_path, t, files=[("sub.SLDASM", O15), ("p.SLDPRT", O02), ("q.SLDPRT", O02)])
    with open_document(asm) as doc:
        tree = doc.components()
        boms = bom_mod.build_boms(doc)
    ind = boms["indented"]
    assert [(r.item, r.part_number, r.quantity, r.total_quantity, r.instances) for r in ind.rows] == [
        ("1", "sub", 2, 2, ("sub-1", "sub-2")),
        ("1.1", "p", 1, 1, ("sub-1/p-1",)),
        ("1.2", "q", 2, 2, ("sub-2/q-1", "sub-2/q-2")),
    ]
    assert [n.code for n in ind.rows[0].notes] == ["bom_children_differ"] and not ind.complete
    totals: dict[str, int] = {}
    for r in ind.rows:
        totals[r.file] = totals.get(r.file, 0) + r.total_quantity
    assert totals == {k: f.instances_in_bom for k, f in tree.files.items()}
    assert [(r.part_number, r.quantity) for r in boms["parts"].rows] == [("p", 1), ("q", 2)]
    assert boms["top"].complete and boms["parts"].complete


def test_only_subassemblies_that_store_a_needed_document_stay_open(tmp_path):
    """Each component file is closed once read, but for a sub-assembly that stores a
    virtual part a row needs: at most that one is open beside the file being read."""
    t = TreeXml()
    t.top("m1")
    for i in range(2, 8):  # six sub-assemblies, none storing anything a row needs
        t.file(str(i), f"C:\\J\\sub{i}.SLDASM", "ASSEMBLY")
        t.model(f"m{i}", str(i))
        t.ref("m1", f"sub{i}", 1, f"m{i}")
    files = [(f"sub{i}.SLDASM", O15) for i in range(2, 8)]
    asm = _job(tmp_path, t, files=files)
    open_now, most = [], [0]

    def opener(path: str, within: str):
        d = open_document(path, within=within, hold_open=True)
        close = d.close

        def closing():
            if d in open_now:
                open_now.remove(d)
            close()

        d.close = closing
        open_now.append(d)
        most[0] = max(most[0], len(open_now))
        return d

    with open_document(asm) as doc:
        bom = doc.bom(bom_type="indented", read_properties=True, opener=opener)
    # Six identity reads (resolution's own, closed at once) and six reads through the opener.
    assert bom.counts["files_opened"] == 12 and most[0] == 1 and open_now == []
    with open_document(_virtual_assembly(tmp_path)) as doc:
        open_now.clear()
        most[0] = 0
        bom = doc.bom(bom_type="indented", opener=opener)
    assert [r.description for r in bom.rows if r.part_number == "Part9^sub"] == ["Oracle test box"]
    assert most[0] == 1 and open_now == []  # the sub-assembly, kept for its virtual part, then closed


def test_a_subassembly_the_tree_does_not_expand_is_flagged(tmp_path):
    asm = _job(tmp_path, _sub_tree_without_children(), files=[("sub.SLDASM", O15), ("p.SLDPRT", O02)])
    with open_document(asm) as doc:
        boms = bom_mod.build_boms(doc)
    assert boms["top"].complete and not boms["indented"].complete and not boms["parts"].complete
    (sub,) = [r for r in boms["indented"].rows if r.part_number == "sub"]
    assert [n.code for n in sub.notes] == ["bom_children_missing"] and "own file does" in sub.notes[0].message
    assert [r.part_number for r in boms["parts"].rows] == ["sub", "p"]  # kept, with the note


def test_an_empty_subassembly_is_no_part(tmp_path):
    empty = TreeXml()
    empty.top("m1")
    files = [("sub.SLDASM", assembly_with_tree(empty)), ("p.SLDPRT", O02)]
    asm = _job(tmp_path, _sub_tree_without_children(), files=files)
    with open_document(asm) as doc:
        boms = bom_mod.build_boms(doc)
    assert all(b.complete for b in boms.values())
    assert [r.part_number for r in boms["parts"].rows] == ["p"]
    assert [r.part_number for r in boms["indented"].rows] == ["sub", "p"]


def test_cycles_and_limits_are_noted(tmp_path):
    t = TreeXml()
    t.file("2", "C:\\J\\a.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "a", 1, "m2")
    t.ref("m2", "a", 1, "m2")  # a contains itself
    t.ref("m2", "p", 1, "m3")
    asm = _job(tmp_path, t, files=[("p.SLDPRT", O02)])
    with open_document(asm) as doc:
        ind = doc.bom(bom_type="indented", read_properties=False)
        cut = doc.bom(bom_type="indented", read_properties=False, max_depth=1)
    assert [(r.item, r.part_number) for r in ind.rows] == [("1", "a"), ("1.1", "a"), ("1.2", "p")]
    assert [n.code for n in ind.rows[1].notes] == ["bom_children_missing"] and not ind.complete
    assert cut.truncated and not cut.complete and [r.item for r in cut.rows] == ["1"]
    assert "limit" in cut.rows[0].notes[0].message


def test_file_and_time_limits_leave_rows_unread(tmp_path):
    inside = {"allow_outside_roots": False}  # not the parts at o16's stored paths, as above
    with open_document(O16) as doc:
        none = doc.bom(max_files=0, **inside)
        late = doc.bom(max_seconds=0, **inside)
        few = doc.bom(max_files=8, **inside)
        identities = doc.bom(max_files=3, **inside)
    for bom, limit in ((none, "max_files"), (late, "max_seconds"), (identities, "max_files")):
        assert [w.code for w in bom.warnings][-1:] == ["bom_limit_reached"] and limit in bom.warnings[-1]
        unread = [r.part_number for r in bom.rows if r.properties is None]
        assert len(unread) == 6 and not bom.complete  # the virtual part is read from the assembly
    # The six identity reads of resolution, then two files and the virtual part.
    assert few.counts["files_opened"] == 8 and few.counts["read"] == 3
    # Three identities read of six, which take the whole limit: no file is read.
    assert identities.counts["files_opened"] == 3 and identities.counts["read"] == 1


def test_a_document_read_from_bytes_needs_roots(tmp_path):
    asm = _job(tmp_path, _sub_tree_without_children(), files=[("sub.SLDASM", O15), ("p.SLDPRT", O04)])
    with open_document(asm.read_bytes(), name="top.SLDASM") as doc:
        alone = doc.bom()
        rooted = doc.bom(roots={"jobs": str(asm.parent)})
    assert all("no roots were given" in r.notes[0] for r in alone.rows)
    assert [r.description for r in rooted.rows] == ["", "Oracle test box"]
    assert rooted.rows[1].location.root == "jobs"


def test_a_resolution_made_before_is_used_as_it_is(tmp_path):
    roots = Roots([Root("fx", str(FIXTURES))])
    with open_document(O16) as doc:
        res = resolve_references(doc, roots)
        bom = doc.bom(roots=roots, resolution=res)
    assert bom.resolution is res and bom.rows[0].location.root == "fx"
    payload = bom_mod.resolution_payload(res)
    back = bom_mod.resolution_from_payload(json.loads(model.dumps(payload)))
    assert model.resolution_summary_data(back) == model.resolution_summary_data(res)
    assert {k: (r.status, r.match) for k, r in back.results.items()} == {
        k: (r.status, r.match) for k, r in res.results.items()
    }
    assert back.results["6"].match.host_path == res.results["6"].match.host_path
    with pytest.raises(InvalidArgumentError):
        bom_mod.resolution_from_payload({"results": [{"key": 1}], "roots": []})


# --------------------------------------------------------------------------- export
def test_csv_quotes_guards_formulas_and_marks_utf8():
    data = {
        "columns": [*bom_mod.COLUMNS, "Note"],
        "rows": [
            {
                "item": "1",
                "level": 0,
                "part_number": "=HYPERLINK(1)",
                "description": 'a "quoted", text',
                "quantity": 2,
                "values": ["line\nbreak"],
                "total_quantity": 2,
                "configuration": "Default",
                "alternate_name": "@M6",
                "doc_type": "part",
                "file_name": "x.SLDPRT",
                "stored_path": "C:\\J\\x.SLDPRT",
                "location": {"root": "jobs", "path": "a/x.SLDPRT"},
                "nested": ["VirtualComp/x"],
                "notes": [{"code": "bom_properties_unread", "stream": None, "message": "m"}],
            }
        ],
    }
    text = bom_mod.csv_text(data)
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows[0] == [*bom_mod.COLUMNS, "Note", *bom_mod.CSV_COLUMNS]
    assert rows[1][:5] == ["1", "'=HYPERLINK(1)", 'a "quoted", text', "2", "line\nbreak"]
    assert rows[1][-2:] == ["jobs:a/x.SLDPRT > VirtualComp/x", "bom_properties_unread"]
    assert rows[1][rows[0].index("ALTERNATE NAME")] == "'@M6"
    assert text.endswith("\r\n") and '"a ""quoted"", text"' in text
    assert bom_mod.csv_bytes(data) == b"\xef\xbb\xbf" + text.encode("utf-8")


def test_the_cli_writes_csv_and_json_under_its_guards(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    target = out / "o16.json"
    code, env = _run(capsys, "bom", str(O16), "--type", "parts", "--format", "json", "-o", str(target))
    assert code == 0 and json.loads(target.read_text(encoding="utf-8")) == env
    code, env = _run(capsys, "bom", str(O16), "--format", "csv", "-o", str(target))
    assert code == 3 and env["error"]["detail"]["rule"] == "exists"
    assert cli.main(["bom", str(O16), "--format", "csv", "-o", str(target), "--force"]) == 0
    assert "as csv to" in capsys.readouterr().out and target.read_bytes().startswith(b"\xef\xbb\xbf")
    code, env = _run(capsys, "bom", str(O16), "-o", str(FIXTURES / "never.csv"))
    assert code == 3 and env["error"]["detail"]["rule"] == "source_folder"
    assert not (FIXTURES / "never.csv").exists()
    code, env = _run(capsys, "bom", str(O16), "--format", "csv")
    assert code == 2 and env["error"]["detail"] == {"parameter": "format"}
    code, env = _run(capsys, "bom", str(O16), "--column", " ")
    assert code == 2 and env["error"]["reader_message"].startswith("--column: a property name has 1 to 256")


def test_the_cli_writes_no_bom_into_a_folder_it_read_from(tmp_path, capsys):
    """Not beside the assembly, nor in a --root or --library folder, nor beside a component
    file found outside them, unless --allow-source-dir says so."""
    proj = tmp_path / "proj"
    elsewhere = tmp_path / "elsewhere"
    for d in (proj / "asm", proj / "lib", elsewhere, tmp_path / "out"):
        d.mkdir(parents=True)
    shutil.copyfile(O04, proj / "lib" / "p.SLDPRT")
    shutil.copyfile(O02, elsewhere / "q.SLDPRT")
    t = TreeXml()
    t.file("2", "C:\\Nowhere\\p.SLDPRT")
    t.file("3", str(elsewhere / "q.SLDPRT"))  # found at its stored path on Windows
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "p", 1, "m2")
    t.ref("m1", "q", 1, "m3")
    asm = proj / "asm" / "top.SLDASM"
    asm.write_bytes(assembly_with_tree(t))
    base = ["bom", str(asm), "--root", f"proj={proj}", "--format", "csv", "-o"]
    refused = [proj / "asm" / "bom.csv", proj / "lib" / "bom.csv", proj / "bom.csv"]
    if os.name == "nt":
        refused.append(elsewhere / "bom.csv")
    for target in refused:
        code, env = _run(capsys, *base, str(target))
        assert code == 3 and env["error"]["detail"]["rule"] == "source_folder", target
        assert not target.exists()
    code, env = _run(capsys, *base, str(tmp_path / "out" / "bom.csv"))
    assert code in (0, 4) and (tmp_path / "out" / "bom.csv").exists()
    assert cli.main([*base, str(proj / "lib" / "bom.csv"), "--allow-source-dir"]) in (0, 4)
    capsys.readouterr()
    assert (proj / "lib" / "bom.csv").exists()


def test_the_cli_table_shows_control_characters_as_escapes(tmp_path, capsys):
    """A value with a line break or a carriage return stays on its row in the text
    table; the CSV keeps it as it is, quoted."""
    from builders import fixture_streams

    custom = fixture_streams(O04)["docProps/custom.xml"]
    hostile = rebuild(O04, {"docProps/custom.xml": custom.replace(b"Oracle test box", b"a&#13;&#10;b&#13;c")})
    with open_document(hostile, name="p.SLDPRT") as d:
        assert [p.text for p in d.properties if p.name == "Description"] == ["a\r\nb\rc"]
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.ref("m1", "p", 1, "m2")
    asm = _job(tmp_path, t, files=[("p.SLDPRT", hostile)])
    assert cli.main(["bom", str(asm)]) == 0
    out = capsys.readouterr().out
    (line,) = [x for x in out.splitlines() if x.split()[:2] == ["1", "p"]]
    assert line.split() == ["1", "p", "a\\r\\nb\\rc", "1"]
    assert "\r" not in out
    target = tmp_path / "out.csv"
    assert cli.main(["bom", str(asm), "--format", "csv", "-o", str(target)]) == 0
    capsys.readouterr()
    rows = list(csv.reader(io.StringIO(target.read_bytes()[3:].decode("utf-8"), newline="")))
    assert rows[1][2] == "a\r\nb\rc"
    code, env = _run(capsys, "bom", str(O16), "--type", "flat")
    assert code == 2 and env["error"]["code"] == "invalid_argument"
    code, env = _run(capsys, "bom", str(O16), "--configuration", "Nope")
    assert code == 1 and env["error"]["code"] == "configuration_not_found"
    code, env = _run(capsys, "bom", str(O16), "--column", "PartNo", "--part-number-property", "PartNo")
    assert code == 0 and env["data"]["rows"][1]["part_number"] == "ORACLE-PN-123"
    assert env["data"]["rows"][1]["values"] == ["ORACLE-PN-123"]
    code, env = _run(capsys, "bom", str(O16), "--root", f"fx={FIXTURES}", "--no-outside-roots")
    assert code == 0 and env["data"]["rows"][0]["location"]["root"] == "fx"
    assert env["data"]["resolution"]["outside_roots"] is False
    # CSV and JSON on standard output, without --json
    assert cli.main(["bom", str(O16), "--format", "csv"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("ITEM NO.,PART NUMBER") and "o17_деталь" in text
    assert cli.main(["bom", str(O16), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "bom"
    assert cli.main(["bom", str(O02)]) == 0
    assert "no BOM: the document is a part" in capsys.readouterr().out


def test_an_indented_plan_counts_each_instance_once_however_its_tree_is_crafted():
    """A damaged or crafted tree: one sub-assembly placed 450 times, each instance listing
    450 components of its own (SOLIDWORKS lists one model per file and configuration).
    Planning counts every node once, in moments, instead of looking each of the 202,500
    rows' QTY. up across all 450 instances."""
    import time
    from types import SimpleNamespace

    def node(file, children=()):
        return SimpleNamespace(
            file=file,
            component=None,
            name=file,
            configuration="Default",
            suppressed=False,
            excluded_from_bom=False,
            children=list(children),
        )

    n = 450
    tree = SimpleNamespace(children=[node("sub", [node(f"p{i}-{j}") for j in range(n)]) for i in range(n)])
    t0 = time.perf_counter()
    plan = bom_mod._plan_indented(tree)
    assert time.perf_counter() - t0 < within(1.5)
    assert len(plan) == 1 + n * n
    assert (plan[0].item, plan[0].quantity, plan[0].total, plan[0].children_differ) == ("1", n, n, True)
    assert (plan[1].item, plan[1].quantity, plan[1].total) == ("1.1", 1, 1)
