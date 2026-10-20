"""``solidseas sldprt DESIGN``: a native part written from a SolidSeas IR document and
from a SolidCraft design, the refusal of what the generator cannot write and the
part written without it under ``--allow-partial``, the ``sldprt_written`` kind
validated strictly against its schema, the write guards (never over a file, never
next to the design unless asked, only a ``.sldprt`` name) and designs that cannot be
read. Tests that need the generator skip until ``solidseas.nativewrite.generate``
is there."""

import json
from pathlib import Path

import pytest

from jsonschema_subset import validate
from solidseas import cli, model
from solidseas.formats.solidworks import open_document
from solidseas.nativewrite import ir

SOLIDCRAFT = Path(__file__).resolve().parent / "fixtures" / "solidcraft" / "rect-extrude-40x30x10.solidcraft"


def _no_constants(name):
    raise ValueError(f"{name} is not strict JSON")


def run(capsys, *argv) -> tuple[int, dict]:
    """``sldprt`` with --json: one strict JSON document out, nothing on standard error."""
    code = cli.main(["sldprt", *argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out, parse_constant=_no_constants)


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind and env["ok"] is (kind != "error")
    errors = validate(env, model.envelope_schema(kind), strict=True)
    assert errors == [], errors[:5]
    return env["data"] if env["ok"] else env["error"]


def needs_generator():
    pytest.importorskip("solidseas.nativewrite.generate")


def box() -> ir.Document:
    """A 40 x 30 mm corner rectangle from the origin on the base plane xy, extruded
    blind 10 mm as a new body: what the generator writes today."""
    corners = [("p1", 0.0, 0.0), ("p2", 0.04, 0.0), ("p3", 0.04, 0.03), ("p4", 0.0, 0.03)]
    points = [ir.Point(pid, x, y) for pid, x, y in corners]
    lines = [ir.Curve(f"l{i + 1}", "line", [corners[i][0], corners[(i + 1) % 4][0]]) for i in range(4)]
    sketch = ir.Sketch("s1", "Base sketch", ir.Plane.named("xy"), points=points, curves=lines)
    extrude = ir.Extrude("e1", "Base", "s1", 0.01, operation="new_body")
    return ir.Document("box", [sketch, extrude])


@pytest.fixture
def design(tmp_path) -> Path:
    folder = tmp_path / "designs"
    folder.mkdir()
    path = folder / "box.json"
    path.write_text(ir.to_json(box()), encoding="utf-8")
    return path


@pytest.fixture
def out(tmp_path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def _is_part(path: Path) -> bool:
    with open_document(str(path)) as doc:
        return doc.doc_type == "part"


# --------------------------------------------------------------------------- written
def test_an_ir_design_is_written_as_a_new_part(capsys, design, out):
    needs_generator()
    target = out / "box.SLDPRT"
    code, env = run(capsys, str(design), "-o", str(target))
    data = check(env, "sldprt_written")
    assert code == 0 and env["source"] == {"file": str(design)}
    assert data["output"] == str(target) and data["bytes"] == target.stat().st_size > 0
    assert data["design"] == {"name": "box", "format": "ir"}
    assert data["features"] == [
        {"id": "s1", "name": "Base sketch", "part_name": "Sketch1"},
        {"id": "e1", "name": "Base", "part_name": "Boss-Extrude1"},
    ]
    assert data["left_out"] == [] and data["unsupported"] == [] and data["partial"] is False
    assert _is_part(target)


def test_the_text_says_what_was_written_and_that_solidworks_has_not_opened_it(capsys, design, out):
    needs_generator()
    code = cli.main(["sldprt", str(design), "-o", str(out)])
    text, err = capsys.readouterr()
    target = out / "box.SLDPRT"  # a folder takes the design's name
    assert code == 0 and err == "" and target.is_file()
    assert text.startswith(f"wrote {target} (") and "a part with 2 feature(s) from the design box" in text
    assert "  Sketch1, from Base sketch\n" in text and "  Boss-Extrude1, from Base\n" in text
    assert "left out" not in text
    assert text.rstrip().endswith(cli.NATIVE_PART_NOTE)
    note = cli.NATIVE_PART_NOTE
    assert "without SOLIDWORKS" in note and "not been opened in SOLIDWORKS" in note


def test_without_o_the_part_goes_to_the_current_folder(capsys, design, out, monkeypatch):
    needs_generator()
    monkeypatch.chdir(out)
    code, env = run(capsys, str(design))
    assert code == 0 and check(env, "sldprt_written")["output"] == str(out / "box.SLDPRT")


# --------------------------------------------------------------------------- what the generator cannot write
def test_a_design_with_a_fillet_is_refused_and_every_item_listed(capsys, out):
    needs_generator()
    target = out / "plate.SLDPRT"
    code, env = run(capsys, str(SOLIDCRAFT), "-o", str(target))
    err = check(env, "error")
    assert code == 1 == cli.exit_code("not_implemented") and err["code"] == "not_implemented"
    assert err["detail"]["rule"] == "native_write" and err["detail"]["value"] >= 1
    assert "Fillet1" in err["reader_message"] and "--allow-partial" in err["reader_message"]
    assert not target.exists() and list(out.iterdir()) == []


def test_the_refusal_in_text_lists_the_items(capsys, out):
    needs_generator()
    code = cli.main(["sldprt", str(SOLIDCRAFT), "-o", str(out / "plate.SLDPRT")])
    text, err = capsys.readouterr()
    assert code == 1 and text == ""
    assert err.startswith("solidseas: the design needs what SolidSeas cannot write") and "\n  " in err
    assert "Fillet1" in err and "UnsupportedOperationError" not in err
    assert list(out.iterdir()) == []


def test_allow_partial_writes_the_part_and_lists_what_was_left_out(capsys, out):
    needs_generator()
    target = out / "plate.SLDPRT"
    code, env = run(capsys, str(SOLIDCRAFT), "-o", str(target), "--allow-partial")
    data = check(env, "sldprt_written")
    assert code == 4 and data["partial"] is True
    assert data["design"] == {"name": "rect-extrude-40x30x10", "format": "solidcraft"}
    assert [f["part_name"] for f in data["features"]] == ["Sketch1", "Boss-Extrude1"]
    assert [f["name"] for f in data["features"]] == ["Sketch1", "Extrude1"]
    assert data["unsupported"] and any("Fillet1" in item for item in data["unsupported"])
    assert set(data["unsupported"]) <= set(data["left_out"])
    assert data["bytes"] == target.stat().st_size and _is_part(target)


def test_allow_partial_in_text_prints_every_item_left_out(capsys, out):
    needs_generator()
    code = cli.main(["sldprt", str(SOLIDCRAFT), "-o", str(out / "plate.SLDPRT"), "--allow-partial"])
    text, err = capsys.readouterr()
    assert code == 4 and err == ""
    listed = text.split("left out of the part:\n", 1)[1]
    assert "Fillet1" in listed and text.rstrip().endswith(cli.NATIVE_PART_NOTE)


def test_allow_partial_on_a_design_it_fully_writes_exits_0(capsys, design, out):
    needs_generator()
    code, env = run(capsys, str(design), "-o", str(out), "--allow-partial")
    data = check(env, "sldprt_written")
    assert code == 0 and data["partial"] is False and data["unsupported"] == []


# --------------------------------------------------------------------------- the write guards
def test_an_existing_file_is_never_replaced(capsys, design, out):
    target = out / "box.SLDPRT"
    target.write_bytes(b"not mine")
    for extra in ((), ("--allow-partial",)):
        code, env = run(capsys, str(design), "-o", str(target), *extra)
        err = check(env, "error")
        assert code == 3 and err["code"] == "output_refused" and err["detail"]["rule"] == "exists"
    code, env = run(capsys, str(design), "-o", str(out))  # the design's name in a folder
    assert code == 3 and check(env, "error")["detail"]["rule"] == "exists"
    assert target.read_bytes() == b"not mine"


def test_there_is_no_force(capsys, design, out):
    code, env = run(capsys, str(design), "-o", str(out / "box.SLDPRT"), "--force")
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"


@pytest.mark.parametrize(
    ("name", "rule"),
    [("box.step", "output_extension"), ("box", "output_extension"), ("missing/", "output_folder")],
)
def test_only_a_sldprt_name_or_a_folder_that_exists(capsys, design, out, name, rule):
    code, env = run(capsys, str(design), "-o", str(out / name) + ("/" if name.endswith("/") else ""))
    err = check(env, "error")
    assert code == 3 and err["code"] == "output_refused" and err["detail"]["rule"] == rule
    assert list(out.iterdir()) == []


def test_a_folder_that_is_not_there_is_refused(capsys, design, tmp_path):
    code, env = run(capsys, str(design), "-o", str(tmp_path / "nowhere" / "box.SLDPRT"))
    assert code == 3 and check(env, "error")["detail"]["rule"] == "output_folder"
    assert not (tmp_path / "nowhere").exists()


def test_not_next_to_the_design_unless_asked(capsys, design):
    target = design.parent / "box.SLDPRT"
    code, env = run(capsys, str(design), "-o", str(target))
    assert code == 3 and check(env, "error")["detail"]["rule"] == "source_folder"
    assert not target.exists()
    needs_generator()
    code, env = run(capsys, str(design), "-o", str(target), "--allow-source-dir")
    assert code == 0 and check(env, "sldprt_written")["output"] == str(target) and target.is_file()


# --------------------------------------------------------------------------- designs that cannot be read
@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("box.json", b"{not json"),
        ("box.json", b'{"name": "box", "format": "something-else/1", "features": []}'),
        ("box.json", b'{"features": []}'),
        ("box.solidcraft", b"\x00\x01 not a design"),
        ("box.solidcraft", b'{"format": "solidcraft/999", "features": []}'),
        ("box.solidcraft", b"PK\x03\x04 a broken zip"),
        ("box.txt", b"{}"),
    ],
)
def test_a_design_that_cannot_be_read_is_a_usage_error(capsys, tmp_path, out, name, content):
    (tmp_path / "bad").mkdir()
    path = tmp_path / "bad" / name
    path.write_bytes(content)
    code, env = run(capsys, str(path), "-o", str(out))
    err = check(env, "error")
    assert code == 2 and err["code"] == "invalid_argument" and err["detail"]["parameter"] == "design"
    assert list(out.iterdir()) == []


