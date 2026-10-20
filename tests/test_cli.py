"""The command line interface, including its refusal to write next to source files.

The JSON documents themselves (one per command, strict, stderr empty) and the
exit-code table are covered in ``test_cli_json.py``.
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fakefs import ARCHIVE, DIRECTORY, REPARSE, FakeEntry, fake_tree
from solidseas import __version__
from solidseas.cli import EXIT_PARTIAL, EXIT_REFUSED, main
from solidseas.formats.solidworks import open_document
from solidseas.formats.solidworks import parasolid as ps
from support import ASSEMBLY, FIXTURES, fixture_path

O02 = str(fixture_path("o02_boxA.SLDPRT"))
O06 = str(fixture_path("o06_boxA_props_mat_cfg.SLDPRT"))
# Where a worker's memory cap holds: the Job Object on Windows, RLIMIT_AS on Linux.
MEMORY_CAPPED = sys.platform == "win32" or sys.platform.startswith("linux")


def run_json(capsys, *argv):
    """Run a command with --json; return the exit code and the envelope's data (or error)."""
    code = main([*argv, "--json"])
    env = json.loads(capsys.readouterr().out)
    return code, env["data"] if env["ok"] else env["error"]


@pytest.fixture
def source_copy(tmp_path) -> Path:
    """A writable copy of o02 in its own folder, so refusal tests never touch tests/fixtures."""
    src = tmp_path / "project"
    src.mkdir()
    dst = src / "o02_boxA.SLDPRT"
    shutil.copyfile(O02, dst)
    return dst


def test_info_json(capsys):
    code, info = run_json(capsys, "info", O06)
    assert code == 0
    assert info["format"] == "modern" and info["doc_type"] == "part"
    assert info["saved_version"]["format_version"] == 17000
    assert info["saved_version"]["release"] == "SOLIDWORKS 2024"
    assert [c["name"] for c in info["configurations"]] == ["Default", "OracleAlt"]
    assert info["active_configuration"] == "Default"
    assert info["counts"]["streams"] > 30


def test_info_text(capsys):
    assert main(["info", O06]) == 0
    out = capsys.readouterr().out
    assert "SOLIDWORKS 2024" in out and "OracleAlt" in out and "640 x 480" in out


def test_streams_json(capsys):
    code, out = run_json(capsys, "streams", O02)
    assert code == 0
    names = {s["name"]: s for s in out["streams"]}
    assert names["Contents/Config-0-Partition"]["size"] > 0
    assert names["PreviewPNG"]["codec"] == "deflate"


def test_props_json(capsys):
    code, out = run_json(capsys, "props", O06)  # effective properties of the active configuration
    assert code == 0 and (out["view"], out["configuration"]) == ("effective", "Default")
    assert {p["name"]: p["value"] for p in out["properties"]} == {
        "PartNo": "ORACLE-PN-123",
        "Description": "Oracle test box",
        "Qty": 42,
    }
    code, alt = run_json(capsys, "props", O06, "--configuration", "OracleAlt", "--view", "configuration")
    assert code == 0 and [(p["name"], p["value"]) for p in alt["properties"]] == [("CfgOnly", "ALT-VALUE")]
    code, err = run_json(capsys, "props", O06, "--configuration", "Nope")
    assert code == 1 and err["code"] == "configuration_not_found"


def test_props_default_output_is_json(capsys):
    assert main(["props", O06]) == 0
    assert json.loads(capsys.readouterr().out)["configuration"] == "Default"


def test_configurations_command(capsys):
    code, out = run_json(capsys, "configurations", O06)
    assert code == 0 and out["active_configuration"] == "Default"
    alt = next(c for c in out["configurations"] if c["name"] == "OracleAlt")
    assert alt["comment"] == "oracle alt config" and alt["material"]["name"] == "1060 Alloy"
    assert main(["configurations", O06]) == 0
    assert "OracleAlt" in capsys.readouterr().out


def test_dump_stream(tmp_path, capsys):
    out = tmp_path / "preview.png"
    code, res = run_json(capsys, "dump", O02, "PreviewPNG", "-o", str(out))
    assert code == 0 and res["bytes"] == out.stat().st_size and res["stream"] == "PreviewPNG"
    with open_document(O02) as doc:
        assert out.read_bytes() == doc.preview().data
    raw = tmp_path / "raw.bin"
    assert main(["dump", O02, "PreviewPNG", "-o", str(raw), "--raw"]) == 0
    assert raw.read_bytes() != out.read_bytes()


