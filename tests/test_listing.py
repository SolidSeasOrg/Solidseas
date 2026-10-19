"""Folder listings: one entry per document from the same sub-builders as the summary,
lazy reads with the handle closed after each file, and one bad file never stopping
the listing."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from builders import o05_with_ghost_configuration, o06_with_active_alt, rebuild
from fakefs import ARCHIVE, DIRECTORY, REPARSE, FakeEntry, fake_tree
from jsonschema_subset import validate
from solidseas import cli, model, scan
from solidseas import listing as listing_mod
from solidseas.errors import InvalidArgumentError
from solidseas.formats.solidworks import container as container_mod
from solidseas.formats.solidworks import open_document
from support import ASSEMBLY, FIXTURES, NATIVE, PARTS, fixture_path

WINDOWS = os.name == "nt"
ALL = ("properties", "configurations", "preview")
SHARED = ("file", "format", "doc_type", "saved_version", "active_configuration", "configurations", "warnings")


def _fixture_folder(tmp_path, names=NATIVE):
    folder = tmp_path / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(fixture_path(name), folder / name)
    return folder


def _check_schema(data):
    errors = validate(data, model.KINDS["listing"].schema, strict=True)
    assert errors == [], errors[:5]
    env = model.envelope("listing", data, source={"folder": "x"})
    assert validate(env, model.envelope_schema("listing"), strict=True) == []
    model.dumps(env)  # strict encoding


# --------------------------------------------------------------------------- the same data as the summary
def test_every_fixture_entry_matches_its_summary(tmp_path):
    folder = _fixture_folder(tmp_path)
    data = scan(folder, include=ALL).listing()
    _check_schema(data)
    entries = {e["path"]: e for e in data["entries"]}
    assert len(entries) == len(NATIVE) == 8
    for name in NATIVE:
        e = entries[name]
        assert (e["type"], e["status"], e["error"]) == ("file", "ok", None), name
        with open_document(folder / name) as doc:  # read whole, the default
            summary = doc.summary()
            effective = model.build_properties(doc)["properties"]
        for key in SHARED:  # critique 3.11: one set of sub-builders for both
            assert e[key] == summary[key], (name, key)
        assert e["properties"] == effective
        assert {k: v for k, v in e["preview"].items() if k != "data_base64"} == summary["preview"]
        assert e["preview"]["data_base64"] is None and e["preview"]["available"]
    assert data["counts"] == {
        "entries": 8,
        "ok": 8,
        "error": 0,
        "skipped": 0,
        "link": 0,
        "placeholder": 0,
        "not_solidworks": 0,
        "unsupported": 0,
        "folders": 1,
    }
    assert (data["truncated"], data["truncated_reason"], data["preview_data_capped"]) == (False, None, False)


def test_entries_carry_effective_properties_and_the_summarys_warnings(tmp_path):
    """The fixture comparison above cannot tell these apart: none of o01 to o08, the
    fixtures it lists, has a reader warning or an active configuration with properties
    of its own."""
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / "alt.SLDPRT").write_bytes(o06_with_active_alt())
    (folder / "ghost.SLDPRT").write_bytes(o05_with_ghost_configuration())
    data = scan(folder, include=ALL).listing()
    _check_schema(data)
    by = {e["path"]: e for e in data["entries"]}
    with open_document(folder / "alt.SLDPRT") as doc:
        alt_summary = doc.summary()
    with open_document(folder / "ghost.SLDPRT") as doc:
        ghost_summary = doc.summary()
    # API 5.7: a listing's properties are the active configuration's effective properties
    alt = by["alt.SLDPRT"]
    assert alt["active_configuration"] == "OracleAlt"
    cfg_only = [p for p in alt["properties"] if p["name"] == "CfgOnly"]
    assert [(p["scope"], p["configuration"]) for p in cfg_only] == [("configuration", "OracleAlt")]
    assert len(alt["properties"]) == 4
    # API 5.1: the summary's properties are the file-level ones only
    assert [p["name"] for p in alt_summary["properties"]] == ["PartNo", "Description", "Qty"]
    # entries carry the summary's warnings, and here there is one to carry
    ghost = by["ghost.SLDPRT"]
    assert ghost["warnings"] == ghost_summary["warnings"]
    assert [w["code"] for w in ghost["warnings"]] == ["materialtree_unknown_configuration"]


def test_default_include_is_the_preview_only(tmp_path):
    folder = _fixture_folder(tmp_path, [PARTS[1]])
    (e,) = scan(folder).listing()["entries"]
    assert e["preview"]["available"] and e["properties"] is None and e["configurations"] is None
    (bare,) = scan(folder, include=()).listing()["entries"]
    assert bare["preview"] is None and bare["saved_version"]["format_version"] == 17000


def test_a_document_without_a_preview_says_not_stored(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / "bare.SLDPRT").write_bytes(
        rebuild(fixture_path("o02_boxA.SLDPRT"), drop=("PreviewPNG", "Preview"))
    )
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), folder / "with.SLDPRT")
    data = scan(folder, include=("preview_data",)).listing()
    _check_schema(data)
    entries = {e["path"]: e for e in data["entries"]}
    bare = entries["bare.SLDPRT"]
    assert bare["status"] == "ok" and bare["error"] is None
    assert bare["preview"] == {
        "available": False,
        "reason": "not_stored",
        "mime": None,
        "width": None,
        "height": None,
        "bytes": None,
        "stream": None,
        "sha256": None,
        "data_base64": None,
    }
    assert entries["with.SLDPRT"]["preview"]["available"]  # control: the same part with its preview
    with open_document(folder / "bare.SLDPRT") as doc:
        assert doc.summary()["preview"]["reason"] == "not_stored"


def test_inline_preview_data_and_its_cap(tmp_path):
    folder = _fixture_folder(tmp_path, PARTS[1:4])
    data = scan(folder, include=("preview_data",)).listing()
    for e in data["entries"]:
        image = base64.b64decode(e["preview"]["data_base64"], validate=True)
        assert hashlib.sha256(image).hexdigest() == e["preview"]["sha256"] and image[:4] == b"\x89PNG"
    one = len(data["entries"][0]["preview"]["data_base64"])
    capped = scan(folder, include=("preview_data",), max_preview_data_bytes=one).listing()
    first, *rest = capped["entries"]
    assert first["preview"]["data_base64"] and capped["preview_data_capped"]
    assert rest and all(e["preview"]["data_base64"] is None and e["preview"]["available"] for e in rest)


# --------------------------------------------------------------------------- statuses
def test_one_bad_file_never_stops_the_listing(tmp_path, monkeypatch):
    folder = _fixture_folder(tmp_path, [PARTS[1], PARTS[3], ASSEMBLY])
    damaged = (folder / PARTS[1]).read_bytes()
    (folder / "damaged.SLDPRT").write_bytes(damaged[: len(damaged) // 2])
    (folder / "junk.SLDPRT").write_bytes(b"not a CAD file at all")
    real = listing_mod.open_document

    def flaky(path, *args, **kwargs):
        if os.path.basename(path) == PARTS[3]:
            raise ValueError("an unexpected bug in a reader")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(listing_mod, "open_document", flaky)
    data = scan(folder).listing()
    _check_schema(data)
    by = {e["path"]: e for e in data["entries"]}
    assert by["damaged.SLDPRT"]["error"]["code"] == "damaged_file"
    assert by["junk.SLDPRT"]["error"]["code"] == "unknown_format"
    assert by[PARTS[3]]["error"]["code"] == "internal"
    assert by[PARTS[3]]["file"]["size"] == (folder / PARTS[3]).stat().st_size  # still described
    assert by[PARTS[1]]["status"] == by[ASSEMBLY]["status"] == "ok"
    c = data["counts"]
    assert (c["entries"], c["ok"], c["error"]) == (5, 2, 3)


def test_reader_message_can_be_left_out_of_error_objects(tmp_path):
    folder = _fixture_folder(tmp_path, [PARTS[1]])
    damaged = (folder / PARTS[1]).read_bytes()
    (folder / "damaged.SLDPRT").write_bytes(damaged[: len(damaged) // 2])
    with_text = {e["path"]: e for e in scan(folder).listing()["entries"]}["damaged.SLDPRT"]["error"]
    assert isinstance(with_text["reader_message"], str) and with_text["reader_message"]  # control
    quiet = {e["path"]: e for e in scan(folder, reader_message=False).listing()["entries"]}
    err = quiet["damaged.SLDPRT"]["error"]
    assert (err["code"], err["reader_message"]) == ("damaged_file", None)
    assert err == {**with_text, "reader_message": None}
    assert quiet[PARTS[1]]["status"] == "ok"


def _unreadable_subfolder(monkeypatch, tmp_path):
    shutil.copyfile(fixture_path(PARTS[1]), tmp_path / "real.SLDPRT")
    size = (tmp_path / "real.SLDPRT").stat().st_size
    tree = {
        "": [FakeEntry("denied", DIRECTORY), FakeEntry("real.SLDPRT", ARCHIVE, size=size)],
        "denied": PermissionError(13, "Access is denied"),
    }
    fake_tree(monkeypatch, tmp_path, tree)


def test_an_unreadable_subfolder_is_an_error_entry(monkeypatch, tmp_path):
    _unreadable_subfolder(monkeypatch, tmp_path)
    data = scan(tmp_path, recursive=True).listing()
    _check_schema(data)
    by = {e["path"]: e for e in data["entries"]}
    d = by["denied"]
    assert (d["type"], d["status"], d["error"]["code"]) == ("folder", "error", "permission_denied")
    assert by["real.SLDPRT"]["status"] == "ok" and data["counts"]["error"] == 1


def test_list_exits_4_for_an_unreadable_subfolder_with_and_without_json(monkeypatch, tmp_path, capsys):
    _unreadable_subfolder(monkeypatch, tmp_path)
    assert cli.main(["list", str(tmp_path), "--recursive"]) == cli.EXIT_PARTIAL
    out = capsys.readouterr().out
    assert "permission_denied" in out and "error 1" in out
    assert cli.main(["list", str(tmp_path), "--recursive", "--json"]) == cli.EXIT_PARTIAL
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] and env["data"]["counts"]["error"] == 1
    assert cli.main(["list", str(tmp_path)]) == cli.EXIT_OK  # control: not recursive, nothing failed
    capsys.readouterr()


def test_lock_files_are_skipped_and_never_opened(tmp_path, monkeypatch):
    folder = _fixture_folder(tmp_path, [PARTS[1]])
    (folder / "~$o02_boxA.SLDPRT").write_bytes(b"\0" * 64)
    (folder / "~$notes.docx").write_bytes(b"\0" * 8)  # not a SOLIDWORKS lock file: not listed
    opened = []
    real = listing_mod.open_document
    monkeypatch.setattr(listing_mod, "open_document", lambda p, *a, **k: opened.append(p) or real(p, *a, **k))
    data = scan(folder).listing()
    lock = next(e for e in data["entries"] if e["path"].startswith("~$"))
    assert (lock["status"], lock["reason"], lock["file"]["size"]) == ("skipped", "lock_file", 64)
    assert len(data["entries"]) == 2 and data["counts"]["skipped"] == 1
    assert [os.path.basename(p) for p in opened] == [PARTS[1]]


def test_step_wearing_a_solidworks_extension(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / "bracket.step.SLDASM").write_bytes(b"\r\n \t ISO-10303-21;\nHEADER;\nENDSEC;\n")
    (folder / "bom.SLDPRT").write_bytes(b"\xef\xbb\xbfISO-10303-21;\n")
    data = scan(folder).listing()
    _check_schema(data)
    for e in data["entries"]:
        assert (e["status"], e["detected"], e["error"]) == ("not_solidworks", "step", None)
    assert data["counts"]["not_solidworks"] == 2 and data["counts"]["error"] == 0


@pytest.mark.skipif(not WINDOWS, reason="byte-range locks through msvcrt")
def test_a_locked_file_is_a_retryable_entry(tmp_path):
    import msvcrt

    folder = _fixture_folder(tmp_path, [PARTS[1], PARTS[2]])
    locked = folder / PARTS[2]
    size = locked.stat().st_size
    with open(locked, "rb") as holder:
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, size)
        try:
            data = scan(folder).listing()
        finally:
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, size)
    by = {e["path"]: e for e in data["entries"]}
    err = by[PARTS[2]]["error"]
    assert (by[PARTS[2]]["status"], err["code"], err["retryable"]) == ("error", "locked", True)
    assert by[PARTS[1]]["status"] == "ok" and data["counts"]["error"] == 1


def test_placeholders_are_listed_and_never_read(tmp_path, monkeypatch):
    shutil.copyfile(fixture_path(PARTS[1]), tmp_path / "real.SLDPRT")
    entries = [
        FakeEntry("online.SLDPRT", ARCHIVE | REPARSE | 0x400000, 0x9000601A, size=500_000),
        FakeEntry("offline.SLDASM", ARCHIVE | 0x1000, size=7),
        FakeEntry("recall.SLDDRW", ARCHIVE | 0x40000, size=9),
        FakeEntry("real.SLDPRT", ARCHIVE, size=(tmp_path / "real.SLDPRT").stat().st_size),
    ]
    fake_tree(monkeypatch, tmp_path, {"": entries})
    opened: list[str] = []
    for mod in (container_mod, listing_mod):  # every way a listing could open a file
        real = mod.open_readonly
        monkeypatch.setattr(
            mod, "open_readonly", lambda p, _real=real, **kw: opened.append(p) or _real(p, **kw)
        )
    data = scan(tmp_path).listing()
    by = {e["path"]: e for e in data["entries"]}
    placeholders = [e for e in by.values() if e["status"] == "placeholder"]
    assert len(placeholders) == 3 and data["counts"]["placeholder"] == 3
    assert by["online.SLDPRT"]["reason"] == "recall_on_data_access"
    assert by["online.SLDPRT"]["file"]["size"] == 500_000
    assert by["real.SLDPRT"]["status"] == "ok"
    assert [os.path.basename(p) for p in opened] == ["real.SLDPRT"]  # the wrapper saw reads: it works


def test_folders_links_and_depth(tmp_path):
    folder = _fixture_folder(tmp_path, [PARTS[1]])
    (folder / "sub" / "deeper").mkdir(parents=True)
    shutil.copyfile(fixture_path(PARTS[2]), folder / "sub" / PARTS[2])
    shutil.copyfile(fixture_path(PARTS[3]), folder / "sub" / "deeper" / PARTS[3])
    flat = scan(folder).listing()
    assert [(e["path"], e["type"], e["status"]) for e in flat["entries"]] == [
        (PARTS[1], "file", "ok"),
        ("sub", "folder", "ok"),
    ]
    assert flat["entries"][1]["file"] is None
    deep = scan(folder, recursive=True).listing()
    assert [e["path"] for e in deep["entries"]] == [PARTS[1], f"sub/{PARTS[2]}", f"sub/deeper/{PARTS[3]}"]
    assert deep["counts"]["folders"] == 3
    limited = scan(folder, recursive=True, max_depth=2).listing()
    by = {e["path"]: e for e in limited["entries"]}
    assert by["sub/deeper"] == model.listing_entry("sub/deeper", "folder", "skipped", reason="max_depth")
    assert f"sub/deeper/{PARTS[3]}" not in by and limited["counts"]["skipped"] == 1
    _check_schema(limited)


@pytest.mark.skipif(not WINDOWS, reason="directory junctions")
def test_a_junction_is_a_link_entry(tmp_path):
    import _winapi

    folder = _fixture_folder(tmp_path, [PARTS[1]])
    outside = _fixture_folder(tmp_path / "x", [PARTS[2]])
    _winapi.CreateJunction(str(outside), str(folder / "jn"))
    try:
        assert (folder / "jn" / PARTS[2]).is_file()  # control: it leads to a document outside
        data = scan(folder, recursive=True).listing()
    finally:
        os.rmdir(folder / "jn")
    assert [(e["path"], e["status"], e["type"], e["reason"]) for e in data["entries"]] == [
        ("jn", "link", "folder", "junction"),
        (PARTS[1], "ok", "file", None),
    ]


# --------------------------------------------------------------------------- what changes after the walk
def _make_folder_link(target: Path, link: Path) -> None:
    """A junction on Windows (no extra rights needed), a symbolic link elsewhere."""
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_folder_link(link: Path) -> None:
    if WINDOWS:
        os.rmdir(link)  # removes the junction, not what it points at
    else:
        os.unlink(link)


def test_a_folder_swapped_for_a_link_during_the_listing_is_refused(tmp_path):
    """The walker lists a folder, then reads its documents one by one. A folder on the
    way that becomes a link in between must not lead the read out of the root."""
    root = tmp_path / "root"
    (root / "z").mkdir(parents=True)
    shutil.copyfile(fixture_path(PARTS[1]), root / "z" / "b.SLDPRT")
    shutil.copyfile(fixture_path(PARTS[2]), root / "z" / "c.SLDPRT")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(fixture_path(PARTS[6]), outside / "c.SLDPRT")  # another document, of another size
    entries = iter(scan(root, recursive=True))
    first = next(entries)
    assert (first["path"], first["status"]) == ("z/b.SLDPRT", "ok")  # z has been listed
    (root / "z").rename(root / "z_was")
    _make_folder_link(outside, root / "z")
    try:
        # control: the same name now leads to the document outside the root
        assert (root / "z" / "c.SLDPRT").stat().st_size == (outside / "c.SLDPRT").stat().st_size
        rest = list(entries)
    finally:
        _remove_folder_link(root / "z")
    (c,) = [e for e in rest if e["path"] == "z/c.SLDPRT"]
    assert (c["status"], c["error"]["code"], c["format"]) == ("error", "link_refused", None)
    assert (outside / "c.SLDPRT").is_file()


@pytest.mark.skipif(not WINDOWS, reason="elsewhere the walker's lazy lstat already sees the link")
def test_a_file_swapped_for_a_symbolic_link_after_its_folder_was_listed_is_refused(tmp_path):
    folder = _fixture_folder(tmp_path, [PARTS[1], PARTS[2]])
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(fixture_path(PARTS[6]), outside / "secret.SLDPRT")
    entries = iter(scan(folder))
    assert next(entries)["path"] == PARTS[1]
    victim = folder / PARTS[2]
    victim.unlink()
    try:
        os.symlink(outside / "secret.SLDPRT", victim)
    except OSError:
        pytest.skip("symbolic links need extra rights here")
    assert victim.stat().st_size == (outside / "secret.SLDPRT").stat().st_size  # control: it leads out
    (e,) = list(entries)
    assert (e["path"], e["status"], e["error"]["code"]) == (PARTS[2], "error", "link_refused")
    assert e["saved_version"] is None


@pytest.mark.skipif(not WINDOWS, reason="file attributes")
def test_a_file_that_became_a_placeholder_after_its_folder_was_listed_is_not_read(tmp_path):
    import ctypes

    set_attributes = ctypes.WinDLL("kernel32", use_last_error=True).SetFileAttributesW
    folder = _fixture_folder(tmp_path, [PARTS[1], PARTS[2]])
    entries = iter(scan(folder))
    assert next(entries)["path"] == PARTS[1]
    target = str(folder / PARTS[2])
    assert set_attributes(target, 0x1000 | 0x20)  # FILE_ATTRIBUTE_OFFLINE, as an HSM or cloud file
    try:
        assert os.stat(target).st_file_attributes & 0x1000  # control: the attribute is there
        (e,) = list(entries)
    finally:
        set_attributes(target, 0x80)
    assert (e["path"], e["status"], e["error"]["code"]) == (PARTS[2], "error", "placeholder_file")


def test_a_root_that_is_a_link_is_read_through(tmp_path):
    outside = _fixture_folder(tmp_path / "x", [PARTS[2]])
    alias = tmp_path / "alias"
    try:
        _make_folder_link(outside, alias)
    except OSError:
        pytest.skip("symbolic links need extra rights here")
    try:
        data = scan(alias).listing()  # a root is configuration (C6): links below it are refused
    finally:
        _remove_folder_link(alias)
    assert [(e["path"], e["status"]) for e in data["entries"]] == [(PARTS[2], "ok")]


SRC = Path(__file__).resolve().parents[1] / "src"
_SCAN_IN_A_CHILD = (
    "import sys\nfrom solidseas import model, scan\nprint(model.dumps(scan(sys.argv[1]).listing()))"
)


@pytest.mark.skipif(WINDOWS, reason="FIFOs are made with os.mkfifo on Linux and macOS")
def test_a_fifo_named_like_a_document_never_blocks(tmp_path):
    """Opening a FIFO waits for a writer, forever. Each run is a child process with a
    timeout, so a regression fails here instead of hanging the suite."""
    folder = _fixture_folder(tmp_path, [PARTS[1]])
    os.mkfifo(folder / "trap.SLDPRT")
    env = {**os.environ, "PYTHONPATH": str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def child(*argv):
        return subprocess.run(
            [sys.executable, *argv], capture_output=True, text=True, env=env, timeout=60, check=False
        )

    expected = [(PARTS[1], "ok", None), ("trap.SLDPRT", "skipped", "not_regular_file")]
    proc = child("-c", _SCAN_IN_A_CHILD, str(folder))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert [(e["path"], e["status"], e["reason"]) for e in data["entries"]] == expected
    proc = child("-m", "solidseas", "list", str(folder), "--json")
    assert proc.returncode == 0, proc.stdout
    data = json.loads(proc.stdout)["data"]
    assert [(e["path"], e["status"], e["reason"]) for e in data["entries"]] == expected
    out = tmp_path / "out"
    proc = child("-m", "solidseas", "batch", str(folder), "-o", str(out), "--no-parasolid", "--json")
    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["data"]["status_counts"] == {"ok": 1, "skipped": 1}
    proc = child("-m", "solidseas", "info", str(folder / "trap.SLDPRT"), "--json")
    assert proc.returncode == cli.EXIT_REFUSED, proc.stdout
    assert json.loads(proc.stdout)["error"]["detail"] == {"rule": "not_regular_file"}


def test_entry_and_time_limits(tmp_path):
    folder = _fixture_folder(tmp_path, PARTS)
    two = scan(folder, max_entries=2).listing()
    assert len(two["entries"]) == 2 and (two["truncated"], two["truncated_reason"]) == (True, "max_entries")
    exact = scan(folder, max_entries=len(PARTS)).listing()
    assert len(exact["entries"]) == len(PARTS) and not exact["truncated"]
    s = scan(folder, max_seconds=60)
    s._deadline = time.monotonic() - 1  # as if the minute had passed
    late = s.listing()
    assert late["entries"] == [] and late["truncated_reason"] == "deadline"


def test_max_examined_bounds_the_walk_over_a_sparse_tree(monkeypatch, tmp_path, capsys):
    """max_entries counts entries listed; to say "not truncated" the walk must still look
    at everything else. max_examined bounds that look."""
    shutil.copyfile(fixture_path(PARTS[1]), tmp_path / "real.SLDPRT")
    size = (tmp_path / "real.SLDPRT").stat().st_size
    noise = [FakeEntry(f"note{i:04}.txt", ARCHIVE, size=1) for i in range(1000)]
    fake_tree(monkeypatch, tmp_path, {"": [FakeEntry("real.SLDPRT", ARCHIVE, size=size), *noise]})
    unbounded = scan(tmp_path, max_entries=1)
    assert len(unbounded.listing()["entries"]) == 1
    assert unbounded.walk_stats.entries == 1001 and unbounded.truncated_reason is None  # looked at all
    bounded = scan(tmp_path, max_examined=50)
    data = bounded.listing()
    assert bounded.walk_stats.entries == 50
    assert (data["truncated"], data["truncated_reason"]) == (True, "max_examined")
    assert [e["path"] for e in data["entries"]] == ["real.SLDPRT"]
    with pytest.raises(InvalidArgumentError):
        scan(tmp_path, max_examined=0)
    assert cli.main(["list", str(tmp_path), "--max-examined", "50", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["data"]["truncated_reason"] == "max_examined"


def test_the_handle_is_closed_before_the_next_file(tmp_path, monkeypatch):
    folder = _fixture_folder(tmp_path, PARTS[:4])
    handles = []
    real = container_mod.open_readonly

    def tracked(path, **kw):
        assert all(h.closed for h in handles), "a previous document was still held open"
        fh = real(path, **kw)
        handles.append(fh)
        return fh

    monkeypatch.setattr(container_mod, "open_readonly", tracked)
    entries = list(scan(folder))
    assert len(entries) == len(handles) == 4 and all(h.closed for h in handles)


def test_arguments_are_checked(tmp_path):
    with pytest.raises(InvalidArgumentError):
        scan(tmp_path, include=("thumbnails",))
    with pytest.raises(InvalidArgumentError):
        scan(tmp_path, max_entries=0)
    with pytest.raises(InvalidArgumentError):
        scan(tmp_path, max_seconds=-1)
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "missing")
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(NotADirectoryError):
        scan(tmp_path / "f.txt")
    s = scan(tmp_path)
    assert s.listing()["entries"] == []
    with pytest.raises(RuntimeError):
        list(s)


def test_a_listing_reads_less_than_the_files(tmp_path, monkeypatch):
    """The real bound is measured on the corpus; here the counter must see every read
    and a listing must read less than whole files would."""
    folder = _fixture_folder(tmp_path, [ASSEMBLY, PARTS[6]])
    read = [0]
    real = container_mod.open_readonly

    class Counting:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n=-1):
            data = self._fh.read(n)
            read[0] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

    monkeypatch.setattr(container_mod, "open_readonly", lambda p, **kw: Counting(real(p, **kw)))
    data = scan(folder, include=ALL).listing()
    total = sum(e["file"]["size"] for e in data["entries"])
    assert data["counts"]["ok"] == 2 and 0 < read[0] < total


# --------------------------------------------------------------------------- threads
def _copies(tmp_path: Path, n: int = 3) -> Path:
    """The fixture documents, ``n`` times over in subfolders, with a lock file and a
    STEP file wearing a part's name among them."""
    root = tmp_path / "many"
    for k in range(n):
        d = root / f"d{k}"
        d.mkdir(parents=True)
        for f in FIXTURES.iterdir():
            if f.suffix.lower() in (".sldprt", ".sldasm", ".slddrw"):
                shutil.copy(f, d / f.name)
    (root / "d0" / "~$o02_boxA.SLDPRT").write_bytes(b"lock")
    (root / "d1" / "fake.SLDPRT").write_bytes(b"ISO-10303-21;\nHEADER;\n")
    return root


