"""Parasolid of SOLIDWORKS assemblies (``solidseas.parasolid``): one transmit whose
ASSEMBLY places every part instance by an INSTANCE and its TRANSFORM, each part's
bodies copied in once. The fixtures hold no SOLIDWORKS export of an assembly, so the
files written are read back with SolidSeas' own transmit reader and checked against
what SOLIDWORKS reported (``ground_truth.json``): the number of bodies placed, each
placed body's box against SOLIDWORKS' box of that component, every part's volume,
and the assembly's volume and centre of mass."""

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest

from jsonschema_subset import validate
from solidseas import cli, model, open_document
from solidseas import parasolid as P
from solidseas.errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NothingToExportError,
    NotRepresentableError,
    OutputRefusedError,
    SldLimitError,
)
from solidseas.formats import open_model
from solidseas.formats.solidworks import parasolid as ps
from solidseas.formats.solidworks.parasolid import XtTransmit
from solidseas.roots import Root, Roots
from support import FIXTURES, fixture_path, ground_truth, parts_at_stored_paths

O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
GT = ground_truth()
DEFAULT_DENSITY = 1000.0  # SOLIDWORKS' density for a part without a material, as o02 reports it


def _export(name: str, configuration: str | None = None, **kw) -> P.AssemblyParasolid:
    with open_document(fixture_path(name)) as doc:
        return P.assembly_parasolid(doc, configuration, **kw)


def _det(r) -> float:
    return (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )


def _read_back(data: bytes, fmt: str) -> dict[str, dict]:
    """Each placed body by its path of instance names (``sub-1/part-1``): its box,
    volume and centroid in the top assembly's frame."""
    with open_model(data, name=f"a.{fmt}") as doc:
        assert doc.doc_type == "assembly"
        tree = {n.id: n for n in doc.tree().nodes}
        scene = doc.scene()
    assert scene.warnings == () and not scene.skipped

    def path(node_id: str) -> str:
        names = []
        while tree[node_id].parent is not None:
            names.append(tree[node_id].name)
            node_id = tree[node_id].parent
        return "/".join(reversed(names))

    out: dict[str, dict] = {}
    for it in scene.items:
        o = scene.objects[it.object]
        p, t = o.positions, o.triangles
        pts = [it.placement.apply((p[k], p[k + 1], p[k + 2])) for k in range(0, len(p), 3)]
        vol6 = 0.0
        mom = [0.0, 0.0, 0.0]
        for k in range(0, len(t), 3):
            a, b, c = pts[t[k]], pts[t[k + 1]], pts[t[k + 2]]
            v = (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            )
            vol6 += v
            for i in range(3):
                mom[i] += v * (a[i] + b[i] + c[i]) / 4.0
        key = path(it.instance)
        assert key not in out, key
        out[key] = {
            "box": [*(min(q[i] for q in pts) for i in range(3)), *(max(q[i] for q in pts) for i in range(3))],
            "volume": vol6 / 6.0,
            "centroid": [m / vol6 for m in mom],
            "det": _det(it.placement.rotation),
        }
    return out


CASES = [(O08, "Default"), (O15, "Default"), (O16, "Default"), (O16, "Lite")]


@pytest.mark.parametrize("fmt", ["x_b", "x_t"])
@pytest.mark.parametrize(("name", "configuration"), CASES)
def test_every_body_is_placed_where_solidworks_reported_it(name, configuration, fmt):
    """Body count, each placed body's box, every part's volume, and the assembly's volume
    and centre of mass, against SOLIDWORKS' own numbers for the assembly."""
    m = _export(name, configuration, other_configurations=True)
    assert m.valid, m.report["errors"]
    assert m.configuration == configuration and m.skipped == ()
    want = GT[name]["api"]["configurations"][configuration]
    components = {
        c["name"]: c
        for c in want["components"]
        if not c["suppressed"] and not c["file_name"].upper().endswith(".SLDASM")
    }
    got = _read_back(m.data(fmt), fmt)
    assert sorted(got) == sorted(components)  # one body for each part instance, named after it
    assert m.counts["instances"] == m.counts["bodies_placed"] == len(components)
    tol = 1e-9  # text keeps 15 significant digits, far inside this
    mass = 0.0
    moment = [0.0, 0.0, 0.0]
    for key, body in got.items():
        c = components[key]
        assert body["box"] == pytest.approx(c["box_m"], abs=tol), key
        assert body["det"] == pytest.approx(1.0, abs=1e-9)  # turned, never mirrored
        part = GT.get(c["file_name"])
        if part is not None:  # the virtual part has no ground truth of its own
            cfg = part["api"]["configurations"][c["referenced_configuration"]]
            assert body["volume"] == pytest.approx(cfg["volume_m3"], rel=1e-9), key
            density = cfg["density_kg_m3"]
        else:
            density = DEFAULT_DENSITY
        mass += body["volume"] * density
        for i in range(3):
            moment[i] += body["volume"] * density * body["centroid"][i]
    assert sum(b["volume"] for b in got.values()) == pytest.approx(want["volume_m3"], rel=1e-9)
    assert mass == pytest.approx(want["mass_kg"], rel=1e-9)
    assert [x / mass for x in moment] == pytest.approx(want["center_of_mass_m"], abs=1e-9)


