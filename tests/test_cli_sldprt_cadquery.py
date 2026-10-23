"""``solidseas sldprt RECORDING.json``: a native part written from a CadQuery recording
(``solidseas.nativewrite.cqrecording``), its features named after the CadQuery calls that made
them, the recording's file properties carried over, what the recording holds that the part
cannot refused or left out under ``--allow-partial``, and a recording that cannot be read
refused as a design. No CadQuery is needed: the recordings are written by
``tests/cadquery_chains.py``."""

import json
from pathlib import Path

import pytest

from cadquery_chains import Chain
from jsonschema_subset import validate
from solidseas import cli, model
from solidseas.formats.solidworks import open_document


def run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main(["sldprt", *argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind
    assert validate(env, model.envelope_schema(kind), strict=True) == []
    return env["data"] if env["ok"] else env["error"]


def needs_generator():
    pytest.importorskip("solidseas.nativewrite.generate")


def write(folder: Path, chain: Chain, model_, name: str = "plate", **options) -> Path:
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(chain.recording(model_, name=name, **options)), encoding="utf-8")
    return path


def plate(**options):
    c = Chain()
    m = c.wp("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").workplane(centerOption="CenterOfMass")
    return c, m.hole(8)


@pytest.fixture
def out(tmp_path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def test_a_cadquery_recording_is_written_as_a_part(capsys, tmp_path, out):
    needs_generator()
    c, m = plate()
    props = [
        {"name": "PartNo", "value": "SS-1001", "type": "text"},
        {"name": "Qty", "value": 2, "type": "number"},
    ]
    design = write(tmp_path / "designs", c, m, properties=props)
    code, env = run(capsys, str(design), "-o", str(out))
    data = check(env, "sldprt_written")
    target = out / "plate.SLDPRT"
    assert code == 0 and data["output"] == str(target) and data["bytes"] == target.stat().st_size
    assert data["design"] == {"name": "plate", "format": "cadquery"}
    assert data["features"] == [
        {"id": "s3", "name": "rect(40, 30, centered=False)", "part_name": "Sketch1"},
        {"id": "f3", "name": "extrude(10)", "part_name": "Boss-Extrude1"},
        {"id": "s6", "name": "hole(8)", "part_name": "Sketch2"},
        {"id": "f6", "name": "hole(8)", "part_name": "Cut-Extrude1"},
    ]
    assert data["properties"] == [
        {"name": "PartNo", "type": "text", "value": "SS-1001"},
        {"name": "Qty", "type": "number", "value": 2},
    ]
    assert data["left_out"] == [] and data["partial"] is False
    with open_document(str(target)) as part:
        assert part.doc_type == "part"


def test_the_text_names_each_feature_after_its_cadquery_call(capsys, tmp_path, out):
    needs_generator()
    c, m = plate()
    design = write(tmp_path / "designs", c, m)
    code = cli.main(["sldprt", str(design), "-o", str(out), "--property", "PartNo=SS-1002"])
    text, err = capsys.readouterr()
    assert code == 0 and err == ""
    assert "a part with 4 feature(s) from the design plate" in text
    assert (
        "  Sketch1, from rect(40, 30, centered=False)\n" in text and "  Cut-Extrude1, from hole(8)\n" in text
    )
    assert "file properties: PartNo\n" in text and text.rstrip().endswith(cli.NATIVE_HOLE_NOTE)


def test_what_the_part_cannot_hold_is_refused_or_left_out(capsys, tmp_path, out):
    needs_generator()
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).edges("|Z").fillet(2)
    design = write(tmp_path / "designs", c, m, name="rounded")
    code, env = run(capsys, str(design), "-o", str(out))
    err = check(env, "error")
    assert code == 1 and err["code"] == "not_implemented" and err["detail"]["rule"] == "native_write"
    assert "fillet(2): CadQuery's fillet() is not translated yet" in err["reader_message"]
    assert list(out.iterdir()) == []
    code, env = run(capsys, str(design), "-o", str(out), "--allow-partial")
    data = check(env, "sldprt_written")
    assert (
        code == 4
        and data["partial"] is True
        and [f["part_name"] for f in data["features"]]
        == [
            "Sketch1",
            "Boss-Extrude1",
        ]
    )
    assert "fillet(2): CadQuery's fillet() is not translated yet" in data["unsupported"]


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"units": "furlong"}, "units is one of"),
        ({"steps": []}, "steps is a list"),
        ({"model": 99}, "no step made the model's workplane 99"),
    ],
)
def test_a_recording_that_cannot_be_read_is_a_usage_error(capsys, tmp_path, out, change, words):
    c, m = plate()
    data = {**c.recording(m, name="plate"), **change}
    (tmp_path / "bad").mkdir()
    design = tmp_path / "bad" / "plate.json"
    design.write_text(json.dumps(data), encoding="utf-8")
    code, env = run(capsys, str(design), "-o", str(out))
    err = check(env, "error")
    assert code == 2 and err["code"] == "invalid_argument" and err["detail"]["parameter"] == "design"
    said = err["reader_message"]
    assert "is not a CadQuery recording SolidSeas reads" in said and words in said
    assert list(out.iterdir()) == []
