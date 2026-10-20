"""``--json`` on every command: one strictly parsed JSON document on standard output,
nothing on standard error, and exit codes that come from the error-code table."""

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from jsonschema_subset import validate
from solidseas import cli, model
from support import ASSEMBLY, FIXTURES, PARTS, fixture_path

O02 = str(fixture_path("o02_boxA.SLDPRT"))
O06 = str(fixture_path("o06_boxA_props_mat_cfg.SLDPRT"))
API_MD = FIXTURES.parent.parent / "docs" / "API.md"
WINDOWS = os.name == "nt"


def _no_constants(name):
    raise ValueError(f"{name} is not strict JSON")


def run(capsys, *argv) -> tuple[int, dict]:
    """Run one command with --json: exactly one strict JSON document out, nothing on stderr."""
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    doc = json.loads(out, parse_constant=_no_constants)  # one document: trailing data would raise
    assert out.endswith("}\n") and out.count("\n}\n") == 1
    return code, doc


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind and env["ok"] is (kind != "error")
    errors = validate(env, model.envelope_schema(kind), strict=True)
    assert errors == [], errors[:5]
    return env["data"] if env["ok"] else env["error"]


@pytest.fixture
def folder(tmp_path) -> Path:
    src = tmp_path / "jobs"
    (src / "sub").mkdir(parents=True)
    for name in (PARTS[1], PARTS[5], ASSEMBLY):
        shutil.copyfile(fixture_path(name), src / name)
    shutil.copyfile(fixture_path(PARTS[3]), src / "sub" / PARTS[3])
    return src


# --------------------------------------------------------------------------- one document per command
def test_info(capsys):
    code, env = run(capsys, "info", O06)
    data = check(env, "document_summary")
    assert code == 0 and env["source"] == {"file": O06}
    with cli.open_document(O06) as doc:
        assert data == doc.summary()  # the same data as Python


def test_props_and_configurations(capsys):
    code, env = run(capsys, "props", O06, "--view", "file")
    assert code == 0 and check(env, "properties")["view"] == "file"
    code, env = run(capsys, "configurations", O06)
    assert code == 0 and len(check(env, "configurations")["configurations"]) == 2


def test_components_and_references(capsys):
    asm = str(fixture_path(ASSEMBLY))
    code, env = run(capsys, "components", asm, "--flat")
    data = check(env, "components")
    assert code == 0 and env["source"] == {"file": asm} and len(data["instances"]) == 2
    code, env = run(capsys, "references", asm)
    data = check(env, "references")
    assert code == 0 and [f["instances"] for f in data["files"]] == [2]
    code, env = run(capsys, "references", O06)  # a part references nothing; still a result
    assert code == 0 and check(env, "references")["files"] == []


def test_bom(capsys):
    asm = str(fixture_path(ASSEMBLY))
    code, env = run(capsys, "bom", asm, "--type", "indented")
    data = check(env, "bom")
    assert code == 0 and env["source"] == {"file": asm} and data["complete"]
    assert [(r["item"], r["part_number"], r["quantity"]) for r in data["rows"]] == [("1", "o02_boxA", 2)]
    with cli.open_document(asm) as doc:
        assert data == model.build_bom(doc, bom_type="indented")  # the same data as Python
    code, env = run(capsys, "bom", O06)  # a part has no BOM; still a result
    assert code == 0 and check(env, "bom")["rows"] == []


def test_paths(capsys):
    asm = str(fixture_path(ASSEMBLY))
    code, env = run(capsys, "paths", asm)
    data = check(env, "path_report")
    assert code == 0 and env["source"] == {"file": asm} and data["complete"]
    assert data["counts"]["paths"] == len(data["paths"]) > 5
    assert data["rewrite"] == {"supported": False, "note": model.REWRITE_NOTE}
    with cli.open_document(asm) as doc:
        assert data == model.build_path_report(doc)  # the same data as Python


def test_streams(capsys):
    code, env = run(capsys, "streams", O02)
    assert code == 0 and len(check(env, "streams")["streams"]) > 30


