"""Comparing two versions (solidseas.versions.versiondiff) on the fixture kit's differential
pairs (tests/fixtures/README.md): each pair isolates one change, and the comparison must
report that change and nothing else."""

import copy
import shutil

import pytest

from jsonschema_subset import validate
from solidseas import model, open_document, versions
from solidseas.formats.solidworks.parasolid import compare_brep
from solidseas.versions.versiondiff import Side, body_fingerprint, compare_sides
from support import fixture_path


def diff(a: str, b: str, **options) -> dict:
    """The comparison of fixture ``a`` with fixture ``b``, both read as one file's versions."""
    name = "part" + a[a.rindex(".") :]
    with Side(fixture_path(a).read_bytes(), name) as sa, Side(fixture_path(b).read_bytes(), name) as sb:
        return compare_sides(sa, sb, **options)


def geometry(d: dict) -> dict:
    return {row["configuration"]: row for row in d["geometry"]["configurations"]}


def nothing_but(d: dict, *, preview: bool = False) -> None:
    fields = [c["field"] for c in d["document"]["changes"]]
    assert fields == (["preview"] if preview else []), fields


def test_saving_again_changes_nothing_that_matters():
    d = diff("o02_boxA.SLDPRT", "o03_boxA_again.SLDPRT")
    nothing_but(d)
    assert d["properties"] == {"added": [], "removed": [], "changed": []}
    assert d["configurations"]["added"] == d["configurations"]["removed"] == []
    row = geometry(d)["Default"]
    assert row["status"] == "unchanged" and row["changes"] == [] and row["to"]["measures"] is None
    assert row["from"]["fingerprint"] == row["to"]["fingerprint"]
    assert (row["to"]["faces"], row["to"]["edges"], row["to"]["vertices"]) == (6, 12, 8)
    assert row["to"]["bodies"] == {"solid": 1, "sheet": 0, "wire": 0, "general": 0}


def test_custom_properties():
    d = diff("o02_boxA.SLDPRT", "o04_boxA_props.SLDPRT")
    nothing_but(d)
    added = {(p["configuration"], p["name"]): p["to"] for p in d["properties"]["added"]}
    assert set(added) == {(None, "PartNo"), (None, "Description"), (None, "Qty")}
    assert added[(None, "PartNo")]["value"] == "ORACLE-PN-123" and added[(None, "Qty")]["value"] == 42
    assert added[(None, "Qty")]["type"] == "number"
    assert d["properties"]["removed"] == d["properties"]["changed"] == []
    assert geometry(d)["Default"]["status"] == "unchanged"
    back = diff("o04_boxA_props.SLDPRT", "o02_boxA.SLDPRT")
    assert {p["name"] for p in back["properties"]["removed"]} == {"PartNo", "Description", "Qty"}
    assert all(p["to"] is None and p["from"] is not None for p in back["properties"]["removed"])


def test_material():
    d = diff("o04_boxA_props.SLDPRT", "o05_boxA_props_mat.SLDPRT")
    changes = [(c["field"], c["configuration"], c["from"], c["to"]) for c in d["document"]["changes"]]
    assert ("material", "Default", None, "1060 Alloy") in changes
    assert {c[0] for c in changes} == {"material", "preview"}  # the preview shows the material's colour
    assert d["properties"] == {"added": [], "removed": [], "changed": []}
    assert geometry(d)["Default"]["status"] == "unchanged"


def test_configurations_and_their_properties():
    d = diff("o05_boxA_props_mat.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT")
    nothing_but(d)
    assert d["configurations"] == {
        "added": ["OracleAlt"],
        "removed": [],
        "active": {"from": "Default", "to": "Default"},
    }
    (added,) = d["properties"]["added"]
    assert (added["configuration"], added["name"], added["to"]["value"]) == (
        "OracleAlt",
        "CfgOnly",
        "ALT-VALUE",
    )
    rows = geometry(d)
    assert rows["Default"]["status"] == "unchanged"
    assert rows["OracleAlt"]["status"] == "added" and rows["OracleAlt"]["to"]["stored"] is False


def test_geometry_alone():
    d = diff("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT")
    nothing_but(d, preview=True)
    assert d["properties"] == {"added": [], "removed": [], "changed": []}
    row = geometry(d)["Default"]
    assert row["status"] == "changed" and row["from"]["fingerprint"] != row["to"]["fingerprint"]
    changes = {c["measure"]: (c["from"], c["to"]) for c in row["changes"]}
    assert set(changes) == {"volume_mm3", "area_mm2", "size_z_mm"}  # same counts, a taller box
    assert changes["volume_mm3"] == pytest.approx(
        (6000.0, 6200.0), rel=1e-9
    )  # ground truth 6.0e-6, 6.2e-6 m^3
    assert changes["area_mm2"] == pytest.approx((2200.0, 2260.0), rel=1e-9)
    assert changes["size_z_mm"] == pytest.approx((30.0, 31.0))
    m = row["to"]["measures"]
    assert (
        m["measured"] and m["complete"] and m["closed"] and m["box_mm"]["size"] == pytest.approx([10, 20, 31])
    )


def test_a_configuration_with_geometry_of_its_own():
    d = diff("o02_boxA.SLDPRT", "o13_two_geometry_configs.SLDPRT")
    assert d["configurations"]["added"] == ["Tall"]
    rows = geometry(d)
    assert rows["Default"]["status"] == "unchanged"
    assert rows["Tall"]["status"] == "added" and rows["Tall"]["to"]["stored"] and rows["Tall"]["from"] is None