def test_dump_unknown_stream(tmp_path, capsys):
    code, err = run_json(capsys, "dump", O02, "No/Such/Stream", "-o", str(tmp_path / "x.bin"))
    assert code == 1 and err["code"] == "stream_not_found"
    assert err["detail"] == {"stream": "No/Such/Stream"}
    assert not (tmp_path / "x.bin").exists()


def test_preview_png_and_bmp(tmp_path, capsys):
    code, res = run_json(capsys, "preview", O02, "-o", str(tmp_path / "box.png"))
    assert code == 0 and (res["width"], res["height"], res["mime"]) == (640, 480, "image/png")
    assert (tmp_path / "box.png").read_bytes().startswith(b"\x89PNG")
    code, res = run_json(capsys, "preview", O02, "-o", str(tmp_path), "--prefer", "dib")
    assert code == 0 and res["output"].endswith("o02_boxA.bmp") and res["mime"] == "image/bmp"
    assert Path(res["output"]).read_bytes()[:2] == b"BM"


def test_preview_conversion_needs_pillow_or_works(tmp_path, capsys):
    target = tmp_path / "large.png"
    code = main(["preview", O02, "-o", str(target), "--prefer", "dib", "--json"])
    capsys.readouterr()
    try:
        import PIL  # noqa: F401
    except ImportError:
        assert code == 1 and not target.exists()
    else:
        assert code == 0 and target.read_bytes().startswith(b"\x89PNG")


def test_parasolid_command(tmp_path, capsys):
    out_dir = tmp_path / "xt"
    code, res = run_json(capsys, "parasolid", O02, "-o", str(out_dir), "--text", "--raw")
    assert code == 0 and res["bodies"] == 1
    kinds = sorted(w["kind"] for w in res["written"])
    assert kinds == ["d_b", "p_b", "x_b", "x_t"]
    xb = out_dir / "o02_boxA_Default_body1.x_b"
    ref = ps.read_file(fixture_path("o02_boxA.x_b").read_bytes())
    assert ps.compare_brep(ps.read_file(xb.read_bytes()), ref)["identical"]
    assert (out_dir / "o02_boxA_Default_body1.x_t").exists()


def test_parasolid_on_assembly_writes_one_transmit(tmp_path, capsys):
    # An assembly is one transmit of its placed parts (tests/test_parasolid_assembly.py).
    code, res = run_json(capsys, "parasolid", str(fixture_path(ASSEMBLY)), "-o", str(tmp_path / "x"))
    assert code == 0 and res["bodies"] == 2 and [w["kind"] for w in res["written"]] == ["x_b"]
    assert res["assembly"]["counts"]["instances"] == 2


# --------------------------------------------------------------------------- refusals
def test_refuses_to_write_next_to_the_source(source_copy, capsys):
    target = source_copy.parent / "preview.png"
    code, err = run_json(capsys, "preview", str(source_copy), "-o", str(target))
    assert code == EXIT_REFUSED == 3 and err["code"] == "output_refused"
    assert "next to the source" in err["reader_message"]
    assert not target.exists()
    assert main(["preview", str(source_copy), "-o", str(target), "--allow-source-dir"]) == 0
    assert target.exists()


def test_refuses_folders_below_the_source_folder(source_copy, capsys):
    target = source_copy.parent / "previews" / "p.png"
    code, err = run_json(capsys, "preview", str(source_copy), "-o", str(target))
    assert code == EXIT_REFUSED and "next to the source" in err["reader_message"]
    assert not target.parent.exists()


def test_output_path_errors_are_reported(tmp_path, capsys):
    folder = tmp_path / "a_folder"
    folder.mkdir()
    code, err = run_json(capsys, "dump", O02, "PreviewPNG", "-o", str(folder), "--force")
    assert code == 1 and err["code"] in ("not_found", "permission_denied")


def test_never_overwrites_the_source_or_writes_cad_files(source_copy, tmp_path, capsys):
    before = source_copy.read_bytes()
    code, _ = run_json(
        capsys,
        "dump",
        str(source_copy),
        "PreviewPNG",
        "-o",
        str(source_copy),
        "--allow-source-dir",
        "--force",
    )
    assert code == EXIT_REFUSED
    code, _ = run_json(capsys, "dump", str(source_copy), "PreviewPNG", "-o", str(tmp_path / "copy.sldprt"))
    assert code == EXIT_REFUSED and not (tmp_path / "copy.sldprt").exists()
    assert source_copy.read_bytes() == before