def test_dump_and_preview(capsys, tmp_path):
    code, env = run(capsys, "dump", O02, "Header2", "-o", str(tmp_path / "h2.bin"))
    assert code == 0 and check(env, "file_written")["stream"] == "Header2"
    code, env = run(capsys, "preview", O02, "-o", str(tmp_path / "p.png"))
    assert code == 0 and check(env, "file_written")["width"] == 640


def test_parasolid(capsys, tmp_path):
    code, env = run(capsys, "parasolid", O02, "-o", str(tmp_path / "xt"))
    data = check(env, "parasolid_result")
    assert code == 0 and data["bodies"] == 1 and data["written"][0]["kind"] == "x_b"


def test_list(capsys, folder):
    code, env = run(capsys, "list", str(folder), "--recursive", "--include", "properties,configurations")
    data = check(env, "listing")
    assert code == 0 and env["source"] == {"folder": str(folder)}
    assert data["counts"]["ok"] == 4 and data["include"] == ["properties", "configurations", "preview"]
    assert all(e["properties"] is not None and e["preview"]["available"] for e in data["entries"])
    code, env = run(capsys, "list", str(folder), "--preview", "inline", "--limit", "1")
    data = check(env, "listing")
    assert (
        code == 0
        and data["truncated_reason"] == "max_entries"
        and data["entries"][0]["preview"]["data_base64"]
    )
    code, env = run(capsys, "list", str(folder), "--preview", "none")
    assert code == 0 and all(e["preview"] is None for e in check(env, "listing")["entries"])


def test_batch(capsys, folder, tmp_path):
    code, env = run(capsys, "batch", str(folder), "-o", str(tmp_path / "out"), "--no-parasolid")
    data = check(env, "batch_summary")
    assert code == 0 and data["files"] == 4 and data["status_counts"] == {"ok": 4}


def test_version(capsys):
    code, env = run(capsys, "version")
    data = check(env, "version")
    assert code == 0 and env["source"] is None and data == model.build_version()


def test_schema(capsys):
    code, index = run(capsys, "schema")
    assert code == 0 and {k["kind"] for k in index["kinds"]} == set(model.KINDS)
    code, schema = run(capsys, "schema", "listing")
    assert code == 0 and schema == model.envelope_schema("listing")
    code, schema = run(capsys, "schema", "listing", "--data")
    assert code == 0 and schema == model.KINDS["listing"].schema
    code, env = run(capsys, "schema", "nope")
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"


def test_every_command_is_covered():
    """The tests above run every command in the table; this keeps them in step.
    ``serve`` runs until it is stopped, so tests/test_serve.py runs it in a child
    process (test_the_cli_serves_until_it_is_stopped)."""
    covered = {"info", "props", "configurations", "streams", "dump", "preview", "parasolid", "list", "batch"}
    covered |= {"version", "schema", "components", "references", "bom", "paths", "serve"}
    covered |= {"export"}  # tests/test_export.py runs it
    covered |= {"convert"}  # tests/test_occt_backend.py runs it
    # tests/test_catalog_surfaces.py runs the catalog's
    covered |= {"index", "where-used", "search", "duplicates", "missing", "changes", "catalog", "catalogs"}
    covered |= {"clear-index"}
    covered |= {"drawing"}  # tests/test_drawing_cli.py runs it
    assert covered == set(cli.COMMANDS)


# --------------------------------------------------------------------------- errors, one document each
def test_missing_file(capsys, tmp_path):
    code, env = run(capsys, "info", str(tmp_path / "nope.SLDPRT"))
    err = check(env, "error")
    assert (
        code == 1 and err["code"] == "not_found" and env["source"] == {"file": str(tmp_path / "nope.SLDPRT")}
    )


def test_not_solidworks(capsys, tmp_path):
    bogus = tmp_path / "bogus.SLDPRT"
    bogus.write_bytes(b"plain text, not a CAD file\n")  # (a STEP start is read as STEP now)
    code, env = run(capsys, "info", str(bogus))
    assert code == 1 and check(env, "error")["code"] == "unknown_format"


