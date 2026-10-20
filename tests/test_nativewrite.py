"""The native writer's offline parts: the container writer, the feature stream and the candidates.

Nothing here needs SOLIDWORKS. What SOLIDWORKS makes of the candidates is the
PC's check (``scripts/sw-checks/native-writer.py``); these tests pin what is
true of the files before SOLIDWORKS sees them.
"""

import json
import math
import os
import random
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from solidseas.formats.solidworks import open_document
from solidseas.formats.solidworks.container import open_container
from solidseas.formats.solidworks.zlb import iter_zlb_chain
from solidseas.nativewrite.container import (
    ContainerWriteError,
    build_container,
    deflate_member,
    patch_in_place,
    read_document,
    with_changes,
    write_new_file,
)
from swnative import experiments as E
from swnative import features as F

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
MODERN = sorted(p for p in FIXTURES.iterdir() if p.suffix.upper() in (".SLDPRT", ".SLDASM", ".SLDDRW"))
PARTS = [p for p in MODERN if p.suffix.upper() == ".SLDPRT"]


def _members(blob: bytes) -> list[tuple[str, bytes]]:
    with open_container(blob) as c:
        return [(s.name, c.read(s.name)) for s in c.streams()]


@pytest.mark.parametrize("path", MODERN, ids=lambda p: p.stem)
def test_every_fixture_rebuilds_and_patches_to_the_same_members(path):
    doc = read_document(path)
    want = [(m.name, m.data) for m in doc.members]
    # zlib level 1 raw deflate is what SOLIDWORKS stores: every member compresses to its stored bytes.
    assert all(deflate_member(m.data) == m.stored for m in doc.members)
    rebuilt = build_container(doc.members, key=doc.key, signatures=doc.signatures)
    assert _members(rebuilt) == want
    assert rebuilt[:8] == doc.raw[:8]
    assert _members(patch_in_place(doc, {})) == want


def test_rebuild_has_no_decoys_and_keeps_unchanged_stored_bytes():
    doc = read_document(FIXTURES / "o02_boxA.SLDPRT")
    blob = build_container(doc.members, key=doc.key, signatures=doc.signatures)
    with open_container(blob) as c:
        assert c.meta["first_local_header"] == 8
        assert c.meta["tail_bytes"] == 0 and c.meta["cd_slack"] == 0
        assert c.signatures_match_lcg()
        for m in doc.members:
            assert c.read_raw(m.name) == m.stored


def test_patch_keeps_every_byte_before_the_directory_and_moves_a_grown_member():
    doc = read_document(FIXTURES / "o02_boxA.SLDPRT")
    name = "Contents/Config-0-ResolvedFeatures"
    noisy = random.Random(7).randbytes(16384)  # does not compress, so it no longer fits
    out = patch_in_place(doc, {name: noisy})
    lfh, _data, _size = doc.offsets[name]
    assert out[: doc.cd_offset] == doc.raw[: doc.cd_offset]  # the old span is left as it was
    with open_container(out) as c:
        assert c.read(name) == noisy
        assert c.info(name).offset >= doc.cd_offset
    small = patch_in_place(doc, {"Contents/CnfgObjs": b"\0" * 12})
    with open_container(small) as c:
        assert c.info("Contents/CnfgObjs").offset == doc.offsets["Contents/CnfgObjs"][0]


def test_changes_add_and_drop_members_and_refuse_bad_names():
    doc = read_document(FIXTURES / "o01_empty.SLDPRT")
    ms = with_changes(doc.members, {"Contents/DisplayLists": None, "Extra/Thing": b"x"})
    names = [n for n, _ in _members(build_container(ms, key=doc.key))]
    assert "Contents/DisplayLists" not in names and names[-1] == "Extra/Thing"
    with pytest.raises(ContainerWriteError):
        build_container(ms + ms[:1], key=doc.key)
    with pytest.raises(ContainerWriteError):
        patch_in_place(doc, {"Not/There": b""})


def test_write_new_file_never_replaces(tmp_path):
    target = tmp_path / "a.sldprt"
    write_new_file(target, b"one")
    with pytest.raises(FileExistsError):
        write_new_file(target, b"two")
    assert target.read_bytes() == b"one"
    assert not list(tmp_path.glob("*.partial"))