def _listed(folder: Path, **options):
    s = scan(folder, recursive=True, **options)
    entries = list(s)
    return entries, dict(s.counts), s.truncated_reason, s.preview_data_capped


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"include": ("preview_data", "properties")},
        {"include": ("preview_data",), "max_preview_data_bytes": 40_000},  # capped part way
        {"max_entries": 7},
        {"after": "d1/o02_boxA.SLDPRT"},
        {"formats": "all"},
    ],
    ids=["default", "images", "capped", "max_entries", "after", "all_formats"],
)
def test_a_listing_read_in_threads_is_the_listing_read_one_file_at_a_time(tmp_path, options):
    folder = _copies(tmp_path)
    one = _listed(folder, **options)
    many = _listed(folder, threads=8, **options)
    assert many == one
    assert len(one[0]) >= 7  # max_entries lists 7; the others list the whole tree


def test_threads_is_checked_and_a_stopped_threaded_listing_leaves_no_thread_waiting(tmp_path):
    import threading

    for bad in (0, 33, True, 2.0):
        with pytest.raises(InvalidArgumentError):
            scan(tmp_path, threads=bad)
    folder = _copies(tmp_path)
    it = iter(scan(folder, recursive=True, threads=4))
    next(it)
    it.close()  # the caller stops early, as the viewer's Cancel does
    deadline = time.monotonic() + 10
    while any(t.name.startswith("solidseas-listing") for t in threading.enumerate()):
        assert time.monotonic() < deadline, "a listing thread kept running"
        time.sleep(0.05)