def test_a_design_that_is_not_there(capsys, tmp_path, out):
    missing = tmp_path / "designs"
    code, env = run(capsys, str(missing / "nope.solidcraft"), "-o", str(out))
    assert code == 1 and check(env, "error")["code"] == "not_found"
    code = cli.main(["sldprt", str(missing / "nope.json"), "-o", str(out)])
    assert code == 1 and "not found" in capsys.readouterr().err


# --------------------------------------------------------------------------- the kind
def test_the_kind_is_registered_and_its_schema_printed(capsys):
    spec = model.KINDS["sldprt_written"]
    assert spec.cli_commands == ("sldprt",) and spec.rest_route is None and spec.schema_version == 1
    assert cli.COMMANDS["sldprt"].kind == "sldprt_written"
    code = cli.main(["schema", "sldprt_written"])
    assert code == 0 and json.loads(capsys.readouterr().out) == model.envelope_schema("sldprt_written")


def test_the_builder_matches_the_schema():
    data = model.build_sldprt_written(
        "/out/plate.SLDPRT",
        1234,
        design_name="plate",
        design_format="solidcraft",
        features=[{"id": "1", "name": "Sketch1", "part_name": "Sketch1"}],
        left_out=["Fillet1: fillets are not written yet"],
        unsupported=["Fillet1: fillets are not written yet"],
    )
    assert validate(data, model.KINDS["sldprt_written"].schema, strict=True) == []
    assert data["partial"] is True and data["design"] == {"name": "plate", "format": "solidcraft"}
