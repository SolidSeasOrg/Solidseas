"""The PDM vault (``docs/PDM.md`` 3, 4 and 7): a library's settings, status, check-ins,
scans, logs and restores, on temporary folders and synthetic files, and ``solidseas pdm``
printing one strict JSON document per action."""

import json
import os
import shutil
import sys
import time

import pytest

from jsonschema_subset import validate
from solidseas import cli, model, pdm, versions
from solidseas.errors import InvalidArgumentError, LinkRefusedError, OutputRefusedError, PathRefusedError
from solidseas.pdm.checkins import parse_checkin
from support import FIXTURES

XB_A = FIXTURES / "o02_boxA.x_b"  # SOLIDWORKS' own Parasolid exports, public fixtures
XB_B = FIXTURES / "o07_boxB_h31.x_b"


def write(path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def bump(path, seconds: float = 2.0) -> None:
    """Move a file's modification time on, as a later save would."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "CAD"
    write(root / "Jobs" / "1042" / "bracket.sldprt", "bracket one")
    write(root / "Jobs" / "1042" / "plate.step", "plate one")
    write(root / "Jobs" / "1043" / "bracket.sldprt", "bracket one")  # the same content in another project
    write(root / "Jobs" / "1043" / "notes.txt", "not CAD")
    (root / "Library").mkdir()
    return root


def files_of(folder) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


# --------------------------------------------------------------------------- init and settings
def test_init_writes_only_its_own_folder(lib):
    before = files_of(lib)
    vault = pdm.init(lib)
    assert vault.created and vault.root == str(lib)
    after = files_of(lib)
    assert after - before == {".solidseas/vault/vault.json"}
    assert (lib / ".solidseas" / "vault" / "store").is_dir()
    assert (lib / ".solidseas" / "vault" / "checkins").is_dir()
    settings = json.loads((lib / ".solidseas" / "vault" / "vault.json").read_text())
    assert settings == {
        "format": 1,
        "sections": [],
        "library": "Library",
        "archive": [],
        "tracked": [],
        "ignore": [],
        "who": "",
    }
    again = pdm.init(lib)
    assert not again.created and files_of(lib) == after


def test_open_walks_up_and_refuses_outside(lib, tmp_path):
    pdm.init(lib)
    assert pdm.open(lib / "Jobs" / "1042" / "bracket.sldprt").root == str(lib)
    assert pdm.open(lib / "Jobs").root == str(lib)
    with pytest.raises(InvalidArgumentError) as err:
        pdm.open(tmp_path)
    assert err.value.detail["rule"] == "not_a_library"
    with pytest.raises(InvalidArgumentError) as err:
        pdm.init(lib / "Jobs")
    assert err.value.detail["rule"] == "inside_library"


def test_sections_and_projects(lib):
    vault = pdm.init(lib)
    assert [p.path for p in vault.projects()] == ["Jobs/1042", "Jobs/1043"]
    assert {s.folder: s.kind for s in vault.sections()} == {"Jobs": "projects", "Library": "library"}
    assert vault.project_of(lib / "Jobs" / "1042" / "sub" / "x.sldprt").path == "Jobs/1042"
    assert vault.project_of(lib / "Library" / "bolt.sldprt") is None
    settings = {
        "format": 1,
        "sections": [{"folder": "Customers", "depth": 2}, {"folder": "Old", "depth": 1}],
        "library": "Library",
        "archive": ["Old"],
        "tracked": [".ext"],
        "ignore": ["*backup*"],
        "who": "D",
    }
    (lib / ".solidseas" / "vault" / "vault.json").write_text(json.dumps(settings))
    (lib / "Customers" / "Acme" / "Job 12").mkdir(parents=True)
    (lib / "Old" / "2019").mkdir(parents=True)
    vault = pdm.open(lib)
    assert [(p.path, p.archived) for p in vault.projects()] == [
        ("Customers/Acme/Job 12", False),
        ("Old/2019", True),
    ]
    assert vault.project_of(lib / "Customers" / "Acme" / "x.sldprt") is None
    assert vault.project_of(lib / "Jobs" / "1042" / "x.sldprt") is None  # not a section any more


@pytest.mark.parametrize(
    "settings",
    [
        "not json",
        '{"format": 2}',
        '{"format": 1, "sections": [{"folder": "../up", "depth": 1}]}',
        '{"format": 1, "sections": [{"folder": "Jobs", "depth": 9}]}',
        '{"format": 1, "library": ".hidden"}',
        '{"format": 1, "tracked": ["ext"]}',
        '{"format": 1, "ignore": [3]}',
        '{"format": 1, "who": 5}',
    ],
)
def test_malformed_settings_are_refused(lib, settings):
    pdm.init(lib)
    (lib / ".solidseas" / "vault" / "vault.json").write_text(settings)
    with pytest.raises(InvalidArgumentError) as err:
        pdm.open(lib)
    assert err.value.detail["rule"] == "vault_settings"


def test_tracked(lib):
    (lib / ".solidseas").mkdir()
    (lib / ".solidseas" / "vault").mkdir()
    (lib / ".solidseas" / "vault" / "vault.json").write_text(
        json.dumps({"format": 1, "tracked": [".ext"], "ignore": ["*.bak.step", "Jobs/old/*"]})
    )
    vault = pdm.open(lib)
    yes = [
        "Jobs/1042/bracket.sldprt",
        "Jobs/1042/a.SLDASM",
        "x/a.step",
        "x/drawing.pdf",
        "x/flat.dxf",
        "x/a.ext",
    ]
    no = ["Jobs/1043/notes.txt", ".git/a.sldprt", "x/.hidden/a.sldprt", "x/~$a.sldprt", "x/a.bak.step"]
    no += ["Jobs/old/a.sldprt", ".solidseas/vault/store/objects/ab/a.sldprt"]
    assert all(vault.tracked(lib / p) for p in yes)
    assert not any(vault.tracked(lib / p) for p in no)
    assert not vault.tracked(lib.parent / "elsewhere.sldprt")


# --------------------------------------------------------------------------- status
def test_status_new_changed_gone(lib):
    vault = pdm.init(lib)
    st = vault.status()
    assert st.counts == {"new": 3, "changed": 0, "gone": 0, "unchanged": 0}
    assert [f.path for f in st.files] == [
        "Jobs/1042/bracket.sldprt",
        "Jobs/1042/plate.step",
        "Jobs/1043/bracket.sldprt",
    ]
    vault.checkin([lib], "first")
    assert vault.status().counts == {"new": 0, "changed": 0, "gone": 0, "unchanged": 3}
    write(lib / "Jobs" / "1042" / "bracket.sldprt", "bracket two")
    bump(lib / "Jobs" / "1042" / "bracket.sldprt")
    (lib / "Jobs" / "1042" / "plate.step").unlink()
    write(lib / "Jobs" / "1043" / "frame.sldasm", "frame")
    st = vault.status()
    assert {f.path: f.state for f in st.files} == {
        "Jobs/1042/bracket.sldprt": "changed",
        "Jobs/1042/plate.step": "gone",
        "Jobs/1043/frame.sldasm": "new",
    }
    assert st.counts["unchanged"] == 1
    scoped = vault.status(lib / "Jobs" / "1043")
    assert scoped.scope == "Jobs/1043" and [f.path for f in scoped.files] == ["Jobs/1043/frame.sldasm"]
    one = vault.status(lib / "Jobs" / "1042" / "bracket.sldprt")
    assert [(f.path, f.state) for f in one.files] == [("Jobs/1042/bracket.sldprt", "changed")]
    with pytest.raises(InvalidArgumentError):
        vault.status(lib / "Jobs" / "1043" / "notes.txt")


def test_status_reads_only_files_whose_size_or_time_changed(lib, monkeypatch):
    vault = pdm.init(lib)
    for k in range(300):
        write(lib / "Jobs" / "big" / f"part{k:03d}.sldprt", f"part {k}")
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", lambda fd: None)
        vault.checkin([lib], "all of them")
    calls = []
    real = pdm.Vault._hash
    monkeypatch.setattr(pdm.Vault, "_hash", lambda self, full: calls.append(full) or real(self, full))
    st = vault.status()
    assert st.counts["unchanged"] == 303 and st.hashed == 0 and calls == []
    bump(lib / "Jobs" / "big" / "part007.sldprt")  # saved again, the same content
    write(lib / "Jobs" / "big" / "part008.sldprt", "part 8, longer")
    st = vault.status()
    assert len(calls) == 2 and st.hashed == 2
    assert [(f.path, f.state) for f in st.files] == [("Jobs/big/part008.sldprt", "changed")]


def test_status_on_many_files_is_quick(lib, monkeypatch):
    vault = pdm.init(lib)
    for k in range(3000):
        write(lib / "Jobs" / f"p{k % 30:02d}" / f"part{k:04d}.sldprt", f"{k}")
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", lambda fd: None)  # the first scan's time is the disk's, not the test's
        vault.scan()
    t0 = time.perf_counter()
    st = vault.status()
    assert st.counts["unchanged"] == 3003 and st.hashed == 0
    assert time.perf_counter() - t0 < 20  # about 0.3 s on the development VM


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_links_are_never_followed(lib, tmp_path):
    vault = pdm.init(lib)
    outside = tmp_path / "outside"
    write(outside / "secret.sldprt", "outside")
    os.symlink(outside, lib / "Jobs" / "linked")
    os.symlink(outside / "secret.sldprt", lib / "Jobs" / "1042" / "link.sldprt")
    st = vault.status()
    assert {s["path"]: s["reason"] for s in st.skipped} == {
        "Jobs/1042/link.sldprt": "link",
        "Jobs/linked": "link",
    }
    assert all("secret" not in f.path and "link" not in f.path for f in st.files)
    with pytest.raises(PathRefusedError):
        vault.checkin([lib / "Jobs" / "linked" / "secret.sldprt"], "no")
    with pytest.raises(LinkRefusedError):
        vault.checkin([lib / "Jobs" / "1042" / "link.sldprt"], "no")


# --------------------------------------------------------------------------- check-ins and scans
def objects(lib) -> list[str]:
    return sorted(
        p.name for p in (lib / ".solidseas" / "vault" / "store" / "objects").rglob("*") if p.is_file()
    )


def records(lib) -> list:
    folder = lib / ".solidseas" / "vault" / "checkins"
    return sorted(folder.rglob("*.json"))


def test_checkin_stores_shared_content_once(lib):
    vault = pdm.init(lib)
    result = vault.checkin([lib / "Jobs"], "first issue", revision="A", state="draft", who="D. M.")
    data = result.data()
    assert data["stored"] == 3 and data["counts"]["new"] == 3
    assert len(objects(lib)) == 2  # the two brackets are one content
    (rec,) = records(lib)
    c = parse_checkin(rec.read_bytes(), rec.name, rec.parent.name)
    assert (c.note, c.revision, c.state, c.who, c.auto) == ("first issue", "A", "draft", "D. M.", False)
    assert sorted(f.path for f in c.files) == [
        "Jobs/1042/bracket.sldprt",
        "Jobs/1042/plate.step",
        "Jobs/1043/bracket.sldprt",
    ]
    by_path = {f.path: f for f in c.files}
    assert by_path["Jobs/1042/bracket.sldprt"].sha256 == by_path["Jobs/1043/bracket.sldprt"].sha256
    assert by_path["Jobs/1042/bracket.sldprt"].snapshot != by_path["Jobs/1043/bracket.sldprt"].snapshot
    assert all(f.new and not f.removed for f in c.files)
    again = vault.checkin([lib / "Jobs" / "1042"], "label it", revision="B").data()
    assert again["stored"] == 0 and again["counts"]["unchanged"] == 2 and len(records(lib)) == 2
    assert all(not f["stored"] and f["version"] for f in again["files"])


def test_checkin_records_gone_files(lib):
    vault = pdm.init(lib)
    vault.checkin([lib], "first")
    (lib / "Jobs" / "1042" / "plate.step").unlink()
    assert vault.status().counts["gone"] == 1
    data = vault.checkin([lib / "Jobs" / "1042"], "plate dropped").data()
    assert {f["path"]: f["state"] for f in data["files"]}["Jobs/1042/plate.step"] == "gone"
    assert vault.status().counts == {"new": 0, "changed": 0, "gone": 0, "unchanged": 2}
    write(lib / "Jobs" / "1042" / "plate.step", "plate back")
    assert {f.path: f.state for f in vault.status().files} == {"Jobs/1042/plate.step": "changed"}


def test_checkin_needs_a_note_and_something_tracked(lib):
    vault = pdm.init(lib)
    with pytest.raises(InvalidArgumentError):
        vault.checkin([lib], "  ")
    with pytest.raises(InvalidArgumentError):
        vault.checkin([lib], "x", revision="r" * 65)
    (lib / "Empty").mkdir()
    with pytest.raises(InvalidArgumentError) as err:
        vault.checkin([lib / "Empty"], "nothing")
    assert err.value.detail["rule"] == "nothing_tracked"
    with pytest.raises(PathRefusedError):
        vault.checkin([lib.parent], "outside")


def test_scan(lib):
    vault = pdm.init(lib)
    data = vault.scan().data()
    assert data["stored"] == 3 and data["checkin"]["auto"] and data["checkin"]["note"] is None
    assert len(records(lib)) == 1
    nothing = vault.scan().data()
    assert nothing["checkin"] is None and nothing["stored"] == 0 and len(records(lib)) == 1
    write(lib / "Jobs" / "1043" / "bracket.sldprt", "bracket changed in 1043")
    (lib / "Jobs" / "1042" / "plate.step").unlink()
    data = vault.scan(lib / "Jobs").data()
    assert data["stored"] == 1 and data["counts"]["gone"] == 1
    assert vault.status().counts["gone"] == 1  # a scan only reports a gone file


# --------------------------------------------------------------------------- log
def test_log_is_newest_first_with_notes(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "first cut", revision="A")
    write(part, "bracket two")
    vault.scan()
    write(part, "bracket three")
    vault.checkin([part], "holes moved", revision="B", state="released")
    vault.checkin([part], "same file, labelled again")
    write(part, "bracket four")
    log = vault.log(part)
    assert log["path"] == "Jobs/1042/bracket.sldprt" and log["git"] is None
    assert [v["source"] for v in log["versions"]] == ["working", "vault", "vault", "vault"]
    assert [v["number"] for v in log["versions"]] == [4, 3, 2, 1]
    v3, v2, v1 = log["versions"][1:]
    assert [c["note"] for c in v3["checkins"]] == ["same file, labelled again", "holes moved"]
    assert v3["checkins"][1]["revision"] == "B" and v3["checkins"][1]["state"] == "released"
    assert v2["checkins"][0]["auto"] and v1["checkins"][0]["note"] == "first cut"


# --------------------------------------------------------------------------- restore
def test_restore_replaces_after_storing_the_current_file(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "first")
    write(part, "edited, never checked in")
    result = vault.restore(part, "v1")
    assert part.read_text() == "bracket one" and result["replaced"] and result["written"]
    assert result["stored_first"]["new"]
    log = vault.log(part)
    notes = [v["subject"] for v in log["versions"]]
    assert notes[0].startswith("Restored v1") and notes[1] == "stored before restoring v1"
    assert (
        versions.read_version(part, "v2", source="snapshots", store=vault.store)
        == b"edited, never checked in"
    )
    assert vault.status().counts["changed"] == 0
    assert not [p for p in part.parent.iterdir() if p.name.startswith(".")]  # no temporary file left


def test_restore_as_a_new_file(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "first")
    write(part, "bracket two")
    result = vault.restore(part, "v1", as_name="bracket v1.sldprt")
    assert (part.parent / "bracket v1.sldprt").read_text() == "bracket one"
    assert part.read_text() == "bracket two" and not result["replaced"]
    assert result["path"] == "Jobs/1042/bracket v1.sldprt" and result["from"] == "Jobs/1042/bracket.sldprt"
    assert result["stored_first"]["new"]  # the current file was stored too
    with pytest.raises(OutputRefusedError):
        vault.restore(part, "v1", as_name="bracket v1.sldprt")
    for bad in ("../x.sldprt", "sub/x.sldprt", ".x.sldprt", "x.txt"):
        with pytest.raises(InvalidArgumentError):
            vault.restore(part, "v1", as_name=bad)


def test_restore_a_deleted_file_and_an_unchanged_one(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "plate.step"
    vault.checkin([part], "first")
    unchanged = vault.restore(part, "latest")
    assert not unchanged["written"] and unchanged["checkin"] is None and part.read_text() == "plate one"
    part.unlink()
    result = vault.restore(part, "v1")
    assert result["written"] and result["stored_first"] is None and part.read_text() == "plate one"


def test_restore_names_the_version_before_storing_the_current_file(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "first")
    write(part, "edited")
    result = vault.restore(part, "latest")  # the newest version in the vault, not the edit just stored
    assert result["version"]["number"] == 1 and part.read_text() == "bracket one"
    write(part, "edited again")
    with pytest.raises(InvalidArgumentError):
        vault.restore(part, "working")
    assert part.read_text() == "edited again"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_restore_refuses_links(lib, tmp_path):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "first")
    target = tmp_path / "elsewhere.sldprt"
    write(target, "not in the library")
    part.unlink()
    os.symlink(target, part)
    with pytest.raises(LinkRefusedError):
        vault.restore(part, "v1")
    assert target.read_text() == "not in the library"
    plate = lib / "Jobs" / "1042" / "plate.step"
    vault.checkin([plate], "first")
    os.symlink(tmp_path / "nowhere.step", plate.parent / "taken.step")
    with pytest.raises(OutputRefusedError):
        vault.restore(plate, "v1", as_name="taken.step")
    assert not (tmp_path / "nowhere.step").exists()


# --------------------------------------------------------------------------- records others may write
def test_malformed_records_are_skipped(lib):
    vault = pdm.init(lib)
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    vault.checkin([part], "good one")
    (good,) = records(lib)
    year = good.parent
    text = json.loads(good.read_text())
    bad = {
        "20260101T000000000000Z-aaaaaaaaaaaa.json": b"not json",
        "20260101T000000000001Z-bbbbbbbbbbbb.json": json.dumps(dict(text, id="bbbbbbbbbbbc")).encode(),
        "20260101T000000000002Z-cccccccccccc.json": json.dumps(dict(text, id="cccccccccccc")).encode(),
        "20260101T000000000003Z-dddddddddddd.json": json.dumps(
            dict(text, id="dddddddddddd", when_utc="2026-01-01T00:00:00.000003Z", files=[{"path": "../x"}])
        ).encode(),
        "20260101T000000000004Z-eeeeeeeeeeee.json": json.dumps(
            dict(text, id="eeeeeeeeeeee", when_utc="2026-01-01T00:00:00.000004Z", note=7)
        ).encode(),
        "readme.txt": b"ignored",
    }
    for name, data in bad.items():
        (year / name).write_bytes(data)
    elsewhere = year.parent / "1999"
    elsewhere.mkdir()
    (elsewhere / good.name).write_bytes(good.read_bytes())  # in the wrong year's folder
    assert [c.note for c in vault.checkins()] == ["good one"]
    snaps = lib / ".solidseas" / "vault" / "store" / "files"
    (folder,) = [p for p in snaps.iterdir() if p.is_dir()]
    (folder / "29990101T000000000000Z-ffffffffffff.json").write_bytes(b"{broken")
    log = vault.log(part)
    assert [v["checkins"][0]["note"] for v in log["versions"]] == ["good one"]
    assert vault.status().counts == {"new": 2, "changed": 0, "gone": 0, "unchanged": 1}


# --------------------------------------------------------------------------- the command line
def run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind and env["ok"] is (kind != "error")
    assert validate(env, model.envelope_schema(kind), strict=True) == []
    return env["data"] if env["ok"] else env["error"]


def test_every_action_as_json(capsys, lib):
    part = lib / "Jobs" / "1042" / "model.x_b"
    shutil.copyfile(XB_A, part)
    code, env = run(capsys, "pdm", "init", str(lib))
    data = check(env, "pdm_result")
    assert code == 0 and data["action"] == "init" and data["init"]["created"] and data["library"] == str(lib)
    code, env = run(capsys, "pdm", "status", str(lib))
    data = check(env, "pdm_result")
    assert code == 0 and data["status"]["counts"]["new"] == 4 and data["checkin"] is None
    code, env = run(capsys, "pdm", "checkin", str(lib / "Jobs"), "-m", "first", "--revision", "A")
    data = check(env, "pdm_result")
    assert code == 0 and data["checkin"]["stored"] == 4 and data["checkin"]["checkin"]["revision"] == "A"
    shutil.copyfile(XB_B, part)
    code, env = run(capsys, "pdm", "scan", str(lib))
    data = check(env, "pdm_result")
    assert code == 0 and data["action"] == "scan" and data["checkin"]["stored"] == 1
    code, env = run(capsys, "pdm", "log", str(part))
    data = check(env, "pdm_result")
    assert code == 0 and [v["number"] for v in data["log"]["versions"]] == [2, 1]
    code, env = run(capsys, "pdm", "show", str(part), "v1")
    data = check(env, "pdm_result")["show"]
    assert code == 0 and data["version"]["number"] == 1 and data["geometry"]["configurations"]
    code, env = run(capsys, "pdm", "diff", str(part), "--no-measures")
    data = check(env, "pdm_result")["diff"]
    assert code == 0 and (data["from"]["number"], data["to"]["number"]) == (1, 2)
    assert data["geometry"]["configurations"][0]["status"] == "changed"
    code, env = run(capsys, "pdm", "restore", str(part), "v1", "--as", "model v1.x_b")
    data = check(env, "pdm_result")["restore"]
    assert code == 0 and data["path"] == "Jobs/1042/model v1.x_b"
    assert (lib / "Jobs" / "1042" / "model v1.x_b").read_bytes() == XB_A.read_bytes()
    code, env = run(capsys, "pdm", "status", str(lib / "Jobs" / "1043" / "notes.txt"))
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"
    code, env = run(capsys, "pdm", "restore", str(part), "v1", "--as", "model v1.x_b")
    assert code != 0 and check(env, "error")["code"] == "output_refused"


def test_plain_words(capsys, lib):
    assert cli.main(["pdm", "init", str(lib)]) == 0
    assert "is now a library" in capsys.readouterr().out
    assert cli.main(["pdm", "status", str(lib)]) == 0
    out = capsys.readouterr().out
    assert "new       Jobs/1042/bracket.sldprt" in out and "3 new, 0 changed, 0 gone, 0 unchanged" in out
    assert cli.main(["pdm", "checkin", str(lib), "-m", "first issue", "--revision", "A"]) == 0
    assert "3 stored, 0 unchanged, revision A" in capsys.readouterr().out
    assert cli.main(["pdm", "scan", str(lib)]) == 0
    assert "nothing new to store (3 unchanged)" in capsys.readouterr().out
    part = lib / "Jobs" / "1042" / "bracket.sldprt"
    write(part, "bracket two")
    assert cli.main(["pdm", "log", str(part)]) == 0
    out = capsys.readouterr().out
    assert "working copy" in out and "first issue [revision A]" in out
    assert cli.main(["pdm", "restore", str(part), "v1"]) == 0
    out = capsys.readouterr().out
    assert "stored the current file first" in out and "put v1" in out
    assert part.read_text() == "bracket one"


def test_an_unknown_action_is_a_usage_error(capsys):
    code, env = run(capsys, "pdm", "nope")
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"