def test_refuses_to_overwrite_without_force(tmp_path, capsys):
    target = tmp_path / "p.png"
    target.write_bytes(b"keep")
    code, _ = run_json(capsys, "preview", O02, "-o", str(target))
    assert code == EXIT_REFUSED and target.read_bytes() == b"keep"
    code, _ = run_json(capsys, "preview", O02, "-o", str(target), "--force")
    assert code == 0 and target.read_bytes().startswith(b"\x89PNG")


def test_parasolid_refuses_the_source_folder(source_copy, capsys):
    code, _ = run_json(capsys, "parasolid", str(source_copy), "-o", str(source_copy.parent / "xt"))
    assert code == EXIT_REFUSED
    assert not (source_copy.parent / "xt").exists()


def test_missing_file(tmp_path, capsys):
    code, err = run_json(capsys, "info", str(tmp_path / "nope.SLDPRT"))
    assert code == 1 and err["code"] == "not_found"
    assert main(["info", str(tmp_path / "nope.SLDPRT")]) == 1
    assert "not found" in capsys.readouterr().err


def test_not_a_solidworks_file(tmp_path, capsys):
    bogus = tmp_path / "bogus.SLDPRT"
    bogus.write_bytes(b"this is not CAD data at all")
    code, err = run_json(capsys, "info", str(bogus))
    assert code == 1 and (err["code"], err["exception"]) == ("unknown_format", "UnknownFormatError")


# --------------------------------------------------------------------------- batch
def _batch_input(tmp_path: Path) -> Path:
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    shutil.copyfile(O02, src / "o02_boxA.SLDPRT")
    shutil.copyfile(O06, src / "sub" / "o06_boxA_props_mat_cfg.SLDPRT")
    shutil.copyfile(fixture_path(ASSEMBLY), src / "o08_asm_2x_boxA.SLDASM")
    (src / "~$o02_boxA.SLDPRT").write_bytes(b"\0" * 64)  # a SOLIDWORKS lock file
    (src / "notes.txt").write_text("ignored")
    return src