# ------------------------------------------------------------------ the feature stream
def _keyword_dimensions(path: Path) -> dict[str, float]:
    """``D1@Feature`` values from the KeyWords XML, the display mirror, in millimetres."""
    with open_container(path) as c:
        text = c.read("swXmlContents/KeyWords")[1:].decode("utf-8")
    out = {}
    for m in re.finditer(
        r'<\w+ id="\d+" Name="([^"]+)"[^>]*>((?:<Dimension Name="D\d+">[^<]*</Dimension>)+)', text
    ):
        for dm in re.finditer(r'<Dimension Name="(D\d+)">([^<]*)</Dimension>', m.group(2)):
            out[f"{dm.group(1)}@{m.group(1)}"] = float(re.search(r"-?[\d.]+", dm.group(2)).group())
    return out


@pytest.mark.parametrize("path", PARTS, ids=lambda p: p.stem)
def test_driving_parameters_match_the_keywords_mirror(path):
    with open_container(path) as c:
        if "Contents/Config-0-ResolvedFeatures" not in c:
            pytest.skip("no feature stream")
        params = F.parameters(c.read("Contents/Config-0-ResolvedFeatures"))
    mirror = _keyword_dimensions(path)
    assert {p.full_name: round(p.value * 1000, 9) for p in params} == mirror


def test_feature_stream_header_counts_the_top_level_features():
    for name, count in (("o01_empty", 17), ("o02_boxA", 19), ("o11_curved", 23), ("o12_multibody", 21)):
        d = read_document(FIXTURES / f"{name}.SLDPRT").data(E.FEATURES)
        assert F.header(d)[1] == count
        assert F.named_nodes(d)[0].name == "Comments"


def test_o02_sketch_points_are_the_rectangle():
    d = read_document(FIXTURES / "o02_boxA.SLDPRT").data(E.FEATURES)
    corners = {(round(p.x, 9), round(p.y, 9)) for p in F.sketch_points(d)}
    assert corners == {(0.0, 0.0), (0.01, 0.0), (0.01, 0.02), (0.0, 0.02)}


def test_o13_configurations_differ_in_the_parameter_and_caches_only():
    with open_container(FIXTURES / "o13_two_geometry_configs.SLDPRT") as c:
        a, b = c.read("Contents/Config-0-ResolvedFeatures"), c.read("Contents/Config-1-ResolvedFeatures")
    assert F.parameter(a, E.DEPTH).value == 0.030 and F.parameter(b, E.DEPTH).value == 0.045
    assert F.parameter(a, E.DEPTH).value_offset == F.parameter(b, E.DEPTH).value_offset
    # Setting Default's depth to Tall's, with its dimension's copies, leaves only plane sizes,
    # the box centre and flag bits apart.
    moved = E.set_depth(a, 0.045, mirrors=True)
    left = [i for i in range(len(a)) if moved[i] != b[i]]
    recs = F.class_records(a)
    owners = {F._record_at(recs, i) for i in left}
    assert owners <= {
        "moDefaultRefPlnData_c",
        "moProfileFeature_c",
        "moExtrusion_c",
        "moBBoxCenterData_c",
        "moLengthParameter_c",
    }


# ------------------------------------------------------------------ the candidates
@pytest.fixture(scope="module")
def cands():
    return {c.name: c for c in E.candidates()}


def test_candidates_read_back_with_the_intended_values(cands):
    assert {n for n, c in cands.items() if c.question != "M"} == {
        "x0-source",
        "x1-rebuilt-container",
        "x2-patched-container",
        "a1-depth-parameter-only",
        "a2-depth-with-mirrors",
        "a3-depth-consistent",
        "c1-no-partition",
        "c2-empty-partition",
        "c3-no-display-lists",
        "s1-sketch-width-12",
        "s2-width-and-depth",
        "p1-solidcraft-rect",
        "p2-solidcraft-rect-no-partition",
        "b1-features-from-o12",
        "b2-features-from-o12-no-partition",
        "b3-o02-features-in-o01",
        "b4-o02-features-in-o01-40x30x10",
    }
    for c in cands.values():
        if c.question in ("B", "M"):
            continue
        with open_container(c.data) as cc:
            feats = cc.read(E.FEATURES)
            names = cc.names()
        assert F.parameter(feats, E.DEPTH).value == pytest.approx(c.box_m[2])
        xs = {round(p.x, 9) for p in F.sketch_points(feats) if p.record == "sgLineHandle"}
        assert max(xs) == pytest.approx(c.box_m[0])
        for gone in c.dropped:
            assert gone not in names
    assert cands["x0-source"].data == (FIXTURES / "o02_boxA.SLDPRT").read_bytes()