@pytest.mark.parametrize(
    "argv",
    [
        ["info", O02, "--bogus"],
        ["no-such-command"],
        ["info"],
        ["list", ".", "--limit", "0"],
        ["list", ".", "--limit", "-1"],
        ["list", ".", "--timeout", "nan"],
        ["props", O06, "--view", "everything"],
        ["--help"],
        ["info", "--help"],
        ["list", "-h"],
    ],
)
def test_usage_errors_are_json_too(capsys, argv):
    code, env = run(capsys, *argv)
    err = check(env, "error")
    assert code == cli.EXIT_USAGE == 2 and err["code"] == "invalid_argument"
    assert err["detail"]["usage"].startswith("usage: solidseas")


def test_help_under_json_carries_the_whole_help_text(capsys):
    code, env = run(capsys, "list", "--help")
    usage = check(env, "error")["detail"]["usage"]
    assert code == 2 and "--max-examined" in usage and "--timeout" in usage  # the help, not just usage
    assert cli.main(["list", "--help"]) == 0  # without --json: the help itself, exit 0
    out, err = capsys.readouterr()
    assert out.startswith("usage: solidseas list") and "--max-examined" in out and err == ""


@pytest.mark.parametrize("argv", [["--version", "--json"], ["--json", "--version"]])
def test_version_flag_under_json_is_the_version_kind(capsys, argv):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    env = json.loads(out, parse_constant=_no_constants)
    assert code == 0 and err == "" and check(env, "version") == model.build_version()
    assert cli.main(["--version"]) == 0  # without --json: one line of text, as before
    assert capsys.readouterr().out == f"solidseas {model.build_version()['solidseas']}\n"


def test_bad_values_found_after_parsing_are_usage_errors(capsys, folder):
    code, env = run(capsys, "list", str(folder), "--include", "thumbnails")
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "include"}
    code, env = run(capsys, "props", O06, "--view", "file", "--configuration", "Default")
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "configuration"}


def test_usage_error_without_json_goes_to_stderr(capsys):
    assert cli.main(["info", O02, "--bogus"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and "unrecognized arguments" in err


def test_json_flag_before_the_command(capsys):
    code = cli.main(["--json", "version"])
    out, err = capsys.readouterr()
    assert code == 0 and err == "" and json.loads(out)["kind"] == "version"


def test_refused_exits_3(capsys, tmp_path):
    src = tmp_path / "project"
    src.mkdir()
    shutil.copyfile(O02, src / "part.SLDPRT")
    code, env = run(capsys, "preview", str(src / "part.SLDPRT"), "-o", str(src / "p.png"))
    assert code == cli.EXIT_REFUSED == 3 and check(env, "error")["code"] == "output_refused"


def test_no_preview(capsys, tmp_path):
    from builders import rebuild

    bare = tmp_path / "in" / "bare.SLDPRT"
    bare.parent.mkdir()
    bare.write_bytes(rebuild(fixture_path("o02_boxA.SLDPRT"), drop=("PreviewPNG", "Preview")))
    code, env = run(capsys, "preview", str(bare), "-o", str(tmp_path / "out.png"))
    assert code == 1 and check(env, "error")["code"] == "no_preview"


def test_partial_listing_and_batch_exit_4(capsys, folder, tmp_path):
    (folder / "damaged.SLDPRT").write_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x04" + b"\x00" * 40)
    code, env = run(capsys, "list", str(folder))
    data = check(env, "listing")
    assert code == cli.EXIT_PARTIAL == 4 and env["ok"] and data["counts"]["error"] == 1
    code, env = run(capsys, "batch", str(folder), "-o", str(tmp_path / "out"), "--no-parasolid")
    data = check(env, "batch_summary")
    assert code == 4 and data["status_counts"] == {"error": 1, "ok": 4}


def test_a_batch_cut_short_by_a_walk_limit_is_partial(capsys, tmp_path):
    # Documents only: which two entries the walker examines first is the file system's
    # order, and on Linux a subfolder can be one of them.
    folder = tmp_path / "jobs"
    folder.mkdir()
    for name in (PARTS[1], PARTS[5], ASSEMBLY):
        shutil.copyfile(fixture_path(name), folder / name)
    out = str(tmp_path / "out")
    code, env = run(capsys, "batch", str(folder), "-o", out, "--no-parasolid", "--max-examined", "2")
    data = check(env, "batch_summary")
    assert code == 4 and data["walk"]["truncated"] == "max_examined" and data["files"] == 2
    assert data["walk"]["entries"] == 2  # the walker looked at two directory entries, no more


@pytest.mark.skipif(not WINDOWS, reason="byte-range locks through msvcrt")
def test_locked_file(capsys, tmp_path):
    import msvcrt

    src = tmp_path / "locked.SLDPRT"
    shutil.copyfile(O02, src)
    size = src.stat().st_size
    with open(src, "rb") as holder:
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, size)
        try:
            code, env = run(capsys, "info", str(src))
        finally:
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, size)
    err = check(env, "error")
    assert code == 1 and (err["code"], err["retryable"]) == ("locked", True)