def test_each_part_is_copied_in_once_however_often_it_is_placed():
    m = _export(O16, "Default", other_configurations=True)
    xt = m.transmit
    census = xt.census()
    # o02 (four times, once inside o15), o06, o07 (three times and once inside o15), o09,
    # o17 and the virtual part: six bodies; the top assembly and o15 are the assemblies.
    assert census["BODY"] == m.counts["bodies"] == m.counts["parts"] == 6
    assert census["ASSEMBLY"] == 2 and m.counts["sub_assemblies"] == 1
    assert census["INSTANCE"] == census["TRANSFORM"] == 13  # 11 in o16, 2 in o15
    assert xt.by_index()[1].type == P.ASSEMBLY and xt.kind == "part"
    names = [
        n for n in xt.nodes if n.type == P.ATT_DEF_ID and n.vals[0] == P.NAME_ATTRIBUTE
    ]  # one definition of each attribute, the parts' own merged
    assert len(names) == 1
    defs = [ps._text(xt, xt.by_index()[xt.get(n, "identifier")]) for n in xt.nodes if n.type == P.ATTRIB_DEF]
    assert len(defs) == len(set(defs))


def test_a_sub_assembly_places_its_parts_in_its_own_frame():
    m = _export(O16, "Default", other_configurations=True)
    with open_model(m.x_b(), name="a.x_b") as doc:
        nodes = doc.tree().nodes
    sub = next(n for n in nodes if n.name == "o15_sub_asm-1")
    assert sub.parent == "1"
    kids = {n.name: n for n in nodes if n.parent == sub.id}
    assert sorted(kids) == ["o02_boxA-1", "o07_boxB_h31-1"]
    # o15 places o07 turned +90 degrees about X and moved 30 mm along X (ground truth)
    turned = kids["o07_boxB_h31-1"].placement
    assert turned.translation_m == pytest.approx((0.03, 0.0, 0.0), abs=1e-12)
    # the images of the axes (1, 0, 0), (0, 0, 1) and (0, -1, 0) are the rotation's columns
    flat = [v for row in turned.rotation for v in row]
    assert flat == pytest.approx([1, 0, 0, 0, 0, -1, 0, 1, 0], abs=1e-12)
    assert kids["o02_boxA-1"].placement.translation_m == pytest.approx((0, 0, 0), abs=1e-12)


def test_a_component_that_cannot_be_written_refuses_the_assembly_unless_asked():
    """o16 places o06 in a configuration whose bodies o06 does not store."""
    with pytest.raises(NotRepresentableError) as caught:
        _export(O16)
    assert caught.value.detail["rule"] == "instances_left_out" and caught.value.detail["value"] == 1
    assert "o06_boxA_props_mat_cfg-1" in str(caught.value) and "'OracleAlt'" in str(caught.value)

    partial = _export(O16, allow_partial=True)
    assert [s.id for s in partial.skipped] == ["o06_boxA_props_mat_cfg-1"]
    assert partial.skipped[0].reason == "parasolid_refused" and partial.counts["skipped"] == 1
    assert "parasolid_instances_left_out" in {w.code for w in partial.warnings}
    got = _read_back(partial.x_b(), "x_b")
    assert len(got) == 11 and "o06_boxA_props_mat_cfg-1" not in got

    other = _export(O16, other_configurations=True)
    assert not other.skipped
    assert "parasolid_other_configuration" in {w.code for w in other.warnings}
    o06 = next(i for i in other.instances if i.id == "o06_boxA_props_mat_cfg-1")
    assert o06.configuration == "Default" and o06.bodies == 1


