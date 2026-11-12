"""Component trees, referenced files and drawing sheets (``docs/API.md`` section 5.9).

Crafted ``COMPINSTANCETREE`` streams (``builders.TreeXml``) exercise what the
SOLIDWORKS-made fixtures cannot: deep and cyclic trees, size limits, damaged
transforms, odd names, display states, nested virtual and imported documents
and drawings. ``test_components_ground_truth.py`` compares the same code with
what SOLIDWORKS itself reported for the fixtures.
"""

import math
import time
import warnings

import pytest

from builders import (
    IDENTITY_TRANSFORM,
    TreeXml,
    assembly_with_tree,
    drawing_keywords,
    rebuild,
    sheet_names,
    transform_text,
)
from jsonschema_subset import validate
from solidseas import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    SolidSeasDeprecationWarning,
    StreamNotFoundError,
    cli,
    model,
    open_document,
)
from solidseas.formats.solidworks import components as components_mod
from solidseas.formats.solidworks.components import (
    IDENTITY,
    MAX_DEPTH_LIMIT,
    MAX_NODES_LIMIT,
    MAX_REFERENCE_SET_NODES,
    parse_sheet_names,
)
from support import ASSEMBLY, PARTS, fixture_path

O04 = fixture_path("o04_boxA_props.SLDPRT")
O08 = fixture_path(ASSEMBLY)


def _schema_ok(kind: str, data: dict) -> None:
    errors = validate(data, model.KINDS[kind].schema, strict=True)
    assert errors == [], errors[:5]
    assert model.to_json_data(data) == data  # already plain JSON data
    model.dumps(model.envelope(kind, data))  # and the strict encoder accepts it


def _tree(tree: TreeXml, members=None, **kwargs):
    return open_document(assembly_with_tree(tree, members), name="top.SLDASM", **kwargs)


def _simple(n_parts: int = 1) -> TreeXml:
    t = TreeXml()
    t.file("2", "C:\\Jobs\\p.SLDPRT")
    t.model("m2", "2")
    t.top("m1")
    for k in range(1, n_parts + 1):
        t.ref("m1", "p", k, "m2", sw_id=k)
    return t


# --------------------------------------------------------------------------- the SOLIDWORKS-made assembly
def test_o08_two_instances_005_m_apart():
    with open_document(O08) as doc:
        tree = doc.components()
        refs = model.build_references(doc)
        (old,) = doc.references()
    assert (tree.configuration, tree.configuration_source, tree.children_state) == (
        "Default",
        "active",
        "described",
    )
    assert [n.id for n in tree.walk()] == ["o02_boxA-1", "o02_boxA-2"]
    (key,) = tree.files
    f = tree.files[key]
    assert (
        key.isdigit() and old.key == key and [x["key"] for x in refs["files"]] == [key]
    )  # C7: one key everywhere
    assert (f.file_name, f.doc_type, f.direct, f.instances, f.instances_in_bom) == (
        "o02_boxA.SLDPRT",
        "part",
        True,
        2,
        2,
    )
    a, b = tree.children
    assert a.file == b.file == key and a.transform.rotation == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    delta = [b.placement.translation_m[i] - a.placement.translation_m[i] for i in range(3)]
    assert delta == pytest.approx([0.05, 0.0, 0.0], abs=1e-12)
    assert a.placement == IDENTITY.then(a.transform)  # depth 1: the placement is the stored transform
    assert refs["files"][0]["per_configuration"] == [
        {"configuration": "Default", "instances": 2, "instances_unsuppressed": 2, "instances_in_bom": 2}
    ]


def test_o08_json_nested_and_flat():
    with open_document(O08) as doc:
        nested = model.build_components(doc)
        flat = model.build_components(doc, flat=True)
        refs = model.build_references(doc)
    for kind, data in (("components", nested), ("components", flat), ("references", refs)):
        _schema_ok(kind, data)
    assert nested["instances"] is None and len(nested["children"]) == 2
    assert flat["children"] is None and [n["id"] for n in flat["instances"]] == ["o02_boxA-1", "o02_boxA-2"]
    assert all(n["children"] is None and n["parent"] is None for n in flat["instances"])
    assert nested["counts"] == flat["counts"] == {"nodes": 2, "depth": 1, "files": 1}
    t = nested["children"][1]["transform"]
    assert t["stored"][12:15] == t["translation_m"] and t["scale"] == 1.0 and len(t["stored"]) == 16


def test_parts_and_drawings_have_no_tree():
    with open_document(fixture_path(PARTS[1])) as doc:
        assert doc.components() is None
        data = model.build_components(doc)
        refs = model.build_references(doc)
        with pytest.raises(ConfigurationNotFoundError):
            model.build_references(doc, configuration="Nope")
    _schema_ok("components", data)
    _schema_ok("references", refs)
    assert (data["children_state"], data["children"], data["files"]) == ("none", [], [])
    assert (refs["children_state"], refs["files"], refs["sheets"]) == ("none", [], None)