def test_depth_with_mirrors_moves_the_dimension_copies_and_nothing_else(cands):
    src = read_document(FIXTURES / "o02_boxA.SLDPRT").data(E.FEATURES)
    with open_container(cands["a2-depth-with-mirrors"].data) as c:
        new = c.read(E.FEATURES)
        kw = c.read(E.KEYWORDS)
    changed = [i for i in range(len(src)) if src[i] != new[i]]
    start, end = F.feature_span(src, "Boss-Extrude1")
    assert changed and all(start <= i < end for i in changed)
    assert b'<Dimension Name="D1">31</Dimension>' in kw


def test_consistent_partition_matches_o07_but_for_resave_noise(cands):
    with open_container(cands["a3-depth-consistent"].data) as c:
        got = list(iter_zlb_chain(c.read(E.PARTITION)))
    with open_container(FIXTURES / "o07_boxB_h31.SLDPRT") as c:
        want = list(iter_zlb_chain(c.read(E.PARTITION)))
    assert [len(b) for b in got] == [len(b) for b in want]
    assert got[1] == want[1]
    diff = [i for i in range(len(got[0])) if got[0][i] != want[0][i]]
    assert len(diff) < 60  # o02 and o03, one model saved twice, differ in 118 bytes here
    depth = struct.pack(">d", 0.031)
    hits = [m.start() for m in re.finditer(re.escape(depth), got[0])]
    assert len(hits) == 17 and not any(h <= i < h + 8 for h in hits for i in diff)
    # The document reader still finds one body in it.
    with open_document(cands["a3-depth-consistent"].data) as doc:
        assert len(doc.parasolid().bodies) == 1


def test_main_writes_without_solidworks_modules(tmp_path):
    out = tmp_path / "candidates"
    run = subprocess.run(
        [sys.executable, "-m", "swnative.experiments", "--out", str(out)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "research")])},
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(run.stdout)
    assert report["solidworks_modules_loaded"] == []
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["made_without_solidworks"] is True
    assert {c["file"] for c in manifest["candidates"]} == {p.name for p in out.glob("*.sldprt")}
    with pytest.raises(FileExistsError):
        E.write_candidates(out)


def _snapshot(volume, depth=0.031, extra=None):
    feats = [
        {"name": "Sketch1", "type": "ProfileFeature", "error": 0, "error_is_warning": False},
        {
            "name": "Boss-Extrude1",
            "type": "Extrusion",
            "error": 0,
            "error_is_warning": False,
            "extrude": {"depth": depth},
        },
    ]
    return {"features": feats + (extra or []), "whats_wrong": [], "measure": {"mass": {"volume_m3": volume}}}


def test_judge_calls_a_rebuilt_edited_reopened_part_editable(cands):
    c = cands["a2-depth-with-mirrors"].manifest()
    report = {
        "opened": True,
        "check": {
            "opened": _snapshot(6.0e-6),
            "rebuilt": _snapshot(6.2e-6),
            "edit": {"found": True, "snapshot": _snapshot(6.6e-6, 0.033)},
            "saved": {"ok": True},
        },
        "reopened": {"check": {"rebuilt": _snapshot(6.6e-6, 0.033)}},
    }
    v = E.judge(c, report)
    assert v["verdict"] == "editable" and v["volume_as_opened"] == 6.0e-6
    stale = dict(report, check=dict(report["check"], rebuilt=_snapshot(6.0e-6)))
    assert E.judge(c, stale)["verdict"] == "native"
    imported = dict(
        report, check=dict(report["check"], rebuilt=_snapshot(6.2e-6, extra=[{"type": "MBimport"}]))
    )
    assert E.judge(c, imported)["verdict"] == "not-native"
    assert E.judge(c, {"opened": False, "open_error": "open_failed"})["verdict"] == "refused"