def test_batch(tmp_path, capsys):
    src = _batch_input(tmp_path)
    out = tmp_path / "out"
    code, summary = run_json(capsys, "batch", str(src), "-o", str(out), "--text")
    assert code == 0
    assert summary["files"] == 4
    assert summary["status_counts"] == {"ok": 3, "skipped": 1}
    assert summary["walk"]["folders"] == 2 and summary["walk"]["skipped"] == 1
    with open(out / "report.csv", newline="", encoding="utf-8") as fh:
        rows = {r["file"]: r for r in csv.DictReader(fh)}
    assert rows["o02_boxA.SLDPRT"]["doc_type"] == "part"
    assert rows["o02_boxA.SLDPRT"]["parasolid_bodies"] == "1"
    assert rows[os.path.join("sub", "o06_boxA_props_mat_cfg.SLDPRT")]["configurations"] == "2"
    assert rows["o08_asm_2x_boxA.SLDASM"]["doc_type"] == "assembly"
    assert rows["~$o02_boxA.SLDPRT"]["status"] == "skipped"
    assert (out / "o02_boxA.SLDPRT.png").exists()
    assert (out / "o02_boxA.SLDPRT_Default_body1.x_b").exists()
    assert (out / "o02_boxA.SLDPRT_Default_body1.x_t").exists()
    assert (out / "sub" / "o06_boxA_props_mat_cfg.SLDPRT_Default_body1.x_b").exists()
    lines = [json.loads(line) for line in (out / "report.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4
    part = next(r for r in lines if r["file"] == "o02_boxA.SLDPRT")
    assert part["summary"]["doc_type"] == "part" and part["parasolid"]["bodies"] == 1
    # a second run refuses to overwrite the report unless --force is given
    assert main(["batch", str(src), "-o", str(out)]) == EXIT_REFUSED
    capsys.readouterr()
    assert main(["batch", str(src), "-o", str(out), "--force"]) == 0


@pytest.mark.parametrize("reading", ["workers", "in_process"])
def test_batch_never_opens_what_the_walk_set_aside(tmp_path, capsys, monkeypatch, reading):
    """Placeholders and links get rows of their own and are never opened (opening a
    OneDrive placeholder starts a download), and an unreadable folder makes the run partial.
    Through worker processes, the real document is the only one handed to a worker."""
    import solidseas.cli as cli
    from solidseas import workers

    src = tmp_path / "in"
    src.mkdir()
    shutil.copyfile(O02, src / "real.SLDPRT")
    size = (src / "real.SLDPRT").stat().st_size
    tree = {
        "": [
            FakeEntry("real.SLDPRT", ARCHIVE, size=size),
            FakeEntry("online.SLDPRT", ARCHIVE | REPARSE | 0x400000, 0x9000601A, size=500_000),
            FakeEntry("linked.SLDASM", ARCHIVE | REPARSE, 0xA000000C),
            FakeEntry("denied", DIRECTORY),
        ],
        "denied": PermissionError(13, "Access is denied"),
    }
    fake_tree(monkeypatch, src, tree)
    opened: list[str] = []
    if reading == "in_process":
        real = cli.open_document

        def recording(path, *args, **kwargs):
            opened.append(os.path.basename(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(cli, "open_document", recording)
        how = ["--in-process"]
    else:
        real_call = workers.WorkerPool.call

        def handed(self, job, params=None, **kwargs):
            opened.append(os.path.basename(params["path"]))
            return real_call(self, job, params, **kwargs)

        monkeypatch.setattr(workers.WorkerPool, "call", handed)
        how = []
    out = tmp_path / "out"
    code, summary = run_json(capsys, "batch", str(src), "-o", str(out), "--no-parasolid", *how)
    assert opened == ["real.SLDPRT"]  # the wrapper saw the one real document, and only it
    assert code == EXIT_PARTIAL  # the folder that could not be read
    assert summary["status_counts"] == {"ok": 1, "placeholder": 1, "link": 1}
    assert (summary["walk"]["placeholders"], summary["walk"]["links"], summary["walk"]["errors"]) == (1, 1, 1)
    with open(out / "report.csv", newline="", encoding="utf-8") as fh:
        rows = {r["file"]: r for r in csv.DictReader(fh)}
    online, linked = rows["online.SLDPRT"], rows["linked.SLDASM"]
    assert online["status"] == "placeholder" and "recall_on_data_access" in online["error"]
    assert linked["status"] == "link" and "symlink" in linked["error"]
    assert rows["real.SLDPRT"]["status"] == "ok"
    text_mode = ["batch", str(src), "-o", str(out), "--no-parasolid", "--force", *how]
    assert main(text_mode) == EXIT_PARTIAL
    assert "folders that could not be read: 1" in capsys.readouterr().out


def test_batch_refuses_a_folder_that_became_a_link_after_the_walk(tmp_path, capsys, monkeypatch):
    """batch walks the whole tree before it reads anything. A folder swapped for a link
    to somewhere else in between must not lead the read out of the folder."""
    import solidseas.cli as cli

    src = tmp_path / "in"
    (src / "z").mkdir(parents=True)
    shutil.copyfile(O02, src / "z" / "c.SLDPRT")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(O06, outside / "c.SLDPRT")

    def swap():
        (src / "z").rename(src / "z_was")
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(outside), str(src / "z"))
        else:
            os.symlink(outside, src / "z", target_is_directory=True)

    class SwapAfterWalking(cli.Walk):
        def __iter__(self):
            yield from super().__iter__()
            swap()

    monkeypatch.setattr(cli, "Walk", SwapAfterWalking)
    out = tmp_path / "out"
    try:
        code, summary = run_json(capsys, "batch", str(src), "-o", str(out), "--no-parasolid", "--no-preview")
        assert (src / "z" / "c.SLDPRT").stat().st_size == os.stat(O06).st_size  # control: it leads out
    finally:
        if os.name == "nt" and (src / "z").exists():
            os.rmdir(src / "z")  # removes the junction, not its target
        elif os.path.islink(src / "z"):
            os.unlink(src / "z")
    assert code == EXIT_PARTIAL and summary["status_counts"] == {"error": 1}
    with open(out / "report.csv", newline="", encoding="utf-8") as fh:
        (row,) = list(csv.DictReader(fh))
    assert row["status"] == "error" and row["error"].startswith("LinkRefusedError") and row["doc_type"] == ""


def test_batch_with_worker_processes(tmp_path, capsys):
    src = _batch_input(tmp_path)
    code, summary = run_json(
        capsys, "batch", str(src), "-o", str(tmp_path / "out"), "--jobs", "2", "--no-preview"
    )
    assert code == 0 and summary["status_counts"] == {"ok": 3, "skipped": 1}
    # two parts' bodies and the assembly's one transmit (tests/test_parasolid_assembly.py)
    assert summary["previews"] == 0 and summary["parasolid_files"] == 3


def test_batch_refuses_output_inside_input(tmp_path, capsys):
    src = _batch_input(tmp_path)
    code, err = run_json(capsys, "batch", str(src), "-o", str(src / "out"))
    assert code == EXIT_REFUSED and "inside the source folder" in err["reader_message"]
    assert not (src / "out").exists()


def test_batch_report_cells_never_start_a_formula(tmp_path, capsys, monkeypatch):
    import solidseas.cli as cli

    src = tmp_path / "in"
    src.mkdir()
    shutil.copyfile(O02, src / "=cmd.SLDPRT")

    def hostile(path, *args, **kwargs):
        raise ValueError("=HYPERLINK(1)")

    monkeypatch.setattr(cli, "open_document", hostile)
    code = main(["batch", str(src), "-o", str(tmp_path / "out"), "--json", "--in-process"])
    capsys.readouterr()
    assert code == EXIT_PARTIAL
    with open(tmp_path / "out" / "report.csv", newline="", encoding="utf-8") as fh:
        (row,) = list(csv.DictReader(fh))
    assert row["file"] == "'=cmd.SLDPRT" and row["error"] == "ValueError: =HYPERLINK(1)"
    assert not any(v.startswith(("=", "+", "-", "@")) for v in row.values())


# --------------------------------------------------------------------------- worker processes
def _no_constants(name):
    raise ValueError(f"{name} is not strict JSON")


def _report(out: Path) -> tuple[dict[str, dict], list[dict]]:
    with open(out / "report.csv", newline="", encoding="utf-8") as fh:
        rows = {r["file"]: r for r in csv.DictReader(fh)}
    text = (out / "report.jsonl").read_text(encoding="utf-8")
    return rows, [json.loads(line, parse_constant=_no_constants) for line in text.splitlines()]


def _timeless(report: tuple[dict[str, dict], list[dict]]) -> tuple[dict[str, dict], list[dict]]:
    """The report without the time an assembly's Parasolid took, which no two runs share."""
    rows, lines = report
    for line in lines:
        asm = (line.get("parasolid") or {}).get("assembly")
        if asm:
            asm.pop("seconds")
    return rows, lines


def _files_below(folder: Path) -> list[Path]:
    return sorted(p.relative_to(folder) for p in folder.rglob("*") if p.is_file())


@pytest.mark.parametrize("given", ["relative", "forward_slashes"])
def test_list_and_batch_read_documents_in_worker_processes(tmp_path, capsys, monkeypatch, given):
    """By default no document is opened in this process; with --in-process they are, and
    the listing, the report and the files written are the same either way, down to the
    error text of a file that fails, which names it as the folder was given."""
    from solidseas import listing as listing_mod
    from solidseas.formats.solidworks import container

    opened: list[str] = []
    real = container.open_readonly

    def record(path, **kwargs):
        opened.append(os.path.basename(os.fspath(path)))
        return real(path, **kwargs)

    monkeypatch.setattr(container, "open_readonly", record)
    monkeypatch.setattr(listing_mod, "open_readonly", record)
    src = _batch_input(tmp_path)
    (src / "sub" / "empty.SLDPRT").write_bytes(b"")  # not a SOLIDWORKS document: an error row
    monkeypatch.chdir(tmp_path)
    folder = "in" if given == "relative" else str(src).replace(os.sep, "/")
    argv = ["list", folder, "--recursive", "--include", "properties,configurations"]
    code, pooled = run_json(capsys, *argv)
    assert code == EXIT_PARTIAL and (pooled["counts"]["ok"], pooled["counts"]["error"]) == (3, 1)
    assert opened == []
    code, local = run_json(capsys, *argv, "--in-process")
    assert code == EXIT_PARTIAL and local == pooled and len(opened) >= 3  # control: these opens are seen
    opened.clear()
    code, summary = run_json(capsys, "batch", folder, "-o", str(tmp_path / "w"), "--text", "--jobs", "2")
    assert code == EXIT_PARTIAL and opened == []
    assert summary["status_counts"] == {"error": 1, "ok": 3, "skipped": 1}
    code, again = run_json(capsys, "batch", folder, "-o", str(tmp_path / "p"), "--text", "--in-process")
    assert code == EXIT_PARTIAL and opened  # control
    assert {k: v for k, v in summary.items() if not k.startswith("report_")} == {
        k: v for k, v in again.items() if not k.startswith("report_")
    }
    assert _timeless(_report(tmp_path / "w")) == _timeless(_report(tmp_path / "p"))
    rows, _ = _report(tmp_path / "w")
    error = rows[os.path.join("sub", "empty.SLDPRT")]["error"]
    as_given = os.path.join(folder, "sub", "empty.SLDPRT")
    assert error.startswith(f"UnknownFormatError: {as_given}: "), error
    written = _files_below(tmp_path / "w")
    assert written == _files_below(tmp_path / "p")
    # the reports, three previews, and the x_b and x_t of two parts and the assembly
    assert len(written) == 2 + 3 + 3 * 2


HOSTILE_JOBS = {"listing_entry": "worker_jobs:listing_entry", "batch_document": "worker_jobs:batch_document"}
HOSTILE_NAMES = ("bomb.SLDPRT", "crash.SLDPRT", "fine.SLDPRT", "slow.SLDPRT")


@pytest.fixture
def hostile(tmp_path, monkeypatch) -> Path:
    """Copies of o02 whose worker job hangs (slow), crashes (crash) or allocates 2 GiB
    (bomb), as tests/worker_jobs.py makes it, and one it reads as usual (fine)."""
    import solidseas.cli as cli

    monkeypatch.setattr(cli, "WORKER_JOBS", {**cli.WORKER_JOBS, **HOSTILE_JOBS})
    src = tmp_path / "in"
    src.mkdir()
    for name in HOSTILE_NAMES:
        shutil.copyfile(O02, src / name)
    return src


def test_a_listing_finishes_past_a_file_that_hangs_crashes_or_exhausts_memory(hostile, capsys):
    start = time.monotonic()
    code, data = run_json(capsys, "list", str(hostile), "--file-timeout", "3", "--memory-mb", "512")
    assert time.monotonic() - start < 60  # one 3 s deadline, not the stuck job's two minutes
    entries = {e["path"]: e for e in data["entries"]}
    assert code == EXIT_PARTIAL and set(entries) == set(HOSTILE_NAMES)
    assert entries["slow.SLDPRT"]["error"]["code"] == "timeout"
    assert entries["crash.SLDPRT"]["error"]["code"] == "worker_crashed"
    if MEMORY_CAPPED:
        assert entries["bomb.SLDPRT"]["error"]["code"] == "limit_exceeded"
        assert entries["bomb.SLDPRT"]["error"]["detail"] == {"limit": "memory"}
        assert (data["counts"]["ok"], data["counts"]["error"]) == (1, 3)
    fine = entries["fine.SLDPRT"]
    assert fine["status"] == "ok" and fine["doc_type"] == "part" and fine["preview"]["available"]
    assert main(["list", str(hostile), "--file-timeout", "3", "--memory-mb", "512"]) == EXIT_PARTIAL
    out = capsys.readouterr().out  # text mode names each failure by its code
    assert "slow.SLDPRT  timeout" in out and "crash.SLDPRT  worker_crashed" in out


def test_a_batch_finishes_past_a_file_that_hangs_crashes_or_exhausts_memory(hostile, tmp_path, capsys):
    out = tmp_path / "out"
    start = time.monotonic()
    limits = ["--file-timeout", "3", "--memory-mb", "512", "--jobs", "2"]
    code, summary = run_json(capsys, "batch", str(hostile), "-o", str(out), *limits)
    assert time.monotonic() - start < 60
    assert code == EXIT_PARTIAL and summary["files"] == 4
    rows, lines = _report(out)
    assert set(rows) == set(HOSTILE_NAMES) and len(lines) == 4
    slow, crash = rows["slow.SLDPRT"], rows["crash.SLDPRT"]
    assert slow["status"] == "error" and slow["error"].startswith("WorkerTimeoutError: ")
    assert crash["status"] == "error" and crash["error"].startswith("WorkerCrashedError: ")
    if MEMORY_CAPPED:
        assert rows["bomb.SLDPRT"]["error"] == "SldLimitError: the worker reached its memory limit"
        assert summary["status_counts"] == {"error": 3, "ok": 1}
    for name in ("slow.SLDPRT", "crash.SLDPRT"):
        assert rows[name]["doc_type"] == "" and not list(out.glob(name + "*"))  # nothing half written
    assert rows["fine.SLDPRT"]["status"] == "ok" and rows["fine.SLDPRT"]["parasolid_bodies"] == "1"
    assert (out / "fine.SLDPRT.png").exists() and (out / "fine.SLDPRT_Default_body1.x_b").exists()
    fine = next(line for line in lines if line["file"] == "fine.SLDPRT")
    assert fine["summary"]["doc_type"] == "part" and fine["parasolid"]["bodies"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="a cap this low suits the Job Object's commit limit")
def test_a_batch_survives_a_crafted_file_that_inflates_past_the_memory_cap(tmp_path, capsys):
    """A 3 KB part whose one local body inflates to 60 MiB, under the 64 MiB transmit cap:
    reading it needs more than a 96 MiB worker may use, so it is that document's error, and
    the next document is read as usual. With room to spare the same file reads (control)."""
    from builders import build_modern, fixture_streams
    from test_hardening import _local_bodies

    src = tmp_path / "in"
    src.mkdir()
    partition = fixture_streams(fixture_path("o01_empty.SLDPRT"))["Contents/Config-0-Partition"]
    inflating = {
        "Contents/Config-0-Partition": partition,
        "Config-0-FeatureBodies/LocalBodies": _local_bodies("Imported1", [bytes(60 << 20)]),
    }
    (src / "a_inflates.SLDPRT").write_bytes(build_modern(inflating))
    shutil.copyfile(O02, src / "b_fine.SLDPRT")
    assert (src / "a_inflates.SLDPRT").stat().st_size < 4096
    code, summary = run_json(capsys, "batch", str(src), "-o", str(tmp_path / "capped"), "--memory-mb", "96")
    rows, _ = _report(tmp_path / "capped")
    assert code == EXIT_PARTIAL and summary["status_counts"] == {"error": 1, "ok": 1}
    assert rows["a_inflates.SLDPRT"]["error"] == "SldLimitError: reading the document ran out of memory"
    assert rows["b_fine.SLDPRT"]["status"] == "ok" and rows["b_fine.SLDPRT"]["parasolid_bodies"] == "1"
    code, summary = run_json(capsys, "batch", str(src), "-o", str(tmp_path / "roomy"), "--memory-mb", "1024")
    assert code == 0 and summary["status_counts"] == {"ok": 2}


def test_list_and_batch_answer_every_crafted_file(tmp_path, capsys):
    """The crafted files of the service's hostile-file test (a flood of directory records,
    lying sector chains, runaway strings, a DOCTYPE, a spent decompression budget, NaN, a
    reference cycle, a doubling tree, noise) each get an entry and a report row, in
    strict JSON, and none needs its worker stopped."""
    from test_serve_security import _hostile

    src = tmp_path / "crafted"
    src.mkdir()
    files = _hostile(tmp_path)
    for name, data in files.items():
        (src / name).write_bytes(data)
    code = main(["list", str(src), "--include", "properties,configurations", "--json"])
    listing = json.loads(capsys.readouterr().out, parse_constant=_no_constants)["data"]
    entries = listing["entries"]
    assert code in (0, EXIT_PARTIAL) and {e["path"] for e in entries} == set(files)
    assert not [e for e in entries if e["error"] and e["error"]["code"] in ("timeout", "worker_crashed")]
    out = tmp_path / "out"
    code = main(["batch", str(src), "-o", str(out), "--text", "--jobs", "2", "--json"])
    summary = json.loads(capsys.readouterr().out, parse_constant=_no_constants)["data"]
    rows, lines = _report(out)
    assert code in (0, EXIT_PARTIAL) and summary["files"] == len(files) == len(rows) == len(lines)
    assert not [r for r in rows.values() if r["error"].startswith(("WorkerTimeout", "WorkerCrashed"))]


@pytest.mark.parametrize("job", ["not_a_row", "list_cell", "dict_cell", "bool_cell"])
def test_a_worker_answer_that_is_not_a_batch_row_is_that_documents_error(tmp_path, capsys, monkeypatch, job):
    """A row that is not an object, or one whose cells are not text or a number, is the
    document's error: nothing of it reaches the report."""
    import solidseas.cli as cli

    monkeypatch.setattr(cli, "WORKER_JOBS", {"batch_document": f"worker_jobs:{job}"})
    src = tmp_path / "in"
    src.mkdir()
    shutil.copyfile(O02, src / "a.SLDPRT")
    code, summary = run_json(capsys, "batch", str(src), "-o", str(tmp_path / "out"))
    assert code == EXIT_PARTIAL and summary["status_counts"] == {"error": 1}
    rows, lines = _report(tmp_path / "out")
    expected = "WorkerCrashedError: the worker's answer was not what the batch job returns"
    assert rows["a.SLDPRT"]["error"] == expected and rows["a.SLDPRT"]["release"] == ""
    assert lines[0]["summary"] is None


def test_the_cli_pool_reads_only_below_the_listed_folder(tmp_path, capsys, monkeypatch):
    """The pool list and batch start lets a job read only below the folder they were given:
    a job that asks for the folder above is refused there, and the run goes on."""
    import solidseas.cli as cli

    jobs = {
        "batch_document": "worker_jobs:batch_document_above",
        "listing_entry": "worker_jobs:listing_entry_above",
    }
    src = tmp_path / "in"
    src.mkdir()
    shutil.copyfile(O02, src / "a.SLDPRT")
    code, listing = run_json(capsys, "list", str(src))
    assert code == 0 and listing["entries"][0]["status"] == "ok"  # control: the real jobs read it
    code, summary = run_json(capsys, "batch", str(src), "-o", str(tmp_path / "control"))
    assert code == 0 and summary["status_counts"] == {"ok": 1}
    monkeypatch.setattr(cli, "WORKER_JOBS", jobs)
    code, listing = run_json(capsys, "list", str(src))
    (entry,) = listing["entries"]
    assert code == EXIT_PARTIAL and entry["status"] == "error"
    assert (entry["error"]["code"], entry["error"]["detail"]) == ("path_refused", {"rule": "outside_roots"})
    code, summary = run_json(capsys, "batch", str(src), "-o", str(tmp_path / "out"))
    rows, _ = _report(tmp_path / "out")
    assert code == EXIT_PARTIAL and summary["status_counts"] == {"error": 1}
    assert rows["a.SLDPRT"]["error"].startswith("PathRefusedError: ")
    assert _files_below(tmp_path / "out") == [Path("report.csv"), Path("report.jsonl")]


@pytest.mark.parametrize(
    "extra",
    [
        ["--in-process", "--file-timeout", "5"],
        ["--in-process", "--memory-mb", "100"],
        ["--file-timeout", "0"],
        ["--memory-mb", "0"],
    ],
)
@pytest.mark.parametrize("command", ["list", "batch"])
def test_worker_options_are_checked(tmp_path, capsys, command, extra):
    out = ["-o", str(tmp_path.parent / "out")] if command == "batch" else []
    code, err = run_json(capsys, command, str(tmp_path), *out, *extra)
    assert code == 2 and err["code"] == "invalid_argument"


@pytest.mark.parametrize("extra", [["--in-process", "--jobs", "2"], ["--jobs", "65"]])
def test_batch_jobs_need_worker_processes_and_a_limit(tmp_path, capsys, extra):
    code, err = run_json(capsys, "batch", str(tmp_path), "-o", str(tmp_path.parent / "out"), *extra)
    assert code == 2 and err["code"] == "invalid_argument"
    assert err["detail"]["parameter"] == ("in_process" if "--in-process" in extra else "jobs")
    assert not (tmp_path.parent / "out").exists()


def _src_env() -> dict[str, str]:
    env = dict(os.environ)
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _check_list_run(proc: subprocess.CompletedProcess) -> None:
    """A list of the fixtures, read in worker processes started by that command."""
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stderr == ""
    data = json.loads(proc.stdout)["data"]
    assert data["counts"]["ok"] == data["counts"]["entries"] >= 19


def test_python_dash_m_entry_point(tmp_path):
    env = _src_env()
    proc = subprocess.run(
        [sys.executable, "-m", "solidseas", "info", O02, "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert json.loads(proc.stdout)["data"]["doc_type"] == "part"
    # list starts worker processes with spawn, which runs the main module again in each:
    # solidseas.__main__ is never run again, so the workers start
    listed = subprocess.run(
        [sys.executable, "-m", "solidseas", "list", str(FIXTURES), "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )
    _check_list_run(listed)
    version = subprocess.run(
        [sys.executable, "-m", "solidseas", "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert version.stdout.strip() == f"solidseas {__version__}"


# The script pip installs as the solidseas command (distlib's template). On Windows it is
# the __main__.py of a zip appended to solidseas.exe; elsewhere a plain script file.
PIP_LAUNCHER = r"""# -*- coding: utf-8 -*-
import re
import sys
from solidseas.cli import main
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
    sys.exit(main())
"""


@pytest.mark.parametrize("form", ["zip_main", "script"])
def test_the_installed_command_starts_its_workers(tmp_path, form):
    """The installed solidseas command starts its worker processes in both forms pip writes:
    spawn never runs a zip's __main__.py again, and it runs the plain script again as
    __mp_main__, where the launcher's main guard stops it."""
    import zipfile

    if form == "zip_main":
        launcher = tmp_path / "solidseas.exe"  # what the Windows launcher hands to Python
        with zipfile.ZipFile(launcher, "w") as zf:
            zf.writestr("__main__.py", PIP_LAUNCHER)
    else:
        launcher = tmp_path / "solidseas"
        launcher.write_text("#!/usr/bin/env python\n" + PIP_LAUNCHER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(launcher), "list", str(FIXTURES), "--json"],
        capture_output=True,
        text=True,
        env=_src_env(),
        timeout=180,
        check=False,
    )
    _check_list_run(proc)