def test_a_parts_external_files_are_its_references():
    """Base part, mirrored part, in-context assembly and import source, each told apart by
    the type of the feature that uses it (crafted: the fixture kit has none of these)."""
    from builders import part_with_externals

    data = part_with_externals(
        [
            ("C:\\Jobs\\base.SLDPRT", "PART", "Stock"),
            ("C:\\Jobs\\left.SLDPRT", "PART", "MirrorStock"),
            ("C:\\Jobs\\top.SLDASM", "ASSEMBLY", None),
            ("C:\\Vendor\\motor.STEP", "PART", "MBimport"),
            ("C:\\Vendor\\gear.igs", "PART", None),
            ("C:\\Jobs\\other.SLDPRT", "PART", None),
        ],
        imported_path={"5": "C:\\Vendor\\motor.STEP"},
    )
    with open_document(data, name="p.SLDPRT") as doc:
        files = doc.reference_set().files
        refs = model.build_references(doc)
        assert doc.components() is None  # still no component tree
    assert [(f.key, f.file_name, f.doc_type, f.relation) for f in files.values()] == [
        ("2", "base.SLDPRT", "part", "base_part"),
        ("3", "left.SLDPRT", "part", "mirrored_part"),
        ("4", "top.SLDASM", "assembly", "in_context"),
        ("5", "motor.STEP", None, "import_source"),
        ("6", "gear.igs", None, "import_source"),
        ("7", "other.SLDPRT", "part", "external"),
    ]
    motor = files["5"]
    assert (motor.imported, motor.imported_path, motor.direct, motor.instances) == (
        True,
        "C:\\Vendor\\motor.STEP",
        True,
        None,
    )
    assert motor.sources == ("swXmlContents/Features",) and motor.configurations_used == ("Default",)
    _schema_ok("references", refs)
    assert [f["relation"] for f in refs["files"]][:2] == ["base_part", "mirrored_part"]
    assert refs["children_state"] == "none" and refs["sheets"] is None


