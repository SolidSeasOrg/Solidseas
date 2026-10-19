"""The BOM editor's table definition (``solidseas.bomtable``) on o16, whose indented BOM
has a sub-assembly (o15) holding o02 and o07, three instances of o07 at the top, a
part used in a configuration of its own (o06 in OracleAlt) and a virtual part."""

import shutil

import pytest

from solidseas import InvalidArgumentError, open_document
from solidseas import bom as bom_mod
from solidseas.bomtable import (
    BUILT_IN,
    DEFAULT_COLUMNS,
    apply,
    column,
    row_keys,
    spec,
    spec_from_json,
)
from support import fixture_path

O16 = fixture_path("o16_asm_features.SLDASM")


@pytest.fixture(scope="module")
def boms():
    with open_document(O16) as doc:
        return {t: bom_mod.build_bom(doc, bom_type=t, columns=["Description"]) for t in bom_mod.BOM_TYPES}


def _items(table) -> list[tuple[str, str]]:
    return [(r.item, r.cells[1].strip()) for r in table.rows]


def test_the_default_spec_shows_the_bom_as_solidworks_numbers_it(boms):
    for t, b in boms.items():
        table = apply(spec(t), b)
        assert table.headings() == [BUILT_IN[c] for c in DEFAULT_COLUMNS]
        assert table.cells()[1:] == [row[:4] for row in b.table()[1:]], t
        assert not any(any(r.overridden) for r in table.rows) and table.unused == () and table.hidden == ()


def test_keys_name_the_file_and_configuration_and_the_sub_assembly_above(boms):
    keys = row_keys(boms["indented"])
    assert keys["2"] == "o06_boxa_props_mat_cfg.sldprt|OracleAlt"
    assert keys["3.1"] == "o15_sub_asm.sldasm|Default/o02_boxa.sldprt|Default"
    assert keys["1"] == "o02_boxa.sldprt|Default" != keys["3.1"], (
        "the same part under a sub-assembly is another row"
    )
    assert len(set(keys.values())) == len(keys)


def test_reordering_and_hiding_number_the_items_again_and_keep_components_under_their_sub_assembly(boms):
    b = boms["indented"]
    keys = row_keys(b)
    s = spec("indented", order=[keys["4"], keys["3"], keys["3.2"]], hidden=[keys["1"]])
    table = apply(s, b)
    assert _items(table) == [
        ("1", "o07_boxB_h31"),
        ("2", "o15_sub_asm"),
        ("2.1", "o07_boxB_h31"),
        ("2.2", "o02_boxA"),
        ("3", "o06_boxA_props_mat_cfg"),
        ("4", "o09_import_step"),
        ("5", "o17_деталь"),
        ("6", "Part12^o16_asm_features"),
    ]
    assert table.hidden == (keys["1"],)
    gone = apply(spec("indented", hidden=[keys["3"]]), b)
    assert [r.item for r in gone.rows] == ["1", "2", "3", "4", "5", "6"], (
        "a hidden sub-assembly hides its rows"
    )


def test_an_override_replaces_one_cell_and_one_whose_row_is_gone_is_reported(boms):
    b = boms["top"]
    keys = row_keys(b)
    s = spec(
        "top",
        [*DEFAULT_COLUMNS, "property:Description", ("total_quantity", "TOTAL")],
        overrides={
            (keys["1"], "description"): "Base plate, 6 mm",
            ("gone.sldprt|Default", "description"): "an old edit",
            (keys["2"], "configuration"): "a column not shown",
        },
    )
    table = apply(s, b)
    first, second = table.rows[0], table.rows[1]
    assert first.cells[2] == "Base plate, 6 mm" and first.overridden == (
        False,
        False,
        True,
        False,
        False,
        False,
    )
    assert second.cells[4] == "Oracle test box", "a property column reads the property"
    assert table.headings()[-2:] == ["DESCRIPTION", "TOTAL"]
    assert table.unused == (("gone.sldprt|Default", "description"), (keys["2"], "configuration"))


def test_bom_json_from_the_viewers_reader_gives_the_same_table(boms):
    from solidseas import model

    for t, b in boms.items():
        keys = row_keys(b)
        first = next(iter(keys.values()))
        s = spec(
            t, [*DEFAULT_COLUMNS, "property:Description"], order=[list(keys.values())[-1]], hidden=[first]
        )
        assert apply(s, model.bom_data(b)).cells() == apply(s, b).cells(), t
        assert row_keys(model.bom_data(b)) == keys