# ------------------------------------------------------------------ the IR, SolidCraft and the seed writer
from solidseas.nativewrite import ir  # noqa: E402
from solidseas.nativewrite import solidcraft as SC  # noqa: E402
from swnative import writer as W  # noqa: E402

RECT_SAMPLE = FIXTURES / "solidcraft" / "rect-extrude-40x30x10.solidcraft"


def test_solidcraft_sample_translates_with_its_intent():
    doc = SC.read_ir(RECT_SAMPLE)
    sk, ex, fillet = doc.features
    assert isinstance(sk, ir.Sketch) and sk.plane.base == "xy"
    assert {(p.id, round(p.x, 9), round(p.y, 9)) for p in sk.points} == {
        ("p1", 0.0, 0.0),
        ("p2", 0.04, 0.0),
        ("p3", 0.04, 0.03),
        ("p4", 0.0, 0.03),
    }
    assert [c.points for c in sk.curves] == [["p1", "p2"], ["p2", "p3"], ["p3", "p4"], ["p4", "p1"]]
    assert sorted(k.kind for k in sk.constraints) == [
        "coincident",
        "horizontal",
        "horizontal",
        "vertical",
        "vertical",
    ]
    assert sk.constraints[0].points == [ir.ORIGIN, "p1"]
    dims = {d.parameter: (d.kind, d.curves, round(d.value, 9)) for d in sk.dimensions}
    assert dims == {"d1": ("length", ["l1"], 0.04), "d2": ("length", ["l2"], 0.03)}
    assert (ex.depth, ex.direction, ex.operation, ex.profile) == (
        0.01,
        "forward",
        "new_body",
        [["l1", "l2", "l3", "l4"]],
    )
    assert ex.depth_parameter == "d3"
    params = {p.name: (round(p.value, 9), p.expression) for p in doc.parameters}
    assert params["width"] == (0.04, "40 mm") and params["d1"] == (0.04, "width") and params["d3"][0] == 0.01
    assert (
        isinstance(fillet, ir.Fillet)
        and fillet.radius == 0.002
        and fillet.edges[0].point == (0.04, 0.015, 0.01)
    )
    # The IR round-trips through JSON.
    assert ir.from_json(ir.to_json(doc)) == doc


@pytest.mark.parametrize(
    ("text", "unit", "want"),
    [
        ("40 mm", "mm", 0.04),
        ("2.5 cm + 5", "mm", 0.03),
        ("1 in", "mm", 0.0254),
        ("width / 2", "mm", 0.02),
        ("90", "deg", 1.5707963267948966),
        ("sqrt(9) * 2", "mm", 0.006),
        ("10,5", "mm", 0.0105),
    ],
)
def test_solidcraft_expressions(text, unit, want):
    ex = SC.Expressions([{"name": "width", "expr": "40 mm", "unit": "mm"}])
    assert ex.eval(text, unit) == pytest.approx(want)


@pytest.mark.parametrize("text", ["__import__('os')", "width.real", "[1]", "a if b else c", "lambda: 1"])
def test_solidcraft_expressions_refuse_anything_else(text):
    with pytest.raises(SC.SolidCraftError):
        SC.Expressions([]).eval(text)