# --------------------------------------------------------------------------- crafted trees
def test_three_levels_with_exact_ids_and_placements():
    t = TreeXml()
    t.file("2", "C:\\J\\sub1.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\sub2.SLDASM", "ASSEMBLY")
    t.file("4", "C:\\J\\part.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.model("m4", "4")
    shift = transform_text(translation=(0.1, 0, 0))
    turn_z = transform_text(((0, -1, 0), (1, 0, 0), (0, 0, 1)), (0, 0.2, 0))  # +90 degrees about Z
    t.ref("m1", "sub1", 1, "m2", transform=shift)
    t.ref("m2", "sub2", 1, "m3", transform=turn_z)
    t.ref("m3", "part", 1, "m4", transform=shift)
    with _tree(t) as doc:
        tree = doc.components()
    ids = [(n.id, n.parent, n.depth, n.children_state) for n in tree.walk()]
    assert ids == [
        ("sub1-1", None, 1, "described"),
        ("sub1-1/sub2-1", "sub1-1", 2, "described"),
        ("sub1-1/sub2-1/part-1", "sub1-1/sub2-1", 3, "none"),
    ]
    assert (tree.node_count, tree.depth, list(tree.files)) == (3, 3, ["2", "3", "4"])
    part = list(tree.walk())[2]
    assert part.transform.translation_m == (0.1, 0.0, 0.0)  # stored relative to sub2
    # in the top frame: 0.1 along sub2's X, which sub1 turned onto +Y, plus both offsets
    assert part.placement.translation_m == pytest.approx((0.1, 0.3, 0.0), abs=1e-15)
    assert part.placement.rotation == ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert part.placement.apply((1, 0, 0)) == pytest.approx((0.1, 1.3, 0.0))
    assert tree.files["2"].direct is True and tree.files["4"].direct is False


def test_rotation_layout_is_the_columns_of_r():
    """o16 o02_boxA-2 as SOLIDWORKS stored it: +90 degrees about Z, 0.1 m along X. ArrayData
    gave x_axis_image (0, 1, 0) and y_axis_image (-1, 0, 0)."""
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.model("m2", "2")
    t.top("m1")
    t.ref("m1", "p", 1, "m2", transform="0 1 0 0 -1 0 0 0 0 0 1 0 0.1 0 0 1")
    with _tree(t) as doc:
        (node,) = doc.components().children
    assert node.transform.apply((1, 0, 0)) == pytest.approx((0.1, 1.0, 0.0))  # X goes to +Y
    assert node.transform.apply((0, 1, 0)) == pytest.approx((-0.9, 0.0, 0.0))  # Y goes to -X
    assert node.transform.rotation == ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def test_composition_through_a_rotated_subassembly_matches_solidworks():
    """o16's o15_sub_asm-1 (40 degrees about (1, 1, 1), 0.1 m along Y) and its child
    o07_boxB_h31-1 (+90 degrees about X, 0.03 m along X), with the ArrayData SOLIDWORKS
    reported for the child in the top assembly."""
    a, b, c = 0.8440296287459854, 0.4490987851112869, -0.2931284138572722
    sub = f"{a} {b} {c} 0 {c} {a} {b} 0 {b} {c} {a} 0 0 0.1 0 1"
    child = "1 0 0 0 0 0 1 0 0 -1 0 0 0.03 0 0 1"
    reported = [
        0.8440296287459854, 0.4490987851112869, -0.29312841385727223,
        0.4490987851112869, -0.29312841385727223, 0.8440296287459854,
        0.29312841385727223, -0.8440296287459854, -0.4490987851112869,
        0.02532088886237956, 0.11347296355333861, -0.008793852415718166,
    ]  # fmt: skip
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", transform=sub)
    t.ref("m2", "p", 1, "m3", transform=child)
    with _tree(t) as doc:
        p = list(doc.components().walk())[1].placement
    for i in range(3):
        for j in range(3):
            assert p.rotation[i][j] == pytest.approx(reported[3 * j + i], abs=1e-12)
        assert p.translation_m[i] == pytest.approx(reported[9 + i], abs=1e-12)


def test_configurations_differ_and_are_chosen():
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.file("3", "C:\\J\\q.SLDPRT")
    t.file("4", "C:\\J\\r.SLDPRT")
    t.model("mp", "2")
    t.model("mq", "3")
    t.model("mr", "4")
    t.top("mA", "Alpha", most_recent=False)
    t.top("mB", "Beta", most_recent=True)
    t.ref("mA", "p", 1, "mp")
    t.ref("mA", "q", 1, "mq")
    t.ref("mB", "p", 1, "mp", suppressed=True, hidden=True)
    t.ref("mB", "r", 1, "mr")
    with _tree(t) as doc:  # o08's active configuration "Default" is not in this tree
        default = doc.components()
        alpha = doc.components("alpha")  # a unique case-insensitive match
        beta = doc.components("Beta")
        refs = doc.reference_set("Alpha")
        beta_refs = doc.reference_set()  # the most recent configuration, Beta
        with pytest.raises(ConfigurationNotFoundError):
            doc.components("Gamma")
        not_described = doc.components("Default")  # known from KeyWords, not in the tree
    assert (default.configuration, default.configuration_source) == ("Beta", "most_recent")
    assert (alpha.configuration, alpha.configuration_source) == ("Alpha", "requested")
    assert alpha.configurations_described == ("Alpha", "Beta")
    assert [n.id for n in alpha.walk()] == ["p-1", "q-1"] and [n.id for n in beta.walk()] == ["p-1", "r-1"]
    assert list(beta.files) == ["2", "4"] and beta.files["2"].instances_unsuppressed == 0
    counts = [
        (k, f.instances, [(c.configuration, c.instances, c.instances_in_bom) for c in f.per_configuration])
        for k, f in refs.files.items()
    ]
    assert counts == [
        ("2", 1, [("Alpha", 1, 1), ("Beta", 1, 0)]),
        ("3", 1, [("Alpha", 1, 1), ("Beta", 0, 0)]),
        ("4", 0, [("Alpha", 0, 0), ("Beta", 1, 1)]),
    ]  # fmt: skip
    assert beta_refs.configuration == "Beta"
    assert [(k, f.instances, f.instances_in_bom) for k, f in beta_refs.files.items()] == [
        ("2", 1, 0),
        ("3", 0, 0),
        ("4", 1, 1),
    ]
    assert (not_described.children_state, not_described.children, not_described.files) == ("unknown", (), {})
    assert [w.code for w in not_described.warnings] == ["configuration_not_described"]


def test_first_configuration_when_none_is_active_or_most_recent():
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.model("mp", "2")
    t.top("mA", "Alpha", most_recent=False)
    t.top("mB", "Beta", most_recent=False)
    t.ref("mA", "p", 1, "mp")
    with _tree(t) as doc:
        tree = doc.components()
    assert (tree.configuration, tree.configuration_source, tree.node_count) == ("Alpha", "first", 1)


def test_a_cycle_stops_at_once():
    t = TreeXml()
    t.file("2", "C:\\J\\a.SLDASM", "ASSEMBLY")
    t.top("m1")
    t.model("m2", "2")
    t.ref("m1", "a", 1, "m2")
    t.ref("m2", "back", 1, "m1")  # A -> B -> A
    start = time.perf_counter()
    with _tree(t) as doc:
        tree = doc.components()
    assert time.perf_counter() - start < 1.0
    assert [(n.id, n.children_state) for n in tree.walk()] == [("a-1", "described"), ("a-1/back-1", "cycle")]
    assert not tree.truncated


def _assert_the_node_limit_holds() -> None:
    """A cheap check run before the large trees below, so that a broken limit fails here
    instead of letting them build billions of nodes."""
    t = _simple(0)
    t.file("3", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.model("m3", "3")
    for k in range(1, 51):
        t.ref("m1", "sub", k, "m3")
        t.ref("m3", "p", k, "m2")
    with _tree(t) as doc:
        tree = doc.components(max_nodes=100)
    assert (tree.node_count, tree.truncated, sum(1 for _ in tree.walk())) == (100, True, 100)


def test_a_doubling_dag_30_levels_deep_is_truncated_quickly():
    _assert_the_node_limit_holds()
    t = TreeXml()
    t.top("m0")
    for level in range(1, 31):
        t.file(str(level + 1), f"C:\\J\\l{level}.SLDASM", "ASSEMBLY")
        t.model(f"m{level}", str(level + 1))
        for k in (1, 2):
            t.ref(f"m{level - 1}", f"l{level}", k, f"m{level}")
    with _tree(t) as doc:
        assert doc.metadata.tree["refs"]  # parse the tree first: the bound is on the expansion
        start = time.perf_counter()
        tree = doc.components()
        elapsed = time.perf_counter() - start
        refs = doc.reference_set()
    assert elapsed < 1.0, elapsed
    assert tree.truncated and tree.node_count == 10_000 and refs.truncated  # 2**31 - 2 without the limit
    assert any(n.children_state == "truncated" for n in tree.walk())
    with open_document(assembly_with_tree(t), name="top.SLDASM") as doc:
        shallow = doc.components(max_depth=3)
    assert shallow.truncated and shallow.node_count == 2 + 4 + 8 and shallow.depth == 3
    assert {n.children_state for n in shallow.walk() if n.depth == 3} == {"truncated"}


def test_a_million_references_hit_the_node_limit_in_time():
    """1,000 sub-assemblies of 1,000 parts each: 1,001,000 instances, stored in 2,000 elements."""
    _assert_the_node_limit_holds()
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    for k in range(1, 1001):
        t.ref("m1", "sub", k, "m2")
        t.ref("m2", "p", k, "m3")
    with _tree(t) as doc:
        start = time.perf_counter()
        tree = doc.components()
        data = model.build_components(doc, flat=True)
        elapsed = time.perf_counter() - start
    assert elapsed < 5.0, elapsed
    assert tree.truncated and tree.node_count == 10_000 and data["counts"]["nodes"] == len(data["instances"])
    f = tree.files["3"]
    assert f.instances == 10_000 - 10 and f.instances_in_bom == f.instances  # lower bounds once truncated


def test_a_reference_set_has_one_budget_for_every_configuration(monkeypatch):
    """References expand every configuration, so their total is capped, not each one
    alone: twenty configurations sharing one 600-instance model, under a cap of 1,000
    (the real cap is MAX_REFERENCE_SET_NODES)."""
    monkeypatch.setattr(components_mod, "MAX_REFERENCE_SET_NODES", 1_000)
    t = _simple(0)
    for k in range(1, 601):
        t.ref("m1", "p", k, "m2")
    for n in range(1, 20):
        t.configuration(f"C{n}", "m1", most_recent=False)
    with _tree(t) as doc:
        refs = doc.reference_set()
        alone = doc.components("C19")  # control: one configuration alone is not capped by it
    per = refs.files["2"].per_configuration
    assert len(per) == 20 and refs.truncated and alone.node_count == 600 and not alone.truncated
    assert [c.instances for c in per[:3]] == [600, 400, 0] and sum(c.instances for c in per) == 1_000
    assert MAX_REFERENCE_SET_NODES >= 100 * 725  # far above the largest corpus tree


@pytest.mark.parametrize(
    "bad",
    [
        "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0",
        "1 0 0 0 0 1 0 0 0 0 1 0 0 0 nan 1",
        "1 0 0 0 0 1 0 0 0 0 1 0 x 0 0 1",
        None,
    ],
)
def test_an_unreadable_transform_is_null_with_a_warning(bad):
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", transform=bad)
    t.ref("m2", "p", 1, "m3")
    t.ref("m1", "p", 1, "m3")  # control: a sibling with a good transform keeps its placement
    with _tree(t) as doc:
        tree = doc.components()
        data = model.build_components(doc)
    sub, inner, ok = tree.walk()
    assert sub.transform is None and sub.placement is None
    assert inner.transform is not None and inner.placement is None  # nothing to compose with
    assert ok.placement is not None
    (w,) = tree.warnings
    assert w.code == "transform_unreadable" and "1 instances" in w.message
    _schema_ok("components", data)
    assert data["warnings"] == [w.to_dict()]


def test_a_placement_that_overflows_is_null_with_a_warning():
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    huge = transform_text(((1e200, 0, 0), (0, 1e200, 0), (0, 0, 1e200)))
    t.ref("m1", "sub", 1, "m2", transform=huge)
    t.ref("m2", "p", 1, "m3", transform=huge)
    with _tree(t) as doc:
        tree = doc.components()
        data = model.build_components(doc)
    assert list(tree.walk())[1].placement is None and [w.code for w in tree.warnings] == ["non_finite_number"]
    _schema_ok("components", data)


def test_names_with_slash_percent_and_hash_get_unique_ids():
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.model("m2", "2")
    t.top("m1")
    for name in ("a/b", "a%2Fb", "a#2", "plain", "plain"):
        t.ref("m1", name, 1, "m2")
    with _tree(t) as doc:
        tree = doc.components()
    ids = [n.id for n in tree.walk()]
    assert ids == ["a%2Fb-1", "a%252Fb-1", "a%232-1", "plain-1", "plain-1#2"]
    assert len(set(ids)) == 5 and [n.name for n in tree.walk()][:3] == ["a/b-1", "a%2Fb-1", "a#2-1"]
    assert [w.code for w in tree.warnings] == ["duplicate_instance_name"]


def test_suppressed_and_excluded_parents_drop_their_children_from_the_bom():
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", suppressed=True)
    t.ref("m1", "sub", 2, "m2", excluded=True)
    t.ref("m1", "sub", 3, "m2")
    t.ref("m2", "p", 1, "m3")
    t.ref("m1", "p", 1, "m3", excluded=True)  # excluded from the BOM itself
    t.ref("m1", "p", 2, "m3")
    with _tree(t) as doc:
        tree = doc.components()
    sub, p = tree.files["2"], tree.files["3"]
    assert (sub.instances, sub.instances_unsuppressed, sub.instances_in_bom) == (3, 2, 1)
    assert (p.instances, p.instances_unsuppressed, p.instances_in_bom) == (5, 4, 2)
    excluded = [n.id for n in tree.walk() if n.excluded_from_bom]
    assert excluded == ["sub-2", "p-1"]  # flags stay as stored; only the counts follow parents


def test_hidden_follows_the_display_state_and_ignores_suppression():
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    t.top("m1", display=[(11, "No"), (12, "Yes"), (13, "Yes")])
    t.ref("m1", "p", 1, "m3", sw_id=11)  # display state says hidden, flag says not
    t.ref("m1", "p", 2, "m3", sw_id=12, suppressed=True, hidden=True)  # suppressed and shown
    t.ref("m1", "sub", 1, "m2", sw_id=13, hidden=True)  # a sub-assembly: the flag decides
    t.ref("m1", "p", 3, "m3", sw_id=14, hidden=True)  # not in the display state: the flag
    t.ref("m2", "p", 1, "m3", sw_id=11, hidden=True, suppressed=True)  # nested: never the top list
    t.ref("m2", "p", 2, "m3", sw_id=12, hidden=True)
    with _tree(t) as doc:
        nodes = {n.id: n for n in doc.components().walk()}
        (old,) = [r for r in doc.references() if r.file_name == "p.SLDPRT"]
    assert {i: n.hidden for i, n in nodes.items()} == {
        "p-1": True,
        "p-2": False,
        "sub-1": True,
        "sub-1/p-1": False,
        "sub-1/p-2": True,
        "p-3": True,
    }
    # the 0.1 list agrees; it holds the instances in stored order, sub-assembly first here
    assert [i.hidden for i in old.instances] == [False, True, True, False, True]


def test_a_sub_assembly_is_hidden_by_its_flag_not_its_display_state():
    # A sub-assembly's swShowState is No for sub-assemblies SOLIDWORKS draws (each such
    # corpus instance holds something hidden), so its swHidden flag decides both ways.
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    t.top("m1", display=[(11, "No"), (12, "Yes"), (13, "No")])
    t.ref("m1", "sub", 1, "m2", sw_id=11)  # display state No, flag clear: shown
    t.ref("m1", "sub", 2, "m2", sw_id=12, hidden=True)  # display state Yes, flag set: hidden
    t.ref("m1", "p", 1, "m3", sw_id=13)  # a part: its display state still decides
    t.ref("m2", "p", 1, "m3", sw_id=11)
    t.ref("m2", "p", 2, "m3", sw_id=12, hidden=True)
    with _tree(t) as doc:
        nodes = {n.id: n.hidden for n in doc.components().walk()}
        counts = doc.display_geometry().counts
    assert nodes == {
        "sub-1": False,
        "sub-1/p-1": False,
        "sub-1/p-2": True,
        "sub-2": True,
        "sub-2/p-1": False,
        "sub-2/p-2": True,
        "p-1": True,
    }
    # what a hidden sub-assembly holds is not drawn: sub-1/p-2, both parts of sub-2, p-1
    assert (counts["parts"], counts["hidden"]) == (5, 4)


def test_without_a_display_state_a_suppressed_instance_is_not_hidden():
    t = _simple(0)
    t.ref("m1", "p", 1, "m2", suppressed=True, hidden=True)
    t.ref("m1", "p", 2, "m2", hidden=True)
    with _tree(t) as doc:
        assert [n.hidden for n in doc.components().walk()] == [False, True]


def test_a_missing_model_and_the_depth_limit():
    t = TreeXml()
    t.file("2", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("3", "C:\\J\\p.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "ghost", 1, "m9")
    t.ref("m1", "sub", 1, "m2")
    t.ref("m2", "p", 1, "m3")
    with _tree(t) as doc:
        tree = doc.components()
        flat = doc.components(max_depth=1)
    assert [(n.id, n.file, n.children_state) for n in tree.walk()] == [
        ("ghost-1", None, "unknown"),
        ("sub-1", "2", "described"),
        ("sub-1/p-1", "3", "none"),
    ]
    assert [w.code for w in tree.warnings] == ["component_model_missing"] and not tree.truncated
    assert [n.children_state for n in flat.walk()] == ["unknown", "truncated"] and flat.truncated


def test_an_empty_subassembly_is_described():
    t = TreeXml()
    t.file("2", "C:\\J\\empty.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.top("m1")
    t.ref("m1", "empty", 1, "m2")
    with _tree(t) as doc:
        (node,) = doc.components().children
    assert (node.children_state, node.children, node.doc_type) == ("described", (), "assembly")


@pytest.mark.parametrize(
    ("kwargs", "parameter"),
    [
        ({"max_nodes": 0}, "max_nodes"),
        ({"max_nodes": MAX_NODES_LIMIT + 1}, "max_nodes"),
        ({"max_nodes": True}, "max_nodes"),
        ({"max_nodes": 10.0}, "max_nodes"),
        ({"max_depth": 0}, "max_depth"),
        ({"max_depth": MAX_DEPTH_LIMIT + 1}, "max_depth"),
    ],
)
def test_limits_are_checked(kwargs, parameter):
    with open_document(O08) as doc:
        with pytest.raises(InvalidArgumentError) as info:
            doc.components(**kwargs)
        assert info.value.detail == {"parameter": parameter}
        with pytest.raises(InvalidArgumentError):
            model.build_components(doc, **kwargs)
    with open_document(fixture_path(PARTS[0])) as doc:  # refused on a part too
        with pytest.raises(InvalidArgumentError):
            model.build_components(doc, **kwargs)


def test_the_deepest_allowed_tree_encodes():
    t = TreeXml()
    t.top("m0")
    for level in range(1, MAX_DEPTH_LIMIT + 1):
        t.file(str(level + 1), f"C:\\J\\l{level}.SLDASM", "ASSEMBLY")
        t.model(f"m{level}", str(level + 1))
        t.ref(f"m{level - 1}", f"l{level}", 1, f"m{level}")
    with _tree(t) as doc:
        data = model.build_components(doc, max_depth=MAX_DEPTH_LIMIT)
    assert data["counts"]["depth"] == MAX_DEPTH_LIMIT and not data["truncated"]
    _schema_ok("components", data)


# --------------------------------------------------------------------------- virtual and imported components
def _embedded_assembly():
    t = TreeXml()
    t.file("2", "C:\\Temp\\VC~~\\top\\Part1^top.SLDPRT", "PART")
    t.file("3", "C:\\Temp\\VC~~\\top\\Part2^top.SLDPRT", "PART")
    t.file("4", "C:\\Temp\\VC~~\\top\\Part3^top.SLDPRT", "PART")
    t.file("5", "C:\\J\\sub.SLDASM", "ASSEMBLY")
    t.file("6", "C:\\Temp\\VC~~\\sub\\Part9^sub.SLDPRT", "PART")
    t.file("7", "C:\\J\\imported.SLDPRT", "PART", swImportedPath="C:\\Import\\imported.step")
    t.file("8", "C:\\J\\elsewhere.SLDPRT", "PART", swImportedPath="C:\\Import\\elsewhere.step")
    t.top("m1")
    for mid, fid in (
        ("m2", "2"),
        ("m3", "3"),
        ("m4", "4"),
        ("m5", "5"),
        ("m6", "6"),
        ("m7", "7"),
        ("m8", "8"),
    ):
        t.model(mid, fid)
    t.ref("m1", "Part1^top", 1, "m2", virtual=True)
    t.ref("m1", "Part2^top", 1, "m3", virtual=True)
    t.ref("m1", "Part3^top", 1, "m4", virtual=True)
    t.ref("m1", "sub", 1, "m5")
    t.ref("m5", "Part9^sub", 1, "m6", virtual=True)
    t.ref("m1", "imported", 1, "m7")
    t.ref("m1", "elsewhere", 1, "m8")
    part = O04.read_bytes()
    members = {
        "VirtualComp/Part1": part,  # the older form: the stored name before the caret
        "VirtualComp/Part2-sldprt": part,  # SOLIDWORKS 2024: plus the extension
        "ImportedComp/imported.SLDPRT": part,
    }
    return assembly_with_tree(t, members)


def test_virtual_and_imported_files_map_to_their_nested_documents():
    with open_document(_embedded_assembly(), name="top.SLDASM") as doc:
        files = doc.reference_set().files
        nested_names = doc.nested_documents()
    got = {f.file_name: (f.virtual, f.imported, f.direct, f.nested, f.embedded, f.embedded_in_subassembly)
           for f in files.values()}  # fmt: skip
    assert got == {
        "Part1^top.SLDPRT": (True, False, True, "VirtualComp/Part1", "embedded", False),
        "Part2^top.SLDPRT": (True, False, True, "VirtualComp/Part2-sldprt", "embedded", False),
        "Part3^top.SLDPRT": (True, False, True, None, "embedded_not_found", False),
        "sub.SLDASM": (False, False, True, None, None, False),
        "Part9^sub.SLDPRT": (True, False, False, None, "embedded_in_subassembly", True),
        "imported.SLDPRT": (False, True, True, "ImportedComp/imported.SLDPRT", "embedded", False),
        "elsewhere.SLDPRT": (False, True, True, None, None, False),
    }
    assert sorted(nested_names) == [
        "ImportedComp/imported.SLDPRT",
        "VirtualComp/Part1",
        "VirtualComp/Part2-sldprt",
    ]


def test_a_nested_stream_is_claimed_by_one_file_only():
    t = TreeXml()
    t.file("2", "C:\\T\\Part1^top.SLDPRT")
    t.file("3", "C:\\T\\Part1^other.SLDPRT")  # the same name before the caret
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "Part1^top", 1, "m2", virtual=True)
    t.ref("m1", "Part1^other", 1, "m3", virtual=True)
    with open_document(
        assembly_with_tree(t, {"VirtualComp/Part1": O04.read_bytes()}), name="a.SLDASM"
    ) as doc:
        files = doc.components().files
    assert [(f.nested, f.embedded) for f in files.values()] == [
        ("VirtualComp/Part1", "embedded"),
        (None, "embedded_not_found"),
    ]


def test_nested_on_summary_properties_and_preview():
    with open_document(_embedded_assembly(), name="top.SLDASM") as doc, open_document(O04) as part:
        name = "VirtualComp/Part2-sldprt"
        summary = doc.summary(nested=name)
        assert summary == model.build_document_summary(doc, nested=name)
        assert summary["doc_type"] == "part" and summary["file"]["name"] == "Part2-sldprt"
        assert summary["properties"] == part.summary()["properties"] and summary["properties"]
        assert model.build_properties(doc, nested=name) == model.build_properties(part)
        assert doc.property_values(nested=name) == part.property_values()
        assert doc.preview(nested=name).data == part.preview().data
        assert doc.nested(name) is doc.nested(name)  # opened once
        assert doc.summary()["doc_type"] == "assembly"  # control: without nested, the assembly
        with pytest.raises(StreamNotFoundError) as info:
            doc.summary(nested="VirtualComp/Nope")
        assert info.value.detail == {"parameter": "nested"}
        with pytest.raises(InvalidArgumentError):
            doc.preview(nested=3)
    assert doc._nested == {}  # closed with the parent


# --------------------------------------------------------------------------- without a tree, and drawings
def test_an_assembly_without_a_tree_lists_header2_files_with_unknown_children():
    data = rebuild(O08, drop=("swXmlContents/COMPINSTANCETREE",))
    with open_document(data, name="frame.SLDASM") as doc:
        tree = doc.components()
        refs = model.build_references(doc)
        comps = model.build_components(doc)
    assert (tree.children_state, tree.children, tree.configuration, tree.configuration_source) == (
        "unknown",
        (),
        "Default",
        "active",
    )
    (f,) = tree.files.values()
    assert (f.key, f.file_name, f.direct, f.instances, f.sources) == (
        "header2:1",
        "o02_boxA.SLDPRT",
        None,
        None,
        ("Header2",),
    )
    assert [x["key"] for x in refs["files"]] == ["header2:1"] and refs["children_state"] == "unknown"
    _schema_ok("references", refs)
    _schema_ok("components", comps)


def _drawing(keywords: bytes | None, names: bytes | None, *, name="sheet.SLDDRW") -> bytes:
    changes = {}
    if keywords is not None:
        changes["swXmlContents/KeyWords"] = keywords
    if names is not None:
        changes["SheetPreviews/SheetNames"] = names
    drop = ("Contents/Definition", "swXmlContents/COMPINSTANCETREE")
    return rebuild(O08, changes, drop=drop + (() if keywords is not None else ("swXmlContents/KeyWords",)))


def test_a_drawing_lists_its_models_sheets_and_views():
    kw = drawing_keywords(
        {
            "Sheet1": [
                ("Drawing View1", "Default", "o02_boxA.sldprt"),
                ("Drawing View2", "Long", "o02_boxA.sldprt"),
            ],
            "Sheet2": [("Drawing View3", "Default", "other.sldprt")],
            "Old": [],
        }
    )
    with open_document(_drawing(kw, sheet_names(["Sheet1", "Sheet2"])), name="sheet.SLDDRW") as doc:
        assert doc.doc_type == "drawing" and doc.active_configuration is None  # o08 stored "Default"
        assert doc.components() is None
        refs = model.build_references(doc)
        sheets = doc.sheets()
        with pytest.raises(ConfigurationNotFoundError):  # a drawing has no configurations
            model.build_references(doc, configuration="Default")
    _schema_ok("references", refs)
    (f,) = refs["files"]
    assert (f["key"], f["file_name"], f["direct"], f["instances"]) == (
        "header2:1",
        "o02_boxA.SLDPRT",
        None,
        None,
    )
    assert f["configurations_used"] == ["Default", "Long"]
    assert f["sources"] == ["Header2", "swXmlContents/KeyWords"]
    def view(name, configuration, file_name, file):
        return {"name": name, "configuration": configuration, "file_name": file_name, "file": file}

    assert refs["sheets"] == [
        {
            "name": "Sheet1",
            "views": [
                view("Drawing View1", "Default", "o02_boxA.sldprt", "header2:1"),
                view("Drawing View2", "Long", "o02_boxA.sldprt", "header2:1"),
            ],
        },
        {"name": "Sheet2", "views": [view("Drawing View3", "Default", "other.sldprt", None)]},
    ]
    assert [s.name for s in sheets] == ["Sheet1", "Sheet2"]  # "Old" is in KeyWords but not a sheet


def test_a_drawing_without_a_sheet_list_uses_keyword_sheets_with_views():
    kw = drawing_keywords({"Sheet1": [("V", "Default", "o02_boxA.sldprt")], "Format": []})
    with open_document(_drawing(kw, b"\x05\x00\xff"), name="sheet.SLDDRW") as doc:
        refs = model.build_references(doc)
    assert [s["name"] for s in refs["sheets"]] == ["Sheet1"]
    assert [w["code"] for w in refs["warnings"]] == ["drawing_sheets_unreadable"]
    with open_document(_drawing(None, None), name="sheet.SLDDRW") as doc:
        bare = model.build_references(doc)
    assert bare["sheets"] == [] and [f["file_name"] for f in bare["files"]] == ["o02_boxA.SLDPRT"]


def test_sheet_names_parse():
    assert parse_sheet_names(sheet_names(["Sheet1", "Детали"])) == ["Sheet1", "Детали"]
    assert parse_sheet_names(b"\x01\x00\xff\xfe\xff\x06S\x00h\x00e\x00e\x00t\x001\x00\x00\x00") == ["Sheet1"]
    for bad in (b"", b"\x01", b"\x02\x00\xff\xfe\xff\x01A\x00", b"\xff\xff" + b"\x00" * 10):
        assert parse_sheet_names(bad) is None


# --------------------------------------------------------------------------- 0.1 references
def test_reference_quantity_is_deprecated_but_still_answers():
    with open_document(O08) as doc:
        (ref,) = doc.references()
        replacement = doc.reference_set().files[ref.key].instances
    with pytest.warns(SolidSeasDeprecationWarning, match=r"reference_set\(configuration\)\.files"):
        assert ref.quantity == 2 == replacement
    assert issubclass(SolidSeasDeprecationWarning, DeprecationWarning)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(ref.instances) == 2 and ref.key is not None  # the rest of the object never warns


def test_the_replacement_for_quantity_answers_for_every_reference():
    """What the deprecation warning names must work wherever ``quantity`` did: a file the
    chosen configuration does not use counts 0, and a drawing's model has no count (None),
    rather than raising KeyError or AttributeError as ``components()`` does."""
    t = TreeXml()
    t.file("2", "C:\\J\\p.SLDPRT")
    t.file("3", "C:\\J\\q.SLDPRT")
    t.model("mp", "2")
    t.model("mq", "3")
    t.top("mA", "Alpha", most_recent=False)
    t.top("mB", "Beta", most_recent=True)
    t.ref("mA", "p", 1, "mp")
    t.ref("mA", "p", 2, "mp")
    t.ref("mB", "q", 1, "mq")
    with _tree(t) as doc:
        refs = doc.references()
        alpha = doc.reference_set("Alpha")
        assert "3" not in doc.components("Alpha").files  # what the old advice would have looked up
        got = {r.key: alpha.files[r.key].instances for r in refs}
        per = {k: [(c.configuration, c.instances) for c in f.per_configuration]
               for k, f in alpha.files.items()}
    assert got == {"2": 2, "3": 0}
    assert per == {"2": [("Alpha", 2), ("Beta", 0)], "3": [("Alpha", 0), ("Beta", 1)]}
    kw = drawing_keywords({"Sheet1": [("Drawing View1", "Default", "o02_boxA.sldprt")]})
    with open_document(_drawing(kw, sheet_names(["Sheet1"])), name="sheet.SLDDRW") as doc:
        (ref,) = doc.references()
        assert doc.components() is None and doc.reference_set().files[ref.key].instances is None


# --------------------------------------------------------------------------- command line
def _run(capsys, *argv):
    import json

    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_cli_components_and_references(capsys):
    code, env = _run(capsys, "components", str(O08))
    assert code == 0 and env["kind"] == "components" and env["source"] == {"file": str(O08)}
    assert not validate(env, model.envelope_schema("components"), strict=True)
    with open_document(O08) as doc:
        assert env["data"] == model.build_components(doc)
    code, env = _run(capsys, "components", str(O08), "--flat", "--max-nodes", "1", "--max-depth", "2")
    assert code == 0 and env["data"]["truncated"] and len(env["data"]["instances"]) == 1
    code, env = _run(capsys, "references", str(O08))
    assert code == 0 and env["kind"] == "references" and env["data"]["files"][0]["instances"] == 2
    code, env = _run(capsys, "components", str(O08), "--configuration", "Nope")
    assert code == 1 and env["error"]["code"] == "configuration_not_found"
    code, env = _run(capsys, "components", str(O08), "--max-nodes", "0")
    assert code == 2 and env["error"]["code"] == "invalid_argument"
    code, env = _run(capsys, "components", str(O08), "--max-depth", str(MAX_DEPTH_LIMIT + 1))
    assert code == 2 and env["error"]["detail"] == {"parameter": "max_depth"}


def test_cli_nested(capsys, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    asm = src / "top.SLDASM"
    asm.write_bytes(_embedded_assembly())
    name = "VirtualComp/Part1"
    code, env = _run(capsys, "info", str(asm), "--nested", name)
    assert code == 0 and env["source"] == {"file": str(asm), "nested": name}
    assert env["data"]["doc_type"] == "part"
    code, env = _run(capsys, "props", str(asm), "--nested", name, "--view", "file")
    with open_document(O04) as part:
        assert code == 0 and env["data"] == model.build_properties(part, view="file")
    (tmp_path / "out").mkdir()
    code, env = _run(capsys, "preview", str(asm), "--nested", name, "-o", str(tmp_path / "out"))
    assert code == 0 and env["data"]["output"].endswith("top_Part1.png")
    code, env = _run(capsys, "info", str(asm), "--nested", "VirtualComp/Nope")
    assert code == 1 and env["error"]["code"] == "stream_not_found"


def test_cli_text_output(capsys):
    assert cli.main(["components", str(O08)]) == 0
    out = capsys.readouterr().out
    assert "o02_boxA-1" in out and "2 instances of 1 files" in out
    assert cli.main(["references", str(O08)]) == 0
    assert "o02_boxA.SLDPRT  2 in BOM of 2" in capsys.readouterr().out
    assert cli.main(["components", str(fixture_path(PARTS[1]))]) == 0
    assert "no components" in capsys.readouterr().out


def test_transform_text_helper_round_trips():
    """The builder writes what the reader decodes (columns of R in 0-2, 4-6, 8-10)."""
    from solidseas.formats.solidworks.components import parse_transform

    rows = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    t = parse_transform(transform_text(rows, (1, 2, 3)))
    assert t.rotation == rows and t.translation_m == (1.0, 2.0, 3.0) and t.scale == 1.0
    assert parse_transform(IDENTITY_TRANSFORM).stored == tuple(float(x) for x in IDENTITY_TRANSFORM.split())
    assert parse_transform("1 " * 5000) is None and math.isfinite(t.stored[0])