def test_interrupted_exits_130(capsys, monkeypatch):
    def stop(args, doc):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, "info", cli.Command("info", "document_summary", "file", stop))
    code, env = run(capsys, "info", O02)
    assert code == cli.EXIT_INTERRUPTED == 130 and check(env, "error")["code"] == "interrupted"


def test_an_unexpected_bug_is_still_one_document(capsys, monkeypatch):
    def broken(args, doc):
        raise RuntimeError("a bug")

    monkeypatch.setitem(cli.COMMANDS, "info", cli.Command("info", "document_summary", "file", broken))
    code, env = run(capsys, "info", O02)
    err = check(env, "error")
    assert code == 1 and (err["code"], err["reader_message"]) == ("internal", "a bug")


# --------------------------------------------------------------------------- the exit-code table
def _api_exit_table() -> dict[int, set[str]]:
    text = API_MD.read_text(encoding="utf-8")
    section = text[text.index("### 7.2 Exit codes") : text.index("### 7.3")]
    table: dict[int, set[str]] = {}
    for row in section.splitlines():
        m = re.match(r"\| (\d+) \|", row)
        if m:
            table[int(m.group(1))] = set(re.findall(r"`([a-z_]+)`", row))
    return table


def test_exit_codes_come_from_the_error_codes():
    table = _api_exit_table()
    assert sorted(table) == [0, 1, 2, 3, 4, 130]
    by_exit: dict[int, set[str]] = {}
    for code, spec in model.ERROR_CODES.items():
        if spec.cli_exit is not None:
            by_exit.setdefault(spec.cli_exit, set()).add(code)
            assert cli.exit_code(code) == spec.cli_exit
    assert sum(len(v) for v in by_exit.values()) >= 25
    assert set(by_exit) == {1, 2, 3, 130}  # 0 and 4 are results, not errors
    for exit_value, codes in by_exit.items():
        assert table[exit_value] == codes, exit_value
    assert table[0] == table[4] == set()
    assert cli.exit_code("unauthorized") == 1  # a service-only code still fails cleanly


def test_the_command_table_matches_the_parser_and_the_kinds():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert set(sub.choices) == set(cli.COMMANDS) and len(cli.COMMANDS) >= 11
    for name, command in cli.COMMANDS.items():
        if command.kind is not None:
            assert name in model.KINDS[command.kind].cli_commands, name
    printed = {c for spec in model.KINDS.values() for c in spec.cli_commands}
    assert printed == {n for n, c in cli.COMMANDS.items() if c.kind is not None}


def _code_only(source: str) -> str:
    q = chr(34) * 3
    without_docstrings = re.sub(q + ".*?" + q, "", source, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in without_docstrings.split("\n"))


def test_the_cli_has_no_json_encoder_of_its_own():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    code = _code_only(source)
    assert "model.dumps(" in code and "def main(" in code  # the anchors exist
    assert "json.dumps(" not in code and "import json" not in code