def test_solidcraft_zip_container_and_refusals(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("container.json", '{"format":"solidcraft-container/1"}')
        z.writestr("document.json", RECT_SAMPLE.read_bytes())
    assert SC.read_ir(buf.getvalue()).name == "rect-extrude-40x30x10"
    with pytest.raises(SC.SolidCraftError):
        SC.load(b'{"format":"solidcraft/99","features":[]}')
    with pytest.raises(SC.SolidCraftError):
        SC.load(b"not json")


def test_ir_validation_catches_broken_references():
    doc = SC.read_ir(RECT_SAMPLE)
    sk = doc.features[0]
    sk.curves[0].points = ["p1", "nowhere"]
    with pytest.raises(ir.IRError):
        ir.validate(doc)


def test_ir_file_properties_round_trip_and_are_checked():
    props = [ir.Property("PartNo", "SS-1001"), ir.Property("Qty", 42, "number"),
             ir.Property("Released", "2026-10-20", "date"), ir.Property("Bought", False, "yesno")]
    doc = ir.from_json(ir.to_json(ir.Document("bracket", properties=props)))
    assert doc.properties == props
    for bad in ([ir.Property("PartNo", "a"), ir.Property("partno", "b")], [ir.Property(" ", "a")],
                [ir.Property("Qty", "42", "number")], [ir.Property("Qty", math.inf, "number")],
                [ir.Property("Released", "10/20/2026", "date")], [ir.Property("Bought", "No", "yesno")],
                [ir.Property("Colour", "red", "colour")], [ir.Property("Name", 3)]):
        with pytest.raises(ir.IRError):
            ir.validate(ir.Document("bad", properties=bad))


def test_seed_writer_refuses_what_it_cannot_hold_and_writes_the_rest_when_asked():
    doc = SC.read_ir(RECT_SAMPLE)
    with pytest.raises(W.NativeWriteUnsupported) as e:
        W.write_sldprt(doc)
    assert len(e.value.items) == 3 and any("Fillet1" in i for i in e.value.items)
    data, rep = W.write_sldprt(doc, allow_partial=True)
    assert rep.box_m == (0.04, 0.03, 0.01) and not rep.validated and len(rep.left_out) == 3
    with open_container(data) as c:
        feats, kw = c.read(E.FEATURES), c.read(E.KEYWORDS)
    assert F.parameter(feats, E.DEPTH).value == 0.01
    corners = {(round(p.x, 9), round(p.y, 9)) for p in F.sketch_points(feats)}
    assert corners == {(0.0, 0.0), (0.04, 0.0), (0.04, 0.03), (0.0, 0.03)}
    assert b'<Dimension Name="D1">10</Dimension>' in kw
    # A sketch on another plane, or a circle, is refused even with allow_partial.
    doc.features[0].plane = ir.Plane.named("yz")
    with pytest.raises(W.NativeWriteUnsupported):
        W.write_sldprt(doc, allow_partial=False)


# ------------------------------------------------------------------ the object map
NATIVE_STREAMS = [
    (p, n)
    for p in PARTS
    if p.stem not in ("o09_import_step", "o10_import_step_cut")
    for n in ("Contents/Config-0-ResolvedFeatures", "Contents/Config-1-ResolvedFeatures")
    if n in read_document(p).offsets
]


@pytest.mark.parametrize(("path", "name"), NATIVE_STREAMS, ids=lambda x: getattr(x, "stem", str(x)[-28:]))
def test_the_feature_stream_continues_the_configuration_streams_archive(path, name):
    doc = read_document(path)
    config, feats = doc.data(name.replace("-ResolvedFeatures", "")), doc.data(name)
    after_config, after_features = F.object_map(config, feats)  # raises unless the counts meet
    assert after_config.classes[F.name_tag(feats)[0]] == "moNodeName_c"
    # Every class reference in the feature stream names a class defined before it.
    assert all(idx in after_features.classes for _off, idx in after_features.references)


def test_the_object_map_explains_o01_and_finds_repeated_planes():
    doc = read_document(FIXTURES / "o01_empty.SLDPRT")
    _, m = F.object_map(doc.data("Contents/Config-0"), doc.data(E.FEATURES))
    names = [m.classes[i] for _off, i in m.references]
    assert names.count("moRefPlane_c") == 2  # Top and Right reuse Front's class
    assert names.count("moNodeName_c") == 18


# ------------------------------------------------------------------ the object-level differ
from swnative import objdiff as OD  # noqa: E402


def test_objdiff_of_two_first_extrusions_finds_the_geometry_and_the_bookkeeping():
    a, b = read_document(FIXTURES / "o02_boxA.SLDPRT"), read_document(FIXTURES / "o11_curved.SLDPRT")
    d = OD.compare(OD.tokens(a, "Sketch1", "Boss-Extrude1"), OD.tokens(b, "Sketch1", "Boss-Extrude1"))
    doubles = {(r["a_value"], r["b_value"]) for r in d["runs"] if r["kind"] == "double"}
    # The rectangle's far corner (10 x 20 against 40 x 30) and the depth (30 against 10), in mm.
    assert {(10.0, 40.0), (20.0, 30.0), (30.0, 10.0)} <= doubles
    stamps = [r for r in d["runs"] if r["kind"] == "unixtime"]
    assert stamps and all(abs(r["a_value"] - r["b_value"]) < 3600 for r in stamps)  # one session
    # o11 writes a new moSketchBlockMgr_c object where o02 refers to the one in Config-0.
    assert d["unaligned"] == [{"op": "insert", "a": [], "b": ["moSketchBlockMgr_c", 271]}]


def test_objdiff_of_one_model_saved_twice_is_bookkeeping_only():
    a, b = read_document(FIXTURES / "o02_boxA.SLDPRT"), read_document(FIXTURES / "o03_boxA_again.SLDPRT")
    d = OD.compare(OD.tokens(a, "Sketch1", "Boss-Extrude1"), OD.tokens(b, "Sketch1", "Boss-Extrude1"))
    assert "double" not in d["counts"] and not d["unaligned"]


# ------------------------------------------------------------------ the layout catalog
from swnative import layouts as LY  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    return LY.catalog(LY.instances(sorted(FIXTURES.glob("*.SLDPRT"))))


def test_layouts_read_names_as_strings_so_instances_line_up(catalog):
    planes = next(x for x in catalog["moNodeName_c"] if "Front Plane" in x.strings[0])
    assert set(planes.strings[0]) == {"Front Plane", "Top Plane", "Right Plane"}
    assert planes.count == 3 * planes.sources  # every mapped part has the three planes


def test_layouts_find_the_rectangle_corners_as_doubles(catalog):
    seen = {v for lay in catalog["sgLineHandle"] for f in lay.fields if f.kind == "f64" for v in f.values}
    assert {0.01, 0.02} <= seen  # o02's far corner, 10 x 20 mm, in metres


def test_the_first_features_are_mostly_the_same_bytes_in_every_part():
    paths = sorted(FIXTURES.glob("*.SLDPRT"))
    for name in ("Comments", "Equations", "Front Plane"):
        spans = LY.feature_spans(paths, name)
        assert len(spans) >= 12 and len({len(i.body) for i in spans}) == 1
        assert LY.layout(spans).constant_fraction() > 0.85


def test_typedump_reads_the_drafting_defaults_of_config_0():
    from swnative import typedump as TD

    data = read_document(FIXTURES / "o01_empty.SLDPRT").data("Contents/Config-0")
    seen = [(i.kind, i.value) for i in TD.items(data)]
    assert ("cstring", "Century Gothic") in seen and ("cstring", "CONTINUOUS") in seen
    assert ("length", 3.5) in seen  # the default text height, in mm
    assert ("angle", 45) in seen


def test_a_sketch_point_record_is_constant_but_for_its_index_ids_and_coordinates():
    found = []
    for path in sorted(FIXTURES.glob("*.SLDPRT")):
        data = read_document(path).data("Contents/Config-0-ResolvedFeatures")
        for p in F.sketch_points(data):
            start = data.rfind(b"\x00\x00\xfe\xff\xff\xff", 0, p.offset)
            if p.offset + 16 - start == 134:
                run = data[start - 12 : p.offset + 20]
                assert run[1] == 0x80 and 1 <= struct.unpack_from("<H", run, 2)[0] < 16 and 1 <= run[60] < 16
                found.append(run[3:60] + run[61:130] + run[146:])
    assert len(found) >= 30 and len(set(found)) == 1


def test_a_cstring_is_read_with_either_length_form():
    short = b"\xff\xfe\xff\x02" + "Ab".encode("utf-16-le")
    long_ = b"\xff\xfe\xff\xff\x02\x00" + "Ab".encode("utf-16-le")
    assert LY._cstring_at(short, 0) == ("Ab", len(short))
    assert LY._cstring_at(long_, 0) == ("Ab", len(long_))
    assert LY._blank_strings(b"\x01" + short + b"\x02") == (b"\x01\xff\xfe\xff\x00\x02", ("Ab",))


@pytest.mark.parametrize(
    ("a", "b", "kind"),
    [
        (struct.pack("<d", 0.01), struct.pack("<d", 0.04), "double"),
        ((1790900763).to_bytes(4, "little"), (1790900778).to_bytes(4, "little"), "unixtime"),
        (b"\x76\x00\x00\x00", b"\x7c\x00\x00\x00", "counter"),
    ],
)
def test_objdiff_classifies_a_run(a, b, kind):
    i = next(k for k in range(len(a)) if a[k] != b[k])
    j = max(k for k in range(len(a)) if a[k] != b[k]) + 1
    assert OD.classify(a, b, i, j, i, j)[0] == kind


def test_b_candidates_carry_o12s_two_features_into_o02(cands):
    for name in ("b1-features-from-o12", "b2-features-from-o12-no-partition"):
        c = cands[name]
        with open_container(c.data) as cc:
            feats, config = cc.read(E.FEATURES), cc.read("Contents/Config-0")
            names = cc.names()
        F.object_map(config, feats)  # the two streams agree with each other
        assert [p.full_name for p in F.parameters(feats)] == ["D1@Boss-Extrude1", "D1@Boss-Extrude2"]
        assert c.expected_volume_m3 == pytest.approx(8.0e-6)  # o12's ground truth
        assert (E.PARTITION in names) == (name == "b1-features-from-o12")


def _sc_doc(features, params=()):
    return {"format": "solidcraft/28", "name": "t", "params": list(params), "features": features}


RECT_SKETCH = json.loads(RECT_SAMPLE.read_text(encoding="utf-8"))["features"][0]
RECT_EXTRUDE = json.loads(RECT_SAMPLE.read_text(encoding="utf-8"))["features"][1]


def test_solidcraft_fillet_chamfer_pattern_mirror_and_hole():
    feats = [
        RECT_SKETCH,
        RECT_EXTRUDE,
        {
            "id": 3,
            "name": "Fillet1",
            "type": "fillet",
            "edges": [[40, 15, 10]],
            "edge_names": ["F2:side:l2|F2:top"],
            "radius": "2",
            "param_names": ["d4"],
        },
        {
            "id": 4,
            "name": "Chamfer1",
            "type": "chamfer",
            "edges": [[0, 15, 10]],
            "distance": "1 mm",
            "angle": "30",
        },
        {
            "id": 5,
            "name": "Hole1",
            "type": "hole",
            "position": [20, 15, 10],
            "direction": [0, 0, -1],
            "diameter": "5",
            "hole": {"type": "counterbore", "cb_diameter": "9", "cb_depth": "3"},
        },
        {
            "id": 6,
            "name": "Pattern1",
            "type": "pattern",
            "features": ["Hole1"],
            "pattern": {"type": "rectangular", "dir1": [1, 0, 0], "count1": "3", "spacing1": "8 mm"},
        },
        {
            "id": 7,
            "name": "Pattern2",
            "type": "pattern",
            "features": ["Hole1"],
            "pattern": {
                "type": "circular",
                "origin": [20, 15, 0],
                "axis": [0, 0, 2],
                "count": "6",
                "angle": "360 deg",
            },
        },
        {
            "id": 8,
            "name": "Mirror1",
            "type": "mirror",
            "features": ["Hole1"],
            "plane": {"type": "origin", "name": "YZ"},
        },
    ]
    doc = SC.to_ir(_sc_doc(feats, json.loads(RECT_SAMPLE.read_text(encoding="utf-8"))["params"]))
    _, _, fil, cha, hole, lin, cir, mir = doc.features
    assert (
        isinstance(fil, ir.Fillet)
        and fil.radius == 0.002
        and fil.edges[0] == ir.EdgeRef((0.04, 0.015, 0.01), "F2:side:l2|F2:top")
    )
    assert isinstance(cha, ir.Chamfer) and cha.distance == 0.001 and cha.angle == pytest.approx(math.pi / 6)
    assert isinstance(hole, ir.Hole) and (hole.kind, hole.depth) == ("counterbore", None)
    assert (hole.diameter, hole.cb_diameter, hole.cb_depth) == pytest.approx((0.005, 0.009, 0.003))
    assert (lin.kind, lin.count1, lin.spacing1, lin.features) == ("linear", 3, 0.008, ["5"])
    assert (cir.kind, cir.count1, cir.axis) == ("circular", 6, (0.0, 0.0, 1.0))
    assert isinstance(mir, ir.Mirror) and mir.plane.base == "yz"
    assert ir.from_json(ir.to_json(doc)) == doc
    with pytest.raises(W.NativeWriteUnsupported) as e:
        W.write_sldprt(doc, allow_partial=False)
    assert sum("is not in the seed" in i for i in e.value.items) == 6


def test_solidcraft_offset_and_face_planes_become_frames():
    sk = json.loads(json.dumps(RECT_SKETCH))
    sk["plane"] = {"type": "offset", "base": {"type": "origin", "name": "XY"}, "distance": "-5"}
    face = json.loads(json.dumps(RECT_SKETCH))
    face["id"] = 9
    face["plane"] = {
        "type": "face",
        "name": "F2:top",
        "at": [3, 4, 10],
        "plane": {"origin": [0, 0, 10], "x_dir": [1, 0, 0], "y_dir": [0, 1, 0]},
    }
    doc = SC.to_ir(_sc_doc([sk, face], json.loads(RECT_SAMPLE.read_text(encoding="utf-8"))["params"]))
    off, top = doc.features[0].plane, doc.features[1].plane
    assert (off.origin, off.parent, off.offset, off.base) == ((0.0, 0.0, -0.005), "xy", -0.005, None)
    assert (top.origin, top.face_name, top.face_point) == ((0.0, 0.0, 0.01), "F2:top", (0.003, 0.004, 0.01))


def test_solidcraft_partial_revolve_with_the_legacy_convention_is_unsupported():
    rev = {
        "id": 2,
        "name": "Revolve1",
        "type": "revolve",
        "sketch": 1,
        "profiles": {"type": "all"},
        "axis": {"type": "sketch_axis", "axis": "y"},
        "angle": "180 deg",
        "operation": "new_body",
    }
    full = dict(rev, id=3, name="Revolve2", angle="360 deg")
    doc = SC.to_ir(
        _sc_doc([RECT_SKETCH, rev, full], json.loads(RECT_SAMPLE.read_text(encoding="utf-8"))["params"])
    )
    assert isinstance(doc.features[1], ir.Unsupported) and "legacy convention" in doc.features[1].reason
    assert isinstance(doc.features[2], ir.Revolve) and doc.features[2].axis == ir.Axis("sketch_y")


def test_b3_and_b4_put_a_box_definition_into_the_empty_part(cands):
    for name, depth in (("b3-o02-features-in-o01", 0.030), ("b4-o02-features-in-o01-40x30x10", 0.010)):
        c = cands[name]
        with open_container(c.data) as cc:
            feats, config, part = cc.read(E.FEATURES), cc.read("Contents/Config-0"), cc.read(E.PARTITION)
        F.object_map(config, feats)
        assert F.parameter(feats, E.DEPTH).value == depth
        assert part == read_document(FIXTURES / "o01_empty.SLDPRT").data(E.PARTITION)


def test_the_seed_writer_leaves_the_partition_out_by_default():
    data, rep = W.write_sldprt(SC.read_ir(RECT_SAMPLE), allow_partial=True)
    with open_container(data) as c:
        assert E.PARTITION not in c and E.GHOST not in c
    assert rep.geometry == "drop"


def test_judge_reads_the_bridges_mass_volume():
    snap = {"measure": {"mass": {"volume_m3": 6.2e-6}}, "features": []}
    assert E._volume(snap) == 6.2e-6
    assert E._volume({"measure": {}}) is None


def test_member_candidates_leave_out_one_member_each_or_all_but_a_core(cands):
    src = read_document(FIXTURES / "o02_boxA.SLDPRT")
    others = [m.name for m in src.members if m.name not in (E.PARTITION, E.GHOST)]
    singles = [c for n, c in cands.items() if n.startswith("m-")]
    assert len(singles) == len(others) == 39
    for c in singles + [cands["m00-no-partition"], cands["g1-core"], cands["g2-core"]]:
        with open_container(c.data) as cc:
            names = set(cc.names())
        assert not names & set(c.dropped) and E.PARTITION not in names
    with open_container(cands["g1-core"].data) as cc:
        assert set(cc.names()) == set(E.CORE_G1)