def test_missing_components_are_reported_not_dropped(tmp_path):
    shutil.copy(FIXTURES / O16, tmp_path / O16)  # without its parts beside it
    if parts_at_stored_paths(tmp_path / O16):
        pytest.skip("the parts are at the paths the assembly stores (the PC that made the fixtures)")
    roots = Roots([Root("here", str(tmp_path))])
    with open_document(tmp_path / O16) as doc:
        with pytest.raises(NotRepresentableError) as caught:
            P.assembly_parasolid(doc, roots=roots, allow_outside_roots=False)
        assert caught.value.detail["value"] == 11
        m = P.assembly_parasolid(doc, roots=roots, allow_outside_roots=False, allow_partial=True)
    # the virtual part is stored inside o16, so it is the one written
    assert [i.id for i in m.instances] == ["Part12^o16_asm_features-1"]
    assert len(m.skipped) == 11 and {s.reason for s in m.skipped} == {"missing"}
    shutil.copy(FIXTURES / O08, tmp_path / O08)
    with open_document(tmp_path / O08) as doc:
        with pytest.raises(NothingToExportError) as caught:
            P.assembly_parasolid(doc, roots=roots, allow_outside_roots=False, allow_partial=True)
    assert caught.value.detail["rule"] == "no_instances"


def test_a_part_with_several_bodies_is_an_assembly_of_them(monkeypatch):
    """As SOLIDWORKS writes a multi-body part: an ASSEMBLY of its bodies at the identity,
    placed as one by each instance."""
    with open_document(fixture_path("o12_multibody.SLDPRT")) as part:
        bodies = [b.transmit for b in part.parasolid().bodies]
    assert len(bodies) == 2
    monkeypatch.setattr(P, "_part_bodies", lambda *a, **k: ("Default", bodies, 0))
    m = _export(O08)
    assert m.valid and m.counts["bodies"] == 2 and m.counts["bodies_placed"] == 4
    xt = m.transmit
    assert xt.census()["ASSEMBLY"] == 2 and xt.census()["INSTANCE"] == 4
    with open_model(m.x_t(), name="a.x_t") as doc:
        tree = doc.tree().nodes
        scene = doc.scene()
    assert [n.name for n in tree if n.parent == "1"] == ["o02_boxA-1", "o02_boxA-2"]
    assert len(scene.items) == 4 and len(scene.objects) == 2
    own = sum(o.measures()["volume_m3"] for o in scene.objects)
    assert sum(scene.objects[it.object].measures()["volume_m3"] for it in scene.items) == pytest.approx(
        2 * own
    )


def _older(xt: XtTransmit) -> XtTransmit:
    """``xt`` as an older Parasolid would have written it: no ``lowest_node_id`` or
    ``mesh_offset_data`` on its BODY, and an older modeller and schema."""
    old = copy.copy(xt)
    old.layouts = dict(xt.layouts)
    lay = xt.layouts[P.BODY]
    drop = {i for i, f in enumerate(lay) if f[0] in ("lowest_node_id", "mesh_offset_data")}
    assert len(drop) == 2
    old.layouts[P.BODY] = [f for i, f in enumerate(lay) if i not in drop]
    old.nodes = [
        ps.Node(n.type, n.index, [v for i, v in enumerate(n.vals) if i not in drop], n.count)
        if n.type == P.BODY
        else n
        for n in xt.nodes
    ]
    old._by_index = None
    old.modeller = ": TRANSMIT FILE created by modeller version 3001000"
    old.schema = "SCH_3001000_30000_13006"
    return old


def test_bodies_of_different_schema_versions_are_written_in_the_newest(monkeypatch):
    real = P._part_bodies

    def older_o07(part, cfg, **kw):
        name, transmits, hidden = real(part, cfg, **kw)
        if "o07" in kw["label"]:
            transmits = [_older(x) for x in transmits]
        return name, transmits, hidden

    monkeypatch.setattr(P, "_part_bodies", older_o07)
    m = _export(O15)
    assert m.valid, m.report["errors"]
    warned = [w for w in m.warnings if w.code == "parasolid_schemas_merged"]
    assert len(warned) == 1 and "2 field(s)" in warned[0] and "0 value(s)" in warned[0]
    assert m.schema == "SCH_3501251_35102_13006"
    got = _read_back(m.x_b(), "x_b")
    want = {c["name"]: c["box_m"] for c in GT[O15]["api"]["configurations"]["Default"]["components"]}
    for key, body in got.items():
        assert body["box"] == pytest.approx(want[key], abs=1e-9)
    assert sum(b["volume"] for b in got.values()) == pytest.approx(1.22e-5, rel=1e-9)


