"""The OCCT backend (``docs/OCCT.md`` tier 1, ``docs/EXTENSIONS.md`` section 9): IGES and
BREP files read through ``solidseas.convert``'s ``occt`` backend, which runs Open CASCADE
in the OCCT extension's helper, and IGES, BREP and STEP written through it.

Most of these tests need no Open CASCADE: a stand-in helper, the standard library alone,
answers the protocol as the real one does and hands back a STEP file of the fixtures, so
the core's side (where the helper comes from, the staging, what it reads back and how it
fails) is tested everywhere. The helper itself runs in two more ways when OCP is there:
in this process, when ``import OCP`` works here, and as a program in an interpreter where
it does (``SOLIDSEAS_OCCT_PYTHON``, the oracle's variable, or this one), through the
viewer's and the command line's own path. Both skip cleanly when OCP is not installed.
"""

import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from solidseas import cli, convert, model, policy
from solidseas.convert import occt
from solidseas.errors import (
    FormatNotSupportedError,
    OutputRefusedError,
    SldFormatError,
    UnsupportedOperationError,
    WorkerTimeoutError,
)
from solidseas.formats import occt as reader
from solidseas.formats import open_model, registry
from solidseas_app import extensions as X
from solidseas_app.extensions import occt_helper
from support import FIXTURES, fixture_path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
HELPER = SRC / "solidseas_app" / "extensions" / "occt_helper.py"
STEP_FIXTURE = fixture_path("o02_boxA.step")

# A stand-in for the helper: the protocol, and a STEP file of the fixtures as every result.
# What the staged file holds says what it does instead: CRASH ends it, SLOW never answers,
# REFUSE answers with an error, ELSEWHERE writes outside the folder it was given, OPEN and
# INVALID change the report, and FEWER a check's face count. OCCT_STANDIN_OPS names the
# operations it offers (an older helper had no check).
STANDIN = r"""
import json, os, shutil, sys, time
step = os.environ["OCCT_STANDIN_STEP"]
names = {"step": "model.step", "iges": "model.igs", "occt_brep": "model.brep"}
ops = os.environ.get("OCCT_STANDIN_OPS", "convert,check").split(",")
ready = {"event": "ready", "protocol": 1, "helper": "occt", "operations": ops, "versions": {"occt": "7.9.3"}}
print(json.dumps(ready), flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    rid = msg["id"]
    if msg["op"] == "shutdown":
        print(json.dumps({"id": rid, "ok": True, "result": {}}), flush=True)
        break
    args = msg["args"]
    data = open(args["path"], "rb").read()
    with open(os.environ["OCCT_STANDIN_LOG"], "a") as log:
        log.write(json.dumps({"op": msg["op"], "args": args, "argv": sys.argv[1:]}) + "\n")
    if b"CRASH" in data:
        os._exit(3)
    if b"SLOW" in data:
        time.sleep(60)
    if b"REFUSE" in data:
        error = {"code": "no_geometry", "message": "the file holds curves or points only"}
        print(json.dumps({"id": rid, "ok": False, "error": error}), flush=True)
        continue
    if msg["op"] == "check":
        report = {
            "from": "step", "roots": 1, "roots_transferred": 1, "shapes": 1, "solids": 1, "sheets": 0,
            "free_faces": 0, "faces": 5 if b"FEWER" in data else 6, "free_edges": 0,
            "open_solid_shells": 1 if b"OPEN" in data else 0, "nonmanifold_edges": 0,
            "valid": b"INVALID" not in data, "volume_mm3": 6000.0, "area_mm2": 2200.0,
            "box_mm": [0, 0, 0, 10, 20, 30], "extra": "dropped",
        }
        print(json.dumps({"id": rid, "ok": True, "result": {"report": report}}), flush=True)
        continue
    target = os.path.join(args["out_dir"], names[args["to"]])
    if b"ELSEWHERE" in data:
        target = os.path.join(os.path.dirname(args["out_dir"]), "elsewhere.step")
    shutil.copyfile(step, target)
    report = {
        "from": args["from"], "solids": 1, "faces": 6, "solids_sewn": 1, "free_faces": 0,
        "open_shells": 2 if b"OPEN" in data else 0, "valid": b"INVALID" not in data,
        "unit": "mm", "application": {"name": "Sender\x07 CAD", "version": 7}, "extra": "dropped",
    }
    result = {"path": target, "bytes": os.path.getsize(target), "format": args["to"], "report": report}
    print(json.dumps({"id": rid, "ok": True, "result": result}), flush=True)
"""


def _iges_record(text: str, section: str, n: int) -> bytes:
    return (text.ljust(72)[:72] + section + str(n).rjust(7)).encode("latin-1") + b"\n"