def test_bodies_added():
    row = geometry(diff("o02_boxA.SLDPRT", "o12_multibody.SLDPRT"))["Default"]
    changes = {c["measure"]: (c["from"], c["to"]) for c in row["changes"]}
    assert changes["solid_bodies"] == (1, 2) and changes["faces"] == (6, 12)
    assert changes["volume_mm3"] == pytest.approx((6000.0, 8000.0), rel=1e-9)


def test_a_part_and_an_assembly_and_two_assemblies():
    d = diff("o02_boxA.SLDPRT", "o08_asm_2x_boxA.SLDASM")
    assert ("type", "part", "assembly") in [
        (c["field"], c["from"], c["to"]) for c in d["document"]["changes"]
    ]
    assert d["geometry"] == {"compared": False, "reason": "different_types", "configurations": []}
    d = diff("o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM")
    assert d["geometry"]["reason"] == "assembly"


def test_the_fingerprint_is_the_shape_not_the_bytes_or_the_numbering():
    def bodies(name):
        with open_document(fixture_path(name)) as doc:
            return [b.transmit for b in doc.parasolid().bodies]

    (a,), (b,), (c,), (d,) = (
        bodies(n)
        for n in ("o02_boxA.SLDPRT", "o03_boxA_again.SLDPRT", "o17_деталь.SLDPRT", "o07_boxB_h31.SLDPRT")
    )
    assert body_fingerprint(a) == body_fingerprint(b) == body_fingerprint(c) != body_fingerprint(d)
    assert compare_brep(a, b)["identical"] and not compare_brep(a, d)["identical"]
    # the same nodes numbered otherwise and listed in another order
    renumbered = copy.deepcopy(a)
    shift = {n.index: n.index + 1000 for n in renumbered.nodes}
    for n in renumbered.nodes:
        layout = renumbered.layouts[n.type]
        for k, (f, v) in enumerate(zip(layout, n.vals, strict=False)):
            if f[1] == "p":
                n.vals[k] = [shift.get(x, x) for x in v] if isinstance(v, list) else shift.get(v, v)
        n.index = shift[n.index]
    renumbered.nodes.reverse()
    renumbered._by_index = None
    assert body_fingerprint(renumbered) == body_fingerprint(a)


def test_a_part_and_its_parasolid_export_have_one_fingerprint():
    """SOLIDWORKS' own .x_b export of o02 and o07 holds the same B-rep as the parts."""
    for part, export in (("o02_boxA.SLDPRT", "o02_boxA.x_b"), ("o07_boxB_h31.SLDPRT", "o07_boxB_h31.x_b")):
        with (
            Side(fixture_path(part).read_bytes(), part) as sp,
            Side(fixture_path(export).read_bytes(), export) as sx,
        ):
            assert sp.geometry["Default"]["fingerprint"] == sx.geometry[None]["fingerprint"]


def test_model_files():
    d = diff("o02_boxA.x_b", "o07_boxB_h31.x_b")
    (row,) = d["geometry"]["configurations"]
    assert row["configuration"] is None and row["status"] == "changed"
    assert {c["measure"] for c in row["changes"]} == {"volume_mm3", "area_mm2", "size_z_mm"}
    assert {p["name"] for p in d["properties"]["changed"]} >= {"FILE", "KEY"}  # the header's fields
    d = diff("o02_boxA.STL", "o02_boxA.STL")
    (row,) = d["geometry"]["configurations"]
    assert row["status"] == "unchanged" and row["to"]["triangles"] == 12


def test_measuring_is_optional_and_bounded():
    row = geometry(diff("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT", measure=False))["Default"]
    assert row["status"] == "changed" and row["changes"] == [] and row["to"]["measures"] is None
    d = diff("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT", max_seconds=1e-9)
    row = geometry(d)["Default"]
    assert row["to"]["measures"] == {**row["to"]["measures"], "measured": False, "reason": "max_seconds"}
    assert [w["code"] for w in d["warnings"]] == ["measures_incomplete"]


def test_compare_through_a_history_and_its_schema(tmp_path):
    path = tmp_path / "bracket.SLDPRT"
    shutil.copyfile(fixture_path("o04_boxA_props.SLDPRT"), path)
    versions.snapshot(path)
    shutil.copyfile(fixture_path("o05_boxA_props_mat.SLDPRT"), path)
    versions.snapshot(path)
    shutil.copyfile(fixture_path("o07_boxB_h31.SLDPRT"), path)  # the working copy, not snapshotted
    d = versions.compare(path)
    assert (d["from"]["number"], d["to"]["number"], d["to"]["kind"]) == (2, 3, "working")
    assert d["source"] == "snapshots" and d["same_content"] is False
    assert geometry(d)["Default"]["status"] == "changed"
    old = versions.compare(path, "v1", "v2")
    assert ("material", "Default") in [(c["field"], c["configuration"]) for c in old["document"]["changes"]]
    same = versions.compare(path, "v2", "latest")
    assert same["same_content"] and geometry(same)["Default"]["status"] == "unchanged"
    for kind, data in (("version_diff", d), ("file_history", versions.history(path))):
        env = model.envelope(kind, data)
        assert validate(env, model.envelope_schema(kind), strict=True) == []
    with versions.open_version(path, "v1") as doc:
        assert doc.preview() is not None and {p.name for p in doc.properties} == {
            "PartNo",
            "Description",
            "Qty",
        }