def test_a_part_is_refused_and_bad_options_raise():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        with pytest.raises(InvalidArgumentError):
            P.assembly_parasolid(doc)
    with open_document(fixture_path(O08)) as doc:
        for bad in ({"max_seconds": 0}, {"max_nodes": 0}, {"max_bytes": True}):
            with pytest.raises(InvalidArgumentError):
                P.assembly_parasolid(doc, **bad)
        with pytest.raises(SldLimitError) as caught:
            P.assembly_parasolid(doc, max_nodes=100)
        assert caught.value.detail["limit"] == "max_nodes"
        with pytest.raises(ConfigurationNotFoundError):
            P.assembly_parasolid(doc, "No such configuration")


def test_write_parasolid_writes_new_files_only(tmp_path):
    m = _export(O08)
    path, size = P.write_parasolid(m, tmp_path / "a.x_t")
    assert size == (tmp_path / "a.x_t").stat().st_size and path == str(tmp_path / "a.x_t")
    assert (tmp_path / "a.x_t").read_bytes().startswith(b"**ABCDEFGHIJ")
    assert b"KEY=a;" in (tmp_path / "a.x_t").read_bytes()
    with pytest.raises(OutputRefusedError):
        P.write_parasolid(m, tmp_path / "a.x_t")
    P.write_parasolid(m, tmp_path / "a.x_t", "x_b", overwrite=True)
    assert ps.split_header((tmp_path / "a.x_t").read_bytes())[1].startswith(b"PS\0\0")
    with pytest.raises(InvalidArgumentError):
        P.write_parasolid(m, tmp_path / "a.step")


def test_a_name_is_read_as_utf8_when_it_is_valid_utf8():
    from solidseas.formats.xt import CHAR_VALUES, _Fields, _text_of

    xt = XtTransmit()
    xt.layouts = {CHAR_VALUES: [("values", "c", ps.VAR)]}

    def text(value: str) -> str | None:
        xt.nodes = [ps.Node(CHAR_VALUES, 1, [value], len(value))]
        xt._by_index = None
        return _text_of(_Fields(xt), xt.nodes[0])

    assert text("o17_деталь-1".encode().decode("latin-1")) == "o17_деталь-1"
    assert text("Stück") == "Stück"  # Latin-1, not valid UTF-8: as it is
    assert text("plain") == "plain"