def iges(start: str = "a synthetic IGES file", params: list[str] | None = None) -> bytes:
    """A small IGES file: a start line and a global section of ``params`` (written as they
    are, so a string is given as a Hollerith ``nH...``), cut across records as IGES does."""
    params = params if params is not None else [",", ";", "4Hpart", "8Hpart.igs", "6HSender", "3Hv12"]
    text = ",".join(params) + ";"
    out = _iges_record(start, "S", 1)
    for i in range(0, len(text), 72):
        out += _iges_record(text[i : i + 72], "G", i // 72 + 1)
    return out + _iges_record("S      1G      1D      0P      0", "T", 1)


@pytest.fixture
def fresh():
    """The backend with no helper running and nothing kept, before and after the test."""
    occt.forget()
    yield occt.BACKEND
    occt.forget()


@pytest.fixture
def standin(tmp_path, monkeypatch, fresh):
    """The backend set up from a checkout, with the stand-in as its helper module."""
    script = tmp_path / "standin.py"
    script.write_text(STANDIN, encoding="utf-8")
    log = tmp_path / "standin.log"
    monkeypatch.setenv(occt.ENV_PYTHON, sys.executable)
    monkeypatch.setenv("OCCT_STANDIN_STEP", str(STEP_FIXTURE))
    monkeypatch.setenv("OCCT_STANDIN_LOG", str(log))
    monkeypatch.setattr(occt, "helper_script", lambda: str(script))
    return log


def install_standin_program(tmp_path: Path, monkeypatch) -> Path:
    """Set the backend up from a checkout whose interpreter is a program that runs the
    stand-in, so the processes this one starts (a worker, the export's process) find the
    stand-in too, through their own copy of the backend. Returns the stand-in's log."""
    if os.name == "nt":
        pytest.skip("the stand-in interpreter is a shell script")
    script = tmp_path / "standin.py"
    script.write_text(STANDIN, encoding="utf-8")
    program = tmp_path / "standin-python"
    program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    log = tmp_path / "standin.log"
    monkeypatch.setenv(occt.ENV_PYTHON, str(program))
    monkeypatch.setenv("OCCT_STANDIN_STEP", str(STEP_FIXTURE))
    monkeypatch.setenv("OCCT_STANDIN_LOG", str(log))
    return log


@pytest.fixture
def standin_program(tmp_path, monkeypatch, fresh):
    """:func:`install_standin_program`, its log."""
    return install_standin_program(tmp_path, monkeypatch)


def _requests(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@lru_cache(maxsize=1)
def _step_volume() -> float:
    with open_model(str(STEP_FIXTURE)) as doc:
        return doc.scene().objects[0].measures()["volume_m3"]


# --------------------------------------------------------------------------- boundaries
def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_helper_imports_the_standard_library_and_ocp_only_and_nothing_imports_it():
    tops = {n.split(".")[0] for n in _imports(HELPER)}
    assert "OCP" in tops and tops - {"OCP"} <= set(sys.stdlib_module_names)
    importers = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if p != HELPER and any("occt_helper" in n for n in _imports(p))
    ]
    assert importers == []
    # the core finds it as a file, never by importing it, and the viewer's build leaves it out
    assert occt.helper_script() == str(HELPER)
    spec = (ROOT / "packaging" / "SolidSeasViewer.spec").read_text(encoding="utf-8")
    assert '"OCP", "solidseas_app.extensions.occt_helper",' in spec


def test_brep_and_iges_files_are_told_by_what_they_hold():
    text = b"DBRep_DrawableShape\n\nCASCADE Topology V3, (c) Open Cascade\nLocations 0\n"
    binary = b"\nOpen CASCADE Topology V4, (c) Open Cascade\nLocations 0\n"
    old = b"CASCADE Topology V1, (c) Matra-Datavision\nLocations 0\n"
    for head, variant in ((text, "text"), (binary, "binary"), (old, "text")):
        got = registry.detect_head(head, len(head), "shape.brep")
        assert (got.format, got.variant, got.by) == ("occt_brep", variant, "both")
        assert registry.detect_head(head, len(head), "noname").format == "occt_brep"
        assert occt_helper.brep_kind(head) == variant
    assert registry.detect_head(b"not a shape", 11, "x.brep").by == "extension"
    data = iges()
    assert registry.detect_head(data, len(data), "part.igs").format == "iges"
    assert registry.by_extension("a.BREP").id == "occt_brep" and registry.FORMATS["occt_brep"].name == "BREP"


def test_the_iges_head_is_read_without_converting_anything(standin):
    params = [
        "1H/",
        "1H|",
        "9HBracket,A",  # a Hollerith string holds the delimiter as text
        "11Hbracket.igs",
        "10HSender CAD",
        "4Hv7.1",
        "32",
        "38",
        "6",
        "308",
        "15",
        "9HReceiver",
        "1.",
        "1",  # inches
        "4HINCH",
        "1",
        "0.01",
        "15H20240131.142530",
        "1E-5",
        "100.",
        "6HA. Lee",
        "8HSome Org",
        "11",
        "0",
    ]
    text = "/".join(params) + "|"
    body = b"".join(_iges_record(text[i : i + 72], "G", i // 72 + 1) for i in range(0, len(text), 72))
    data = _iges_record("start", "S", 1) + body
    fields = reader.global_fields(reader.global_section(data))
    assert fields[:6] == ["/", "|", "Bracket,A", "bracket.igs", "Sender CAD", "v7.1"]
    assert fields[13] == "1" and fields[20] == "A. Lee"
    # records without line ends, as some writers store them
    flat = b"".join(r.rstrip(b"\n") for r in data.splitlines(keepends=True))
    assert reader.global_fields(reader.global_section(flat))[:3] == ["/", "|", "Bracket,A"]
    with open_model(data, name="bracket.igs") as doc:  # opening converts nothing
        assert doc.format == "iges" and doc.doc_type == "part" and doc.kind == "brep"
        assert doc.units == {"length": "in", "scale_m": 0.0254, "source": "file"}
        assert doc.application == {"name": "Sender CAD", "version": "v7.1"}
        assert doc.fields.title == "Bracket,A" and doc.fields.author == "A. Lee"
        assert doc.fields.last_saved_utc.isoformat() == "2024-01-31T14:25:30"
        props = {p.name: p.value for p in doc.properties}
        assert props["organization"] == "Some Org" and props["unit_name"] == "INCH"
        assert doc.report is None and doc.counts()["faces"] is None
    with open_model(
        iges(params=[",", ";", "4Hpart", "1H ", "1H ", "1H ", *["1"] * 7, "99"]), name="p.igs"
    ) as d:
        assert d.units["source"] == "assumed" and [w.code for w in d.warnings] == ["units_assumed"]
    assert _requests(standin) == []


# --------------------------------------------------------------------------- without the backend
def test_without_the_backend_iges_and_brep_say_what_they_need(tmp_path, capsys, fresh):
    part = tmp_path / "part.igs"
    part.write_bytes(iges())
    assert not registry.readable("iges") and not registry.readable("occt_brep")
    assert convert.unavailable("iges") == occt.NOT_ADDED
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(part)
    assert (
        exc.value.detail == {"rule": "needs_extension", "value": "iges"} and str(exc.value) == occt.NOT_ADDED
    )
    assert cli.main(["info", str(part), "--json"]) == 1
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["detail"] == {"rule": "needs_extension", "value": "iges"}
    assert env["error"]["message"] == model.RULE_MESSAGES[("format_not_supported", "needs_extension")]
    # convert says so too, for every format it writes, before it opens anything
    out = tmp_path / "out"
    out.mkdir()
    code = cli.main(["convert", str(STEP_FIXTURE), "--format", "iges", "-o", str(out), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 1 and env["error"]["detail"] == {"rule": "needs_extension", "value": "iges"}
    assert list(out.iterdir()) == []
    # a checkout's interpreter that is not there is said plainly
    os.environ[occt.ENV_PYTHON] = str(tmp_path / "missing" / "python")
    try:
        occt.BACKEND._checked = None
        assert occt.ENV_PYTHON in convert.unavailable("iges") and not registry.readable("iges")
    finally:
        del os.environ[occt.ENV_PYTHON]
        occt.BACKEND._checked = None


def _occt_package(tmp_path, program: bytes) -> Path:
    from solidseas_app.extensions import package

    folder = tmp_path / "occt-package"
    folder.mkdir()
    (folder / "solidseas-occt.exe").write_bytes(program)
    return Path(package.build_package("occt", str(folder), str(tmp_path / "zips"), memory_mb=3072))


def test_the_extension_s_package_and_switch_decide(tmp_path, monkeypatch, fresh):
    monkeypatch.setenv("SOLIDSEAS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OCCT_STANDIN_STEP", str(STEP_FIXTURE))
    monkeypatch.setenv("OCCT_STANDIN_LOG", str(tmp_path / "log"))
    pkg = _occt_package(tmp_path, STANDIN.encode("utf-8"))
    X.add_package(
        X.check_package(str(pkg), accepted={"occt": [hashlib.sha256(pkg.read_bytes()).hexdigest()]})
    )
    assert convert.unavailable("iges") == occt.SWITCHED_OFF
    X.write_state(X.state_path(), X.switched(X.read_state(), "occt", True))
    fresh._checked = None
    assert convert.unavailable("iges") is None and registry.readable("iges")
    previous = policy.set_reader(lambda: policy.Policy(allowed_extensions=("video",)))
    try:
        fresh._checked = None
        assert convert.unavailable("iges") == occt.NOT_ALLOWED
    finally:
        policy.set_reader(previous)
    fresh._checked = None
    # The package's helper is started by the extensions module, which checks its files; the
    # stand-in runs through Python, as the extension tests run theirs.
    real = X.start_helper
    monkeypatch.setattr(
        X, "start_helper", lambda *a, **k: real(*a, launcher=lambda prog: [sys.executable, "-I", prog], **k)
    )
    part = tmp_path / "part.igs"
    part.write_bytes(iges())
    with open_model(part) as doc:
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(_step_volume())
    assert fresh._helper is not None and fresh._helper.label == "the OCCT backend helper"
    fresh.close()
    with open(os.path.join(X.installed_dir("occt"), "solidseas-occt.exe"), "ab") as fh:
        fh.write(b"\n# changed after it was added\n")
    fresh._cache.clear()
    with pytest.raises(FormatNotSupportedError, match="could not start.*not the file it was added with"):
        with open_model(part) as doc:
            doc.scene()


# --------------------------------------------------------------------------- the core's side
def test_an_iges_file_reads_through_the_backend_as_a_step_model(tmp_path, standin):
    part = tmp_path / "bracket.igs"
    part.write_bytes(iges("OPEN INVALID"))
    assert registry.readable("iges")
    with open_model(part) as doc:
        assert doc.report is None
        scene = doc.scene()
        assert scene.objects[0].measures()["volume_m3"] == pytest.approx(_step_volume())
        assert doc.step_bytes == STEP_FIXTURE.read_bytes()
        assert doc.report["solids_sewn"] == 1 and doc.report["open_shells"] == 2
        assert doc.report["application"] == {"name": "Sender CAD", "version": None}  # data, cleaned
        assert "extra" not in doc.report
        assert {"surfaces_not_closed", "check_failed"} <= {w.code for w in doc.warnings}
        assert doc.tree().nodes and len(doc.bodies()) == 1 and doc.counts()["faces"] == 6
        assert doc.format == "iges" and doc.units["length"] == "mm"  # the IGES file's own head
    (sent,) = _requests(standin)
    args = sent["args"]
    assert args["from"] == "iges" and args["to"] == "step" and args["name"] == "model"
    assert os.path.basename(args["path"]) == "model.igs" and sent["argv"] == ["--memory-mb", "3072"]
    assert not os.path.exists(args["path"]) and not os.path.exists(args["out_dir"])  # staging removed
    # the same file again is converted once
    with open_model(part) as doc:
        doc.scene()
    assert len(_requests(standin)) == 1


def test_the_core_takes_only_what_the_helper_was_told_to_write(standin, fresh):
    with pytest.raises(SldFormatError, match="somewhere it was not given"):
        fresh.convert_bytes(b"ELSEWHERE", "iges", "step")
    with pytest.raises(SldFormatError, match="curves or points only"):
        fresh.convert_bytes(b"REFUSE", "iges", "step")
    with pytest.raises(SldFormatError, match="stopped while it read the file"):
        fresh.convert_bytes(b"CRASH", "occt_brep", "step")
    # a crash ends that file alone: the next one starts a new helper
    made = fresh.convert_bytes(b"a good file", "occt_brep", "iges", name="part")
    assert made.format == "iges" and made.data == STEP_FIXTURE.read_bytes()
    with pytest.raises(FormatNotSupportedError, match="does not convert"):
        fresh.convert_bytes(b"x", "stl", "step")


def test_a_file_that_takes_too_long_ends_the_helper(standin, fresh, monkeypatch):
    monkeypatch.setattr(occt, "SECONDS", 2.0)
    with pytest.raises(WorkerTimeoutError, match="did not finish"):
        fresh.convert_bytes(b"SLOW", "iges", "step")
    assert not fresh._helper.alive
    assert fresh.convert_bytes(b"quick", "iges", "step").data == STEP_FIXTURE.read_bytes()


def test_a_step_file_is_checked_through_the_helper(standin, fresh, monkeypatch):
    report = fresh.check_bytes(b"a STEP file")
    assert report["occt"] == "7.9.3" and report["faces"] == 6 and report["valid"] is True
    assert report["volume_mm3"] == 6000.0 and report["box_mm"] == [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]
    assert "extra" not in report and "from" not in report  # a reply is data: only what it should hold
    assert occt.step_findings(report, solids=1, sheets=0, faces=6) == []
    (sent,) = _requests(standin)
    assert sent["op"] == "check" and sorted(sent["args"]) == ["from", "path"]
    assert sent["args"]["from"] == "step" and not os.path.exists(sent["args"]["path"])  # staging removed
    bad = fresh.check_bytes(b"OPEN INVALID FEWER")
    assert occt.step_findings(bad, solids=1, sheets=0, faces=6) == [
        "Open CASCADE read 5 face(s) where 6 were written",
        "1 shell(s) of a solid are not closed",
        "Open CASCADE's own check finds faults in the shape",
    ]
    assert len(occt.step_findings(bad)) == 2  # no counts given: none compared
    assert occt.step_findings({"roots": 0}) == ["Open CASCADE found nothing in the file to read"]
    assert occt.step_findings({"roots": 3, "roots_transferred": 2}) == [
        "Open CASCADE read 2 of the file's 3 roots"
    ]
    junk = occt._check_report(
        {"faces": -1, "solids": True, "valid": "yes", "volume_mm3": float("nan"), "box_mm": [1, 2]}, "7"
    )
    assert junk["faces"] is junk["solids"] is junk["valid"] is junk["volume_mm3"] is junk["box_mm"] is None
    assert junk["occt"] is None
    with pytest.raises(FormatNotSupportedError, match="checks STEP files"):
        fresh.check_bytes(b"x", "iges")
    # a helper of an older package, with no check, says to add this release's
    monkeypatch.setenv("OCCT_STANDIN_OPS", "convert")
    fresh.forget()
    with pytest.raises(FormatNotSupportedError) as exc:
        fresh.check_bytes(b"a STEP file")
    assert str(exc.value) == occt.NO_CHECK and exc.value.detail["rule"] == "needs_extension"


def test_export_check_reads_the_step_file_back(tmp_path, standin, capsys, monkeypatch):
    from jsonschema_subset import validate

    out = tmp_path / "out"
    out.mkdir()
    part = str(fixture_path("o02_boxA.SLDPRT"))
    assert cli.main(["export", part, "--format", "step", "--check", "-o", str(out)]) == 0
    said = capsys.readouterr().out
    assert (
        "checked with Open CASCADE 7.9.3: it reads the file as written, 1 solid(s), 0 sheet(s), 6 faces, "
        "closed and valid" in said
    )
    assert "Open CASCADE 7.9.3 measures volume 6,000 cubic mm, area 2,200 square mm" in said
    (sent,) = _requests(standin)
    assert sent["op"] == "check" and sent["args"]["from"] == "step"
    code = cli.main(["export", part, "--format", "step", "--check", "-o", str(out), "--force", "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 0 and env["data"]["check"]["sound"] is True and env["data"]["check"]["findings"] == []
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []
    # a reading that disagrees with what was written: exit 1, the file kept, each finding said
    real = occt.BACKEND.check_bytes
    monkeypatch.setattr(occt.BACKEND, "check_bytes", lambda data, fmt="step": {**real(data), "faces": 5})
    code = cli.main(["export", part, "--format", "step", "--check", "-o", str(out), "--force"])
    said = capsys.readouterr().out
    assert code == 1 and "the file does not read as written" in said
    assert (
        "check: Open CASCADE read 5 face(s) where 6 were written" in said
        and (out / "o02_boxA.step").is_file()
    )
    # without --check nothing is read back, and the field is null
    code = cli.main(["export", part, "--format", "step", "-o", str(out), "--force", "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 0 and env["data"]["check"] is None
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []
    # 3MF and STL have none
    assert cli.main(["export", part, "--format", "3mf", "--check", "-o", str(out)]) == 2
    assert "--check is for --format step" in capsys.readouterr().err
    # and without the backend it is said before anything is written
    monkeypatch.delenv(occt.ENV_PYTHON)
    occt.BACKEND._checked = None
    empty = tmp_path / "empty"
    empty.mkdir()
    code = cli.main(["export", part, "--format", "step", "--check", "-o", str(empty), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 1 and env["error"]["detail"] == {"rule": "needs_extension", "value": "step"}
    assert list(empty.iterdir()) == []


def test_convert_writes_a_new_file_through_the_backend(tmp_path, standin, capsys):
    out = tmp_path / "out"
    out.mkdir()
    result = convert.convert(STEP_FIXTURE, out / "box.igs", "iges")
    assert (result.format, result.backend, result.source_format) == ("iges", "occt", "step")
    assert Path(result.path).read_bytes() == STEP_FIXTURE.read_bytes() and result.report["faces"] == 6
    with pytest.raises(OutputRefusedError):
        convert.convert(STEP_FIXTURE, out / "box.igs", "iges")
    assert convert.convert(STEP_FIXTURE, out / "box.igs", "iges", overwrite=True).bytes == result.bytes
    # a Parasolid file goes through the STEP SolidSeas writes of it
    convert.convert(fixture_path("o02_boxA.x_b"), out / "box.brep", "brep")
    sent = _requests(standin)[-1]["args"]
    assert (sent["from"], sent["to"], sent["name"]) == ("step", "occt_brep", "o02_boxA")
    with pytest.raises(UnsupportedOperationError, match="STL files cannot be converted"):
        convert.convert(fixture_path("o02_boxA.STL"), out / "mesh.igs", "iges")
    with pytest.raises(Exception, match="format is one of"):
        convert.convert(STEP_FIXTURE, out / "x.stl", "stl")
    # the command line, with its write guards and the file_written envelope
    code = cli.main(["convert", str(STEP_FIXTURE), "--format", "brep", "-o", str(out), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 0 and env["kind"] == "file_written" and env["data"]["source"] == "occt"
    assert env["data"]["output"] == str(out / "o02_boxA.brep")
    assert cli.main(["convert", str(STEP_FIXTURE), "--format", "step", "-o", str(out / "x.igs")]) != 0
    assert "must end in .step or .stp" in capsys.readouterr().err
    assert cli.main(["convert", str(STEP_FIXTURE), "--format", "iges", "-o", str(out / "y.iges")]) == 0
    assert "IGES through Open CASCADE: 1 solid(s), 6 face(s)" in capsys.readouterr().out


def test_the_rest_service_s_workers_start_the_helper_only_for_iges_and_brep(
    tmp_path, standin_program, monkeypatch
):
    from serve_support import Running

    root = tmp_path / "root"
    root.mkdir()
    (root / "bracket.igs").write_bytes(iges())
    running = Running({"m": root}, workers=1, formats=("iges",))
    try:
        assert running.server.pool.helpers_per_worker == 1
        doc = running.get("document", root="m", path="bracket.igs")
        assert doc.status == 200, doc.body[:300]
        data = doc.json()["data"]
        assert data["format"] == "iges" and data["counts"]["faces"] == 6
        assert data["tree"]["nodes"][0]["name"] == "o02_boxA"  # the stand-in's STEP model
        picture = running.get("preview", root="m", path="bracket.igs")
        assert picture.status == 200 and picture.body.startswith(b"\x89PNG")
        assert running.get("properties", root="m", path="bracket.igs").status == 200
    finally:
        running.close()
    # the worker converted the file once, for the tree and the picture, from its own copy
    (sent,) = _requests(standin_program)
    assert sent["args"]["from"] == "iges" and not os.path.exists(sent["args"]["path"])
    assert not str(sent["args"]["path"]).startswith(str(root))
    # a service that reads no IGES or BREP lets its workers start nothing
    running = Running({"m": root}, workers=1, formats=("step", "stl"))
    try:
        assert running.server.pool.helpers_per_worker == 0
    finally:
        running.close()
    # nor does one whose backend is not there, which says so for the file's geometry
    monkeypatch.delenv(occt.ENV_PYTHON)
    occt.BACKEND._checked = None
    running = Running({"m": root}, workers=1, formats=("iges",))
    try:
        assert running.server.pool.helpers_per_worker == 0
        refused = running.get("document", root="m", path="bracket.igs")
        assert refused.status == 422 and refused.json()["error"]["detail"]["rule"] == "needs_extension"
    finally:
        running.close()


def test_the_helper_s_conversation_holds_without_open_cascade():
    lines = [
        b"not json\n",
        b'["a list"]\n',
        b'{"id": 1, "op": "nope"}\n',
        b'{"id": 2, "op": "convert", "args": {"path": "//server/share/x.igs", "from": "iges", '
        b'"to": "step", "out_dir": "."}}\n',
        b'{"id": 3, "op": "convert", "args": {"path": "x", "from": "stl", "to": "step", "out_dir": "."}}\n',
        b'{"id": 7, "op": "check", "args": {"path": "\\\\\\\\server\\\\share\\\\x.step", "from": "step"}}\n',
        b'{"id": 8, "op": "check", "args": {"path": "x.igs", "from": "iges"}}\n',
        b'{"id": 9, "op": "check", "args": {"path": "no such file.step", "from": "step"}}\n',
        b'{"id": 4, "op": "shutdown"}\n',
        b'{"id": 5, "op": "nope"}\n',
    ]
    said: list[dict] = []
    assert occt_helper.serve(iter(lines).__next__, said.append) == 0
    assert [m["id"] for m in said] == [None, None, 1, 2, 3, 7, 8, 9, 4]
    assert said[0]["error"]["code"] == "invalid_request" and said[2]["error"]["code"] == "unknown_op"
    assert said[3]["error"] == {"code": "refused", "message": "path is a network path"}
    assert said[4]["error"]["message"].startswith("from is one of")
    # a check reads a STEP file the core staged, never a network path, and nothing else
    assert said[5]["error"] == {"code": "refused", "message": "path is a network path"}
    assert said[6]["error"] == {"code": "refused", "message": "from is one of step"}
    assert said[7]["error"] == {"code": "refused", "message": "path is not a plain file"}
    assert "check" in occt_helper.OPERATIONS and occt_helper.CHECKS == ("step",)
    # a line too long is answered once, its rest read and dropped
    long = [
        b"x" * (occt_helper.MAX_REQUEST_BYTES + 1),
        b"y" * 10 + b"\n",
        b'{"id": 6, "op": "shutdown"}\n',
        b"",
    ]
    said.clear()
    assert occt_helper.serve(iter(long).__next__, said.append) == 0
    assert [(m["id"], m["ok"]) for m in said] == [(None, False), (6, True)]


# --------------------------------------------------------------------------- the build and notices
def test_the_package_is_built_with_its_notices_and_every_library_s_licence():
    build = (ROOT / "scripts" / "build-extensions.ps1").read_text(encoding="utf-8")
    section = build[build.index("if ('occt' -in $Only) {\n        $folder") :]
    section = section[: section.index("$zips = ")]
    for needed in (
        "requirements\\occt-helper.txt",
        "--require-hashes",
        "packaging\\occt\\libraries.tsv",
        "--onedir",
        "src\\solidseas_app\\extensions\\occt_helper.py",
        '"helper": "occt"',
        "$OcctSource",
        "makes use of facilities provided by the Open CASCADE",
        "'LGPL-2.1.txt', 'OCCT_LGPL_EXCEPTION.txt', 'OCP-LICENSE.txt', 'OCP-third-party.txt'",
        "Copy-Licences $folder ($ownLicences",
        "Invoke-Package 'occt' $folder $notices 3072",
    ):
        assert needed in section, needed
    assert "The OCCT package needs -OcctSource" in build
    assert X.CATALOG["occt"].helper["program"] == "solidseas-occt.exe"
    # the pinned wheel is the one the oracle measured, with a hash for each wheel
    from occt_support import PINNED

    pins = (ROOT / "requirements" / "occt-helper.txt").read_text(encoding="utf-8")
    assert f"cadquery-ocp-novtk=={PINNED['cadquery-ocp']} \\" in pins and pins.count("--hash=sha256:") == 6
    # every DLL of that wheel for Windows has its licence named, and its text is carried
    wheel_dlls = (
        "deflate FreeImage freetype Iex IlmThread Imath jpeg8 lcms2 Lerc liblzma libpng16 libsharpyuv "
        "libwebp libwebpmux msvcp140 OpenEXR OpenEXRCore openjp2 openjph raw tiff zlib zstd vcomp140 "
        "TKBin TKBinL TKBinTObj TKBinXCAF TKBO TKBool TKBRep TKCAF TKCDF TKDE TKDEGLTF TKDEIGES TKDESTEP "
        "TKDESTL TKDEVRML TKernel TKExpress TKFeat TKFillet TKG2d TKG3d TKGeomAlgo TKGeomBase TKHLR TKLCAF "
        "TKMath TKMesh TKMeshVS TKOffset TKOpenGl TKPrim TKRWMesh TKService TKShHealing TKStd TKStdL TKTObj "
        "TKTopAlgo TKV3d TKVCAF TKXCAF TKXml TKXmlL TKXmlTObj TKXmlXCAF TKXSBase"
    ).split()
    rows = [
        line.split("\t")
        for line in (ROOT / "packaging" / "occt" / "libraries.tsv").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert all(len(r) == 3 and all(r) for r in rows)
    for dll in wheel_dlls:
        assert any(fnmatch.fnmatchcase(dll, r[0]) for r in rows), dll
    texts = (ROOT / "licenses" / "OCP-third-party.txt").read_text(encoding="utf-8")
    for _pattern, component, _licence in rows:
        assert component in texts or component == "Open CASCADE Technology", component
    exception = (ROOT / "licenses" / "OCCT_LGPL_EXCEPTION.txt").read_text(encoding="utf-8")
    assert exception.startswith("Open CASCADE exception (version 1.0) to GNU LGPL version 2.1.")
    assert "Apache License" in (ROOT / "licenses" / "OCP-LICENSE.txt").read_text(encoding="utf-8")
    notices = " ".join((ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8").split())
    assert "3.4 occt-<version>.zip (the OCCT backend)" in notices
    assert "makes use of facilities provided by the Open CASCADE Technology software" in notices


# --------------------------------------------------------------------------- with Open CASCADE
def _ocp_here() -> bool:
    try:
        import OCP  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def ocp_python() -> str | None:
    """An interpreter where OCP imports: the oracle's, or this one."""
    for python in (os.environ.get("SOLIDSEAS_OCCT_PYTHON", "").strip(), sys.executable):
        if python and os.path.isfile(python):
            done = subprocess.run([python, "-I", "-c", "import OCP"], capture_output=True, timeout=120)
            if done.returncode == 0:
                return python
    return None


# Shapes for the tests, made by Open CASCADE: a box as loose faces, the same box as an IGES
# manifold solid, one open face, and a file of curves alone; a cylinder in BREP, text and binary.
MAKE = r"""
import os, sys
from OCP.BinTools import BinTools
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Pln, gp_Pnt
from OCP.IGESControl import IGESControl_Controller, IGESControl_Writer
from OCP.Interface import Interface_Static
out = sys.argv[1]
os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
IGESControl_Controller.Init_s()
box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
def write_iges(shape, mode, name):
    Interface_Static.SetIVal_s("write.iges.brep.mode", mode)
    w = IGESControl_Writer("MM", mode)
    w.AddShape(shape)
    w.ComputeModel()
    assert w.Write(os.path.join(out, name))
write_iges(box, 0, "box_faces.igs")
write_iges(box, 1, "box_solid.igs")
write_iges(BRepBuilderAPI_MakeFace(gp_Pln(), 0.0, 5.0, 0.0, 5.0).Face(), 0, "sheet.igs")
write_iges(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(5, 0, 0)).Edge(), 0, "curve.igs")
cyl = BRepPrimAPI_MakeCylinder(5.0, 12.0).Shape()
assert BRepTools.Write_s(cyl, os.path.join(out, "cylinder.brep"))
BinTools.Write_s(cyl, os.path.join(out, "cylinder_binary.brep"))
"""
BOX_M3 = 10.0 * 20.0 * 30.0 * 1e-9
CYLINDER_M3 = 3.141592653589793 * 25.0 * 12.0 * 1e-9


def _fine_volume(doc) -> float:
    """The volume of the document's one object, drawn at a micrometre's chord."""
    return doc.scene(chord_m=1e-6).objects[0].measures()["volume_m3"]


def _make_shapes(python: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [python, "-I", "-c", MAKE, str(folder)], capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return folder


@pytest.mark.skipif(not _ocp_here(), reason="OCP does not import in this interpreter")
def test_the_helper_converts_in_this_process(tmp_path):
    shapes = _make_shapes(sys.executable, tmp_path / "shapes")

    runs = iter(range(100))

    def run(name, fmt="iges", to="step"):
        out = tmp_path / f"out-{next(runs)}"
        out.mkdir()
        return occt_helper.convert({"path": str(shapes / name), "from": fmt, "to": to, "out_dir": str(out)})

    faces = run("box_faces.igs")["report"]
    assert (faces["loose_faces_read"], faces["solids_sewn"], faces["solids"], faces["valid"]) == (
        6,
        1,
        1,
        True,
    )
    assert faces["unit"] == "mm" and faces["open_shells"] == faces["free_faces"] == 0
    solid = run("box_solid.igs")["report"]
    assert (solid["solids_read"], solid["solids_sewn"], solid["solids"]) == (1, 0, 1)
    sheet = run("sheet.igs")["report"]
    assert sheet["solids"] == 0 and sheet["open_shells"] + sheet["free_faces"] == 1
    with pytest.raises(occt_helper.Refused) as exc:
        run("curve.igs")
    assert exc.value.code == "no_geometry"
    for name in ("cylinder.brep", "cylinder_binary.brep"):
        got = run(name, "occt_brep")
        with open_model(got["path"]) as doc:
            assert _fine_volume(doc) == pytest.approx(CYLINDER_M3, rel=1e-3)
    # what SolidSeas' STEP reader makes of Open CASCADE's STEP of the sewn box
    with open_model(run("box_faces.igs", to="step")["path"]) as doc:
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(BOX_M3, rel=1e-9)
    # an IGES file the helper writes names no one, nor where it was made
    written = Path(run("box_solid.igs", to="iges")["path"]).read_bytes()
    header = b"".join(line[:72] for line in written.splitlines() if line[72:73] == b"G")
    login = os.environ.get("USER") or os.environ.get("USERNAME") or "nobody-here"
    assert login.encode() not in header and b"9Hmodel.igs" in header
    with pytest.raises(occt_helper.Refused, match="already in out_dir"):
        out = tmp_path / "again"
        out.mkdir()
        (out / "model.step").write_bytes(b"there first")
        occt_helper.convert(
            {"path": str(shapes / "box_solid.igs"), "from": "iges", "to": "step", "out_dir": str(out)}
        )


def test_iges_and_brep_open_through_the_helper_program(tmp_path, monkeypatch, fresh, capsys):
    python = ocp_python()
    if python is None:
        pytest.skip("no interpreter where OCP imports (SOLIDSEAS_OCCT_PYTHON, or this one)")
    shapes = _make_shapes(python, tmp_path / "shapes")
    monkeypatch.setenv(occt.ENV_PYTHON, python)
    assert registry.readable("iges") and registry.readable("occt_brep")
    with open_model(shapes / "box_faces.igs") as doc:
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(BOX_M3, rel=1e-9)
        assert doc.report["solids_sewn"] == 1 and doc.units["length"] == "mm"
        assert {n.name for n in doc.tree().nodes} == {"box_faces"}
    with open_model(shapes / "sheet.igs") as doc:
        doc.scene()
        assert "surfaces_not_closed" in {w.code for w in doc.warnings}
    with open_model(shapes / "cylinder_binary.brep") as doc:
        assert doc.variant == "binary"
        assert _fine_volume(doc) == pytest.approx(CYLINDER_M3, rel=1e-3)
    with pytest.raises(SldFormatError, match="curves or points only"):
        with open_model(shapes / "curve.igs") as doc:
            doc.scene()
    # the viewer's worker processes start the helper themselves (one each, in their Job Object)
    from solidseas_app.viewer import modeljobs
    from solidseas_app.viewer.modelpool import ModelPool

    pool = ModelPool(workers=1)
    try:
        params = {"path": str(shapes / "box_solid.igs"), "within": str(shapes), "folder": str(shapes)}
        details = pool.call(modeljobs.DETAILS_JOB, params).data["summary"]
        assert details["format"] == "iges" and details["counts"]["faces"] == 6
        viewed = pool.call(modeljobs.VIEW_JOB, params)
        assert viewed.data["geometry"]["size_mm"] == pytest.approx([10.0, 20.0, 30.0])
        assert viewed.data["preview"]["source"] == "rendered" and viewed.payload.startswith(b"\x89PNG")
    finally:
        pool.close()
    # a damaged file fails alone, whatever Open CASCADE does with it
    damaged = tmp_path / "damaged.igs"
    good = (shapes / "box_faces.igs").read_bytes()
    damaged.write_bytes(good[: len(good) // 2])
    try:
        with open_model(damaged) as doc:
            doc.scene()
    except (SldFormatError, FormatNotSupportedError):
        pass
    # IGES written by the command line reads back as the same solid
    out = tmp_path / "out"
    out.mkdir()
    assert cli.main(["convert", str(STEP_FIXTURE), "--format", "iges", "-o", str(out)]) == 0
    assert "IGES through Open CASCADE: 1 solid(s), 6 face(s)" in capsys.readouterr().out
    with open_model(out / "o02_boxA.igs") as doc:
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(_step_volume(), rel=1e-9)
    again = tmp_path / "again"
    again.mkdir()
    assert cli.main(["convert", str(out / "o02_boxA.igs"), "--format", "brep", "-o", str(again)]) == 0
    with open_model(again / "o02_boxA.brep") as doc:
        assert doc.scene().objects[0].measures()["volume_m3"] == pytest.approx(_step_volume(), rel=1e-9)


def test_open_cascade_checks_the_step_files_solidseas_writes(tmp_path, monkeypatch, fresh, capsys):
    python = ocp_python()
    if python is None:
        pytest.skip("no interpreter where OCP imports (SOLIDSEAS_OCCT_PYTHON, or this one)")
    monkeypatch.setenv(occt.ENV_PYTHON, python)
    truth = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    for name, solids, faces in (("o11_curved.SLDPRT", 1, 14), ("o12_multibody.SLDPRT", 2, 12)):
        out = tmp_path / name
        out.mkdir()
        argv = ["export", str(fixture_path(name)), "--format", "step", "--check", "-o", str(out), "--json"]
        code = cli.main(argv)
        check = json.loads(capsys.readouterr().out)["data"]["check"]
        assert code == 0 and check["sound"] is True and check["findings"] == [], (name, check)
        assert (check["solids"], check["faces"], check["occt"]) == (solids, faces, "7.9.3")
        # the measures are SOLIDWORKS' own, as the oracle measures them
        sw = truth[name]["api"]["configurations"]["Default"]
        assert check["volume_mm3"] * 1e-9 == pytest.approx(sw["volume_m3"], rel=1e-9)
        assert check["area_mm2"] * 1e-6 == pytest.approx(sw["surface_area_m2"], rel=1e-9)
    # a box whose shell lost a face: Open CASCADE still reads it, but not as written
    out = tmp_path / "box"
    out.mkdir()
    assert cli.main(["export", str(fixture_path("o02_boxA.SLDPRT")), "--format", "step", "-o", str(out)]) == 0
    capsys.readouterr()
    text = (out / "o02_boxA.step").read_text(encoding="ascii")
    shell = re.search(r"CLOSED_SHELL\('[^']*',\((#\d+(?:,#\d+)*)\)\)", text)
    damaged = text.replace(shell.group(1), shell.group(1).rsplit(",", 1)[0])
    check = fresh.check_bytes(damaged.encode("ascii"))
    # Open CASCADE makes a surface body of a solid whose shell is open, and the check says so
    assert occt.step_findings(check, solids=1, sheets=0, faces=6) == [
        "Open CASCADE read 0 solid(s) where 1 were written",
        "Open CASCADE read 1 sheet(s) where 0 were written",
        "Open CASCADE read 5 face(s) where 6 were written",
    ]


def test_the_rest_service_reads_iges_geometry_through_the_helper_program(tmp_path, monkeypatch, fresh):
    python = ocp_python()
    if python is None:
        pytest.skip("no interpreter where OCP imports (SOLIDSEAS_OCCT_PYTHON, or this one)")
    from serve_support import Running

    shapes = _make_shapes(python, tmp_path / "shapes")
    monkeypatch.setenv(occt.ENV_PYTHON, python)
    running = Running({"m": shapes}, workers=1, formats="iges,occt_brep")
    try:
        assert running.server.pool.helpers_per_worker == 1
        doc = running.get("document", root="m", path="box_faces.igs")
        assert doc.status == 200, doc.body[:300]
        data = doc.json()["data"]
        assert data["format"] == "iges" and data["counts"]["faces"] == 6 and data["counts"]["bodies"] == 1
        picture = running.get("preview", root="m", path="cylinder.brep")
        assert picture.status == 200 and picture.body.startswith(b"\x89PNG")
    finally:
        running.close()


def test_only_pools_that_read_iges_or_brep_let_their_workers_start_the_helper(standin, monkeypatch):
    from solidseas.errors import InvalidArgumentError
    from solidseas.workers import WorkerPool
    from solidseas_app.viewer import modelpool

    for wrong in (-1, 5, True, 1.0):
        with pytest.raises(InvalidArgumentError, match="helpers_per_worker"):
            WorkerPool(1, helpers_per_worker=wrong)
    found = {
        p.relative_to(SRC).as_posix(): m.group(1)
        for p in SRC.rglob("*.py")
        for m in re.finditer(r"^\s+helpers_per_worker=(?!0,)(\S+),$", p.read_text(encoding="utf-8"), re.M)
    }
    # the viewer's model pool and the REST service's, each through the one decision; the
    # catalog's pools and solidseas list read only a model file's head, never its geometry
    assert found == {
        "solidseas_app/viewer/modelpool.py": "_helpers()",
        "solidseas/serve/server.py": "helpers_per_worker(self.config.formats)",
    }
    # while the backend is there, a pool that reads IGES or BREP lets each worker start one
    # process, the helper; any other pool none
    assert occt.helpers_per_worker() == modelpool._helpers() == 1
    assert occt.helpers_per_worker(("iges",)) == occt.helpers_per_worker(("step", "occt_brep")) == 1
    assert occt.helpers_per_worker(("solidworks", "step", "stl")) == occt.helpers_per_worker(()) == 0
    # and without it, none at all
    monkeypatch.delenv(occt.ENV_PYTHON)
    occt.BACKEND._checked = None
    assert occt.helpers_per_worker() == occt.helpers_per_worker(("iges",)) == modelpool._helpers() == 0
