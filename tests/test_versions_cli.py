"""``solidseas history``, ``snapshot`` and ``diff``: one strict JSON document under
``--json`` that matches its kind's schema, plain words without it, and the exit codes of
the error-code table."""

import json
import shutil

import pytest

from jsonschema_subset import validate
from solidseas import cli, model
from support import FIXTURES

XB_A = FIXTURES / "o02_boxA.x_b"  # SOLIDWORKS' own Parasolid exports, public fixtures
XB_B = FIXTURES / "o07_boxB_h31.x_b"


def run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind and env["ok"] is (kind != "error")
    assert validate(env, model.envelope_schema(kind), strict=True) == []
    return env["data"] if env["ok"] else env["error"]


@pytest.fixture
def part(tmp_path):
    path = tmp_path / "jobs" / "bracket.x_b"
    path.parent.mkdir()
    shutil.copyfile(XB_A, path)
    return path


def test_snapshot_history_and_diff_as_json(capsys, part, tmp_path):
    code, env = run(capsys, "snapshot", str(part), "--note", "first cut")
    data = check(env, "snapshot_taken")
    assert code == 0 and data["new"] and data["snapshot"]["subject"] == "first cut"
    assert env["source"] == {"file": str(part)}
    code, env = run(capsys, "snapshot", str(part))
    assert code == 0 and check(env, "snapshot_taken")["new"] is False
    shutil.copyfile(XB_B, part)
    code, env = run(capsys, "history", str(part))
    data = check(env, "file_history")
    assert code == 0 and data["source"] == "snapshots" and data["working"]["state"] == "changed"
    assert [v["kind"] for v in data["versions"]] == ["working", "snapshot"]
    code, env = run(capsys, "diff", str(part))
    data = check(env, "version_diff")
    assert code == 0 and (data["from"]["number"], data["to"]["number"]) == (1, 2)
    (row,) = data["geometry"]["configurations"]
    assert row["status"] == "changed" and "size_z_mm" in {c["measure"] for c in row["changes"]}
    code, env = run(capsys, "diff", str(part), "v1", "working", "--no-measures")
    (row,) = check(env, "version_diff")["geometry"]["configurations"]
    assert code == 0 and row["changes"] == [] and row["to"]["measures"] is None
    store = tmp_path / "elsewhere"
    code, env = run(capsys, "snapshot", str(part), "--store", str(store))
    assert code == 0 and check(env, "snapshot_taken")["store"] == {"location": "folder", "path": str(store)}
    code, env = run(capsys, "history", str(part), "--store", str(store), "--source", "snapshots")
    assert code == 0 and [v["kind"] for v in check(env, "file_history")["versions"]] == ["snapshot"]


def test_plain_words(capsys, part):
    assert cli.main(["history", str(part)]) == 0
    out = capsys.readouterr().out
    assert "no snapshot yet" in out and "no versions yet" not in out
    assert cli.main(["snapshot", str(part)]) == 0
    assert "took snapshot v1" in capsys.readouterr().out
    assert cli.main(["snapshot", str(part)]) == 0
    assert "nothing new was stored" in capsys.readouterr().out
    shutil.copyfile(XB_B, part)
    assert cli.main(["diff", str(part)]) == 0
    out = capsys.readouterr().out
    assert "v1" in out and "working copy" in out and "size in z 30 mm -> 31 mm" in out
    assert "volume 6,000 mm3 -> 6,200 mm3 (+3.33%)" in out


def test_errors_and_their_exit_codes(capsys, part, tmp_path):
    code, env = run(capsys, "diff", str(part))  # one version: nothing to compare
    assert code == 1 and check(env, "error")["code"] == "version_not_found"
    code, env = run(capsys, "diff", str(part), "v7", "working")
    err = check(env, "error")
    assert code == 1 and err["code"] == "version_not_found" and err["detail"] == {"parameter": "older"}
    code, env = run(capsys, "history", str(part), "--source", "git")
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "source"}
    code, env = run(capsys, "history", str(part), "--project", str(tmp_path), "--store", str(tmp_path))
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"  # one store or the other
    code, env = run(capsys, "history", str(tmp_path / "nothing.x_b"))
    assert code == 1 and check(env, "error")["code"] == "not_found"
    code, env = run(capsys, "snapshot", str(part), "--project", str(tmp_path / "other"))
    assert code == 1 and check(env, "error")["code"] == "not_found"
    assert cli.main(["diff", str(part), "nope"]) == 1
    assert "no version of the file is named 'nope'" in capsys.readouterr().err


def test_every_version_kind_and_code_is_registered():
    for kind, command in (
        ("file_history", "history"),
        ("snapshot_taken", "snapshot"),
        ("version_diff", "diff"),
    ):
        assert model.KINDS[kind].cli_commands == (command,) and cli.COMMANDS[command].kind == kind
    assert model.ERROR_CODES["version_not_found"].cli_exit == 1
    assert model.ERROR_CODES["version_unavailable"].http_status == 409