def test_the_flag_of_a_transform():
    from solidseas.formats.solidworks.components import IDENTITY, Placement

    assert P._flag(IDENTITY) == 0
    assert P._flag(Placement(IDENTITY.rotation, (0.1, 0.0, 0.0))) == P.FLAG_TRANSLATION
    turned = Placement(((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))
    assert P._flag(turned) == P.FLAG_ROTATION
    mirrored = Placement(((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))
    assert P._flag(mirrored) == P.FLAG_ROTATION | P.FLAG_REFLECTION


# --------------------------------------------------------------------------- the command line
def _run(capsys, *argv) -> tuple[int, dict | None]:
    import json

    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_cli_parasolid_of_an_assembly(capsys, tmp_path):
    asm = str(fixture_path(O16))
    code, env = _run(capsys, "parasolid", asm, "-o", str(tmp_path), "--text")
    assert code == 1 and env["error"]["code"] == "not_representable"
    assert list(tmp_path.iterdir()) == []  # nothing written
    code, env = _run(capsys, "parasolid", asm, "-o", str(tmp_path), "--text", "--allow-partial")
    assert code == 4  # partial: an instance was left out
    assert validate(env, model.envelope_schema("parasolid_result"), strict=True) == []
    data = env["data"]
    assert [w["kind"] for w in data["written"]] == ["x_b", "x_t"]
    assert all(
        w["source"] == "assembly" and w["valid"] and w["configuration"] == "Default" for w in data["written"]
    )
    assert data["bodies"] == 11 and data["assembly"]["counts"]["instances"] == 11
    assert [s["id"] for s in data["assembly"]["skipped"]] == ["o06_boxA_props_mat_cfg-1"]
    for w in data["written"]:
        assert w["output"].endswith(("o16_asm_features_Default.x_b", "o16_asm_features_Default.x_t"))
        with open_model(w["output"]) as doc:
            assert len(doc.scene().items) == 11
    code, env = _run(
        capsys, "parasolid", asm, "-o", str(tmp_path), "--configuration", "Lite", "--other-configurations"
    )
    assert code == 0 and env["data"]["assembly"]["configuration"] == "Lite"
    assert env["data"]["written"][0]["output"].endswith("o16_asm_features_Lite.x_b")


def test_cli_parasolid_options_for_the_other_kind_of_document(capsys, tmp_path):
    part = str(fixture_path("o02_boxA.SLDPRT"))
    for flag in ("--allow-partial", "--other-configurations", "--include-hidden"):
        code, env = _run(capsys, "parasolid", part, "-o", str(tmp_path), flag)
        assert code == 2 and env["error"]["code"] == "invalid_argument"
    code, env = _run(capsys, "parasolid", part, "-o", str(tmp_path), "--configuration", "Default")
    assert code == 2
    code, env = _run(capsys, "parasolid", str(fixture_path(O08)), "-o", str(tmp_path), "--raw")
    assert code == 2 and env["error"]["detail"]["parameter"] == "--raw"
    code, env = _run(capsys, "parasolid", part, "-o", str(tmp_path))
    assert code == 0 and env["data"]["assembly"] is None


# --------------------------------------------------------------------------- batch
def _batch_folder(tmp_path) -> Path:
    """A folder of the three test assemblies with every part beside them."""
    src = tmp_path / "in"
    src.mkdir()
    for p in FIXTURES.iterdir():
        if p.suffix.upper() in (".SLDPRT", ".SLDASM"):
            shutil.copyfile(p, src / p.name)
    return src


def _batch_report(out: Path) -> tuple[dict, dict]:
    """Each row of report.csv and each line of report.jsonl, by file name."""
    with open(out / "report.csv", newline="", encoding="utf-8") as fh:
        rows = {r["file"]: r for r in csv.DictReader(fh)}
    text = (out / "report.jsonl").read_text(encoding="utf-8")
    return rows, {d["file"]: d for d in map(json.loads, text.splitlines())}


@pytest.mark.parametrize("reading", [["--in-process"], ["--jobs", "2"]])
def test_batch_writes_each_assembly_as_the_parasolid_command_does(capsys, tmp_path, reading):
    """An assembly in a batch gets the one transmit `solidseas parasolid` writes, and a
    refusal is that document's error row, naming the component, with nothing written."""
    src = _batch_folder(tmp_path)
    out = tmp_path / "out"
    code, env = _run(capsys, "batch", str(src), "-o", str(out), "--no-preview", *reading)
    assert validate(env, model.envelope_schema("batch_summary"), strict=True) == []
    data = env["data"]
    assert code == 4 and data["status_counts"] == {"error": 1, "ok": 16}  # o16, as the command refuses it
    assert data["parasolid_left_out"] == 0
    rows, lines = _batch_report(out)
    o16 = rows[O16]
    assert o16["status"] == "error" and o16["error"].startswith("NotRepresentableError: ")
    assert "o06_boxA_props_mat_cfg-1" in o16["error"] and o16["doc_type"] == "assembly"
    assert lines[O16]["parasolid"] is None and not list(out.glob(O16 + "*"))
    for name, bodies in ((O08, 2), (O15, 2)):
        row = rows[name]
        assert (row["status"], row["parasolid_bodies"], row["parasolid_files"]) == ("ok", str(bodies), "1")
        assert row["parasolid_left_out"] == "0"
        result = lines[name]["parasolid"]
        (written,) = result["written"]
        assert written["output"] == f"{name}_Default.x_b" and written["source"] == "assembly"
        assert result["assembly"]["counts"]["instances"] == bodies and result["assembly"]["skipped"] == []
        # the transmit the parasolid command writes for it; only the file's key differs
        code, single = _run(capsys, "parasolid", str(src / name), "-o", str(tmp_path / name))
        assert code == 0 and single["data"]["assembly"]["instances"] == result["assembly"]["instances"]
        mine = ps.split_header((out / written["output"]).read_bytes())[1]
        theirs = ps.split_header(Path(single["data"]["written"][0]["output"]).read_bytes())[1]
        assert mine == theirs
    assert rows["o02_boxA.SLDPRT"]["parasolid_left_out"] == ""  # a part has no components


def test_batch_takes_the_assembly_choices_of_the_parasolid_command(capsys, tmp_path):
    src = _batch_folder(tmp_path)
    out = tmp_path / "partial"
    code, env = _run(capsys, "batch", str(src), "-o", str(out), "--no-preview", "--text", "--allow-partial")
    data = env["data"]
    assert code == 4 and data["status_counts"] == {"ok": 17}  # partial: o16 left a component out
    assert data["parasolid_left_out"] == 1
    rows, lines = _batch_report(out)
    o16 = rows[O16]
    assert (o16["parasolid_bodies"], o16["parasolid_files"], o16["parasolid_left_out"]) == ("11", "2", "1")
    asm = lines[O16]["parasolid"]["assembly"]
    assert [s["id"] for s in asm["skipped"]] == ["o06_boxA_props_mat_cfg-1"]
    assert "parasolid_instances_left_out" in {w["code"] for w in asm["warnings"]}
    assert (out / f"{O16}_Default.x_b").exists()
    with open_model(out / f"{O16}_Default.x_t") as doc:
        assert len(doc.scene().items) == 11
    assert cli.main(["batch", str(src), "-o", str(tmp_path / "said"), "--no-preview", "--allow-partial"]) == 4
    assert "components left out of assembly Parasolid files: 1 in 1 assembly" in capsys.readouterr().out

    # --configuration and --other-configurations: an assembly without that
    # configuration is that document's error, as the command refuses it
    out = tmp_path / "lite"
    argv = ["--no-preview", "--configuration", "Lite", "--other-configurations", "--in-process"]
    code, env = _run(capsys, "batch", str(src), "-o", str(out), *argv)
    rows, lines = _batch_report(out)
    assert code == 4 and env["data"]["status_counts"] == {"error": 2, "ok": 15}
    assert rows[O16]["status"] == "ok" and rows[O16]["parasolid_left_out"] == "0"
    assert lines[O16]["parasolid"]["assembly"]["configuration"] == "Lite"
    assert (out / f"{O16}_Lite.x_b").exists()
    for name in (O08, O15):
        assert rows[name]["error"].startswith("ConfigurationNotFoundError: ")
    # the assembly choices leave the parts as they are: every configuration's bodies
    assert all(r["status"] == "ok" for n, r in rows.items() if n.endswith(".SLDPRT"))
    assert rows["o02_boxA.SLDPRT"]["parasolid_files"] == "1"

    # --include-hidden reaches the export (no test assembly hides a body)
    out = tmp_path / "hidden"
    code, env = _run(capsys, "batch", str(src), "-o", str(out), "--no-preview", "--include-hidden")
    assert code == 4 and _batch_report(out)[0][O08]["parasolid_bodies"] == "2"

    argv = ["--no-parasolid", "--allow-partial"]
    code, env = _run(capsys, "batch", str(src), "-o", str(tmp_path / "x"), *argv)
    assert code == 2 and env["error"]["detail"]["parameter"] == "--allow-partial"
    assert not (tmp_path / "x").exists()


def test_batch_never_writes_an_assembly_over_a_file_already_there(capsys, tmp_path):
    src = _batch_folder(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / f"{O08}_Default.x_b").write_bytes(b"mine")
    code, env = _run(capsys, "batch", str(src), "-o", str(out), "--no-preview", "--allow-partial")
    rows, _ = _batch_report(out)
    assert code == 4 and rows[O08]["status"] == "refused" and "already exists" in rows[O08]["error"]
    assert (out / f"{O08}_Default.x_b").read_bytes() == b"mine"
    assert rows[O15]["status"] == "ok"
    code, env = _run(capsys, "batch", str(src), "-o", str(out), "--no-preview", "--allow-partial", "--force")
    assert code == 4 and env["data"]["status_counts"] == {"ok": 17}
    assert (out / f"{O08}_Default.x_b").read_bytes() != b"mine"