def test_a_property_column_reads_the_rows_own_properties_when_the_bom_lacks_it(boms):
    from solidseas import model
    from solidseas.bomtable import property_names

    with open_document(O16) as doc:
        plain = bom_mod.build_bom(doc, bom_type="top")  # no property columns, as the viewer reads it
    s = spec("top", ["part_number", "property:partno"])
    table = apply(s, model.bom_data(plain))
    assert [r.cells[1] for r in table.rows][1] == "ORACLE-PN-123", "names are compared without case"
    names = property_names(plain)
    assert "PartNo" in names and "Description" in names and len(names) == len({n.casefold() for n in names})


def test_the_spec_round_trips_through_json(boms):
    keys = row_keys(boms["parts"])
    s = spec(
        "parts",
        [*DEFAULT_COLUMNS, "property:Material"],
        order=[keys["2"]],
        overrides={(keys["1"], "quantity"): "2 + spare"},
    )
    again = spec_from_json(s.to_json())
    assert again == s and again.property_names() == ("Material",)


@pytest.mark.parametrize(
    "make",
    [
        lambda: spec("flat"),
        lambda: spec("top", ["item", "item"]),
        lambda: spec("top", []),
        lambda: spec("top", ["weight"]),
        lambda: column("property:"),
        lambda: column("item", "two\nlines"),
        lambda: spec("top", overrides={("k|Default", "item"): "9"}),
        lambda: spec("top", overrides={("k|Default", "description"): "x" * 1001}),
        lambda: spec("top", order=["a", "a"]),
        lambda: spec_from_json({"version": 99}),
        lambda: spec_from_json({"version": 1, "type": "top", "columns": [{"id": "item"}]}),
    ],
)
def test_a_bad_spec_is_refused(make):
    with pytest.raises(InvalidArgumentError):
        make()


# --------------------------------------------------------------------------- the .ssbom file
def test_a_bom_file_round_trips_and_is_written_only_new_or_over_what_was_read(boms, tmp_path):
    from solidseas import OutputRefusedError
    from solidseas.bomfile import assembly_path, make, read, save

    b = boms["indented"]
    keys = row_keys(b)
    s = spec("indented", overrides={(keys["2"], "description"): "Oracle box, anodised"})
    table = apply(s, b)
    target = tmp_path / "boms" / "o16.ssbom"
    target.parent.mkdir()
    # The assembly beside the BOM file's folder, on the same drive (a hosted Windows runner
    # keeps the temporary folder and the checkout on different drives; see the test below).
    assembly = tmp_path / O16.name
    shutil.copyfile(O16, assembly)
    made = make(target, assembly, "Default", table, s)
    saved = save(made, target)
    loaded = read(target)
    assert loaded.bom_file == made and loaded.sha256 == saved.sha256
    assert loaded.bom_file.table[2][2] == "Oracle box, anodised"
    assert assembly_path(target, loaded.bom_file) == str(assembly)
    assert loaded.bom_file.model["relative"] == f"../{O16.name}"
    with pytest.raises(OutputRefusedError):
        save(made, target)  # there already: only over what was read
    again = save(made, target, replaces=loaded.sha256)
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(OutputRefusedError):
        save(made, target, replaces=again.sha256)  # changed since: it stays
    with pytest.raises(InvalidArgumentError):
        save(made, tmp_path / "o16.json")


def test_a_bom_file_on_another_drive_records_no_path_to_its_assembly(boms, tmp_path, monkeypatch):
    from solidseas import bomfile

    def other_drive(*_args, **_kwargs):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(bomfile.os.path, "relpath", other_drive)
    s = spec("indented")
    made = bomfile.make(tmp_path / "o16.ssbom", O16, "Default", apply(s, boms["indented"]), s)
    assert made.model == {"name": O16.name, "relative": None, "configuration": "Default"}
    assert bomfile.assembly_path(tmp_path / "o16.ssbom", made) is None  # never an absolute path


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b'{"format": "solidseas-bom", "schema": 2}',
        b'{"format": "other", "schema": 1}',
        b'{"format": "solidseas-bom", "format": "solidseas-bom", "schema": 1}',
        b'{"format": "solidseas-bom", "schema": 1, "model": {"name": "a"}, "table": [[NaN]]}',
        b'{"format": "solidseas-bom", "schema": 1, "model": {"name": "a"}, '
        b'"spec": {"version": 1, "type": "top", "columns": [{"id": "item", "heading": "ITEM"}]}, '
        b'"table": [[1]]}',
    ],
)
def test_a_damaged_bom_file_is_refused(data):
    from solidseas.bomfile import loads

    with pytest.raises(InvalidArgumentError):
        loads(data)
