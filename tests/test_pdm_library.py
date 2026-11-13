"""The PDM's common-parts library (``docs/PDM.md`` 6) on temporary folders and synthetic
files: candidates, add, list, use, updates and update, the records they write, and
``solidseas pdm library`` printing one strict JSON document per action."""

import json
import os
import sys
import time

import pytest

from jsonschema_subset import validate
from solidseas import cli, model, pdm
from solidseas.errors import InvalidArgumentError, LinkRefusedError, OutputRefusedError
from solidseas.pdm.library import parse_item, parse_link, valid_item_id


def write(path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def bump(path, seconds: float = 2.0) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "CAD"
    write(root / "Jobs" / "1042" / "bolt.sldprt", "bolt one")
    write(root / "Jobs" / "1042" / "bracket.sldprt", "bracket")
    write(root / "Jobs" / "1043" / "sub" / "bolt.sldprt", "bolt one")  # the same bolt
    write(root / "Jobs" / "1043" / "washer.sldprt", "washer")
    write(root / "Jobs" / "1044" / "bolt copy.sldprt", "bolt one")  # again, under another name
    write(root / "Jobs" / "1044" / "washer.sldprt", "washer")
    write(root / "Jobs" / "1044" / "plate.step", "bolt one")  # not a SOLIDWORKS document
    write(root / "Jobs" / "1044" / "SOLIDWORKS Data" / "hex.sldprt", "hex")  # Toolbox
    write(root / "Jobs" / "1045" / "SOLIDWORKS Data" / "hex.sldprt", "hex")
    write(root / "Jobs" / "1045" / "bracket.sldprt", "bracket, but longer")
    (root / "Library").mkdir()
    pdm.init(root)
    return root


def files_of(folder) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file() and ".solidseas" not in p.parts
    }


# --------------------------------------------------------------------------- candidates
def test_candidates_most_widely_shared_first(lib):
    c = pdm.open(lib).library.candidates()
    rows = [(r["name"], r["projects"], [x["path"] for x in r["copies"]]) for r in c["candidates"]]
    assert rows == [
        (
            "bolt.sldprt",
            3,
            ["Jobs/1042/bolt.sldprt", "Jobs/1043/sub/bolt.sldprt", "Jobs/1044/bolt copy.sldprt"],
        ),
        ("washer.sldprt", 2, ["Jobs/1043/washer.sldprt", "Jobs/1044/washer.sldprt"]),
    ]
    assert c["candidates"][0]["names"] == ["bolt copy.sldprt", "bolt.sldprt"]
    assert c["total"] == 2 and c["documents"] == 7  # the Toolbox parts and the STEP file are left out
    assert c["hashed"] == 5  # only the files that share a size with another


def test_candidates_read_only_files_that_changed_since_their_version(lib, monkeypatch):
    vault = pdm.open(lib)
    vault.scan()
    calls = []
    real = pdm.Vault._hash
    monkeypatch.setattr(pdm.Vault, "_hash", lambda self, full: calls.append(full) or real(self, full))
    c = vault.library.candidates()
    assert c["hashed"] == 0 and calls == [] and c["total"] == 2


def test_candidates_leave_out_what_the_library_holds(lib):
    write(lib / "Library" / "std" / "washer.sldprt", "washer")
    vault = pdm.open(lib)
    assert [r["name"] for r in vault.library.candidates()["candidates"]] == ["bolt.sldprt"]
    assert vault.library.candidates(limit=0)["candidates"] == []


def test_candidates_on_many_files_are_quick(lib, monkeypatch):
    for k in range(3000):
        write(lib / "Jobs" / f"p{k % 30:02d}" / f"part{k:04d}.sldprt", f"{k:05d}")  # one size, all different
    vault = pdm.open(lib)
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", lambda fd: None)
        vault.scan()
    t0 = time.perf_counter()
    c = vault.library.candidates()
    assert c["hashed"] == 0 and c["total"] == 2
    assert time.perf_counter() - t0 < 20  # well under a second on the development VM


# --------------------------------------------------------------------------- add and list
def test_add_copies_into_the_library_and_leaves_the_source(lib):
    vault = pdm.open(lib)
    before = files_of(lib / "Jobs")
    r = vault.library.add(lib / "Jobs" / "1042" / "bolt.sldprt", description="M6 bolt")
    assert r["item"]["item"] == "SS-00001" and r["copied"] and r["item"]["path"] == "Library/bolt.sldprt"
    assert r["item"]["source"] == "Jobs/1042/bolt.sldprt" and r["version"]["number"] == 1
    assert (lib / "Library" / "bolt.sldprt").read_bytes() == b"bolt one"
    assert files_of(lib / "Jobs") == before
    assert r["checkin"]["note"] == "Added to the library as SS-00001: M6 bolt"
    (record,) = (lib / ".solidseas" / "vault" / "library" / "items").iterdir()
    assert record.name == "SS-00001.json"
    item = parse_item(record.read_bytes(), record.name)
    assert (item.id, item.description, item.path) == ("SS-00001", "M6 bolt", "Library/bolt.sldprt")
    # a second item takes the next number; one given is kept
    r2 = vault.library.add(lib / "Jobs" / "1043" / "washer.sldprt")
    r3 = vault.library.add(lib / "Jobs" / "1045" / "bracket.sldprt", item="BR-1")
    assert (r2["item"]["item"], r3["item"]["item"]) == ("SS-00002", "BR-1")
    assert [i.id for i in vault.library.items()] == ["BR-1", "SS-00001", "SS-00002"]


def test_add_refuses_what_it_would_replace_or_repeat(lib):
    vault = pdm.open(lib)
    vault.library.add(lib / "Jobs" / "1042" / "bolt.sldprt", item="B1")
    with pytest.raises(OutputRefusedError) as e:  # Library/bolt.sldprt is there now
        vault.library.add(lib / "Jobs" / "1043" / "sub" / "bolt.sldprt")
    assert e.value.detail["rule"] == "exists"
    with pytest.raises(OutputRefusedError) as e:
        vault.library.add(lib / "Jobs" / "1043" / "washer.sldprt", item="b1")
    assert e.value.detail["rule"] == "item_exists"
    with pytest.raises(OutputRefusedError) as e:
        vault.library.add(lib / "Library" / "bolt.sldprt")
    assert e.value.detail["rule"] == "already_an_item"
    for bad in ("", "../x", "a b", "-x", "x" * 41, "CON", "x."):
        assert not valid_item_id(bad)
        with pytest.raises(InvalidArgumentError):
            vault.library.add(lib / "Jobs" / "1043" / "washer.sldprt", item=bad)
    with pytest.raises(InvalidArgumentError):
        vault.library.add(lib / "Jobs" / "1043" / "washer.sldprt", description="two\nlines")
    write(lib / "Jobs" / "1043" / "notes.txt", "not CAD")
    with pytest.raises(InvalidArgumentError):
        vault.library.add(lib / "Jobs" / "1043" / "notes.txt")
    assert not (lib / "Library" / "washer.sldprt").exists()


def test_a_file_already_in_the_library_section_is_recorded_where_it_is(lib):
    write(lib / "Library" / "std" / "nut.sldprt", "nut")
    vault = pdm.open(lib)
    r = vault.library.add(lib / "Library" / "std" / "nut.sldprt", description="M6 nut")
    assert not r["copied"] and r["item"]["path"] == "Library/std/nut.sldprt" and r["item"]["source"] is None
    (row,) = vault.library.list()["items"]
    assert (row["item"], row["exists"], row["stored"], row["copies"]) == ("SS-00001", True, True, 0)
    assert row["version"]["number"] == 1


# --------------------------------------------------------------------------- use, updates and update
@pytest.fixture
def used(lib):
    vault = pdm.open(lib)
    vault.library.add(lib / "Jobs" / "1042" / "bolt.sldprt", description="M6 bolt")
    write(lib / "Jobs" / "1046" / "asm.sldasm", "assembly")
    r = vault.library.use("ss-00001", lib / "Jobs" / "1046")
    return vault, r


def test_use_copies_the_current_version_and_writes_a_link(lib, used):
    vault, r = used
    dest = lib / "Jobs" / "1046" / "bolt.sldprt"
    assert dest.read_bytes() == b"bolt one" and r["path"] == "Jobs/1046/bolt.sldprt"
    assert r["project"]["path"] == "Jobs/1046" and r["version"]["number"] == 1
    assert r["checkin"]["note"] == "Copied library item SS-00001 v1 into Jobs/1046"
    (link,) = vault.library.links()
    assert (link.item, link.project, link.path, link.how) == ("SS-00001", "Jobs/1046", r["path"], "use")
    assert link.sha256 == link.item_sha256
    r2 = vault.library.use("SS-00001", lib / "Jobs" / "1046" / "asm.sldasm", to="parts/hardware")
    assert (lib / "Jobs" / "1046" / "parts" / "hardware" / "bolt.sldprt").read_bytes() == b"bolt one"
    assert r2["path"] == "Jobs/1046/parts/hardware/bolt.sldprt"
    with pytest.raises(OutputRefusedError) as e:
        vault.library.use("SS-00001", lib / "Jobs" / "1042")  # 1042 has a bolt.sldprt of its own
    assert e.value.detail["rule"] == "exists"
    for bad in ("../x", "/abs", "C:\\x", ".hidden", "a/../../b"):
        with pytest.raises(InvalidArgumentError):
            vault.library.use("SS-00001", lib / "Jobs" / "1043", to=bad)
    with pytest.raises(InvalidArgumentError) as e:
        vault.library.use("SS-99999", lib / "Jobs" / "1043")
    assert e.value.detail["rule"] == "unknown_item"
    with pytest.raises(InvalidArgumentError) as e:
        vault.library.use("SS-00001", lib / "Library")
    assert e.value.detail["rule"] == "not_a_project"
    assert vault.status().counts["new"] == 10  # the copies were checked in; the rest never was


def test_updates_and_update(lib, used):
    vault, _r = used
    vault.library.use("SS-00001", lib / "Jobs" / "1043")  # in 1043's top folder
    assert vault.library.updates()["links"] == []
    assert vault.library.updates()["counts"]["current"] == 2
    write(lib / "Library" / "bolt.sldprt", "bolt two")  # the library part changes
    bump(lib / "Library" / "bolt.sldprt")
    write(lib / "Jobs" / "1043" / "bolt.sldprt", "bolt one, edited in the project")
    up = vault.library.updates()
    rows = {r["project"]: r for r in up["links"]}
    assert set(rows) == {"Jobs/1043", "Jobs/1046"}
    assert rows["Jobs/1046"]["behind"] and rows["Jobs/1046"]["copy"] == "unchanged"
    assert rows["Jobs/1046"]["item_changed"] and rows["Jobs/1046"]["number"] == 1
    assert rows["Jobs/1043"]["copy"] == "edited"
    assert vault.library.updates(lib / "Jobs" / "1046")["scope"] == "Jobs/1046"
    r = vault.library.update(lib / "Jobs" / "1046", "SS-00001")
    assert (lib / "Jobs" / "1046" / "bolt.sldprt").read_bytes() == b"bolt two"
    assert r["version"]["number"] == 2 and r["copies"][0]["written"]
    assert r["copies"][0]["stored_first"]["new"] is False  # it already was a version
    assert r["checkin"]["note"] == "Updated from library item SS-00001 v2"
    with pytest.raises(OutputRefusedError) as e:
        vault.library.update(lib / "Jobs" / "1043", "SS-00001")
    assert e.value.detail["rule"] == "edited"
    assert (lib / "Jobs" / "1043" / "bolt.sldprt").read_bytes() == b"bolt one, edited in the project"
    r = vault.library.update(lib / "Jobs" / "1043", "SS-00001", force=True)
    assert r["copies"][0]["stored_first"]["new"] is True
    assert (lib / "Jobs" / "1043" / "bolt.sldprt").read_bytes() == b"bolt two"
    log = vault.log(lib / "Jobs" / "1043" / "bolt.sldprt")
    assert len([v for v in log["versions"] if v["source"] == "vault"]) == 3  # copy, edit, update
    up = vault.library.updates()
    assert up["links"] == [] and up["counts"]["current"] == 2
    with pytest.raises(InvalidArgumentError) as e:
        vault.library.update(lib / "Jobs" / "1044", "SS-00001")
    assert e.value.detail["rule"] == "not_linked"
    (lib / "Jobs" / "1043" / "bolt.sldprt").unlink()
    assert {r["copy"] for r in vault.library.updates()["links"]} == {"gone"}
    r = vault.library.update(lib / "Jobs" / "1043", "SS-00001")
    assert r["copies"][0]["copy"] == "gone" and not r["copies"][0]["written"]
    assert not (lib / "Jobs" / "1043" / "bolt.sldprt").exists()  # a copy that is gone stays gone


def test_update_never_touches_a_file_it_did_not_copy(lib, used):
    vault, _r = used
    write(lib / "Library" / "bolt.sldprt", "bolt two")
    vault.library.update(lib / "Jobs" / "1046", "SS-00001")
    assert (lib / "Jobs" / "1042" / "bolt.sldprt").read_bytes() == b"bolt one"  # the item's source


def test_malformed_records_are_skipped(lib, used):
    vault, _r = used
    items = lib / ".solidseas" / "vault" / "library" / "items"
    links = lib / ".solidseas" / "vault" / "library" / "links"
    (link,) = links.iterdir()
    good = json.loads(link.read_bytes())
    (items / "SS-00002.json").write_bytes(b"{broken")
    (items / "X.json").write_text(
        json.dumps({**json.loads((items / "SS-00001.json").read_bytes()), "item": "Y"})
    )
    bad = dict(good, path="Jobs/other/bolt.sldprt")  # not inside its project
    (links / "29990101T000000000000Z-ffffffffffff.json").write_text(json.dumps(bad))
    (links / "29990101T000000000000Z-eeeeeeeeeeee.json").write_text(json.dumps(dict(good, how="magic")))
    assert [i.id for i in vault.library.items()] == ["SS-00001"]
    assert [link.id for link in vault.library.links()] == [good["id"]]
    assert parse_link(link.read_bytes(), "20000101T000000000000Z-" + good["id"] + ".json") is None
    assert parse_item(b"[]", "SS-00001.json") is None


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_links_are_never_written_through(lib, used, tmp_path):
    vault, _r = used
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, lib / "Jobs" / "1043" / "linked")
    with pytest.raises(LinkRefusedError):
        vault.library.use("SS-00001", lib / "Jobs" / "1043", to="linked")
    assert list(outside.iterdir()) == []
    os.symlink(outside / "x.sldprt", lib / "Jobs" / "1043" / "bolt.sldprt")
    with pytest.raises(OutputRefusedError):
        vault.library.use("SS-00001", lib / "Jobs" / "1043")
    assert not (outside / "x.sldprt").exists()


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


def test_every_library_action_as_json(capsys, lib):
    code, env = run(capsys, "pdm", "library", "candidates", str(lib))
    data = check(env, "pdm_result")
    assert code == 0 and data["action"] == "library_candidates"
    assert data["library_candidates"]["total"] == 2 and data["status"] is None
    code, env = run(
        capsys, "pdm", "library", "add", str(lib / "Jobs" / "1042" / "bolt.sldprt"), "-d", "M6 bolt"
    )
    data = check(env, "pdm_result")["library_add"]
    assert code == 0 and data["item"]["item"] == "SS-00001"
    code, env = run(capsys, "pdm", "library", "use", "SS-00001", str(lib / "Jobs" / "1043"), "--to", "hw")
    data = check(env, "pdm_result")["library_use"]
    assert code == 0 and data["path"] == "Jobs/1043/hw/bolt.sldprt"
    code, env = run(capsys, "pdm", "library", "list", str(lib))
    data = check(env, "pdm_result")["library_list"]
    assert code == 0 and data["items"][0]["copies"] == 1
    write(lib / "Library" / "bolt.sldprt", "bolt two")
    code, env = run(capsys, "pdm", "library", "updates", str(lib))
    data = check(env, "pdm_result")["library_updates"]
    assert code == 0 and [r["behind"] for r in data["links"]] == [True]
    code, env = run(capsys, "pdm", "library", "update", str(lib / "Jobs" / "1043"), "SS-00001")
    data = check(env, "pdm_result")["library_update"]
    assert code == 0 and data["copies"][0]["written"]
    code, env = run(capsys, "pdm", "library", "use", "SS-00001", str(lib / "Jobs" / "1043"), "--to", "hw")
    assert code != 0 and check(env, "error")["code"] == "output_refused"


def test_library_plain_words(capsys, lib):
    assert cli.main(["pdm", "library", "candidates", str(lib)]) == 0
    out = capsys.readouterr().out
    assert "3 projects" in out and "Jobs/1044/bolt copy.sldprt" in out
    assert cli.main(["pdm", "library", "add", str(lib / "Jobs" / "1042" / "bolt.sldprt"), "-d", "M6"]) == 0
    assert "SS-00001" in capsys.readouterr().out
    assert cli.main(["pdm", "library", "use", "SS-00001", str(lib / "Jobs" / "1043")]) == 0
    assert "copied SS-00001 v1 to Jobs/1043/bolt.sldprt" in capsys.readouterr().out
    assert cli.main(["pdm", "library", "list", str(lib)]) == 0
    assert "SS-00001" in capsys.readouterr().out
    assert cli.main(["pdm", "library", "updates", str(lib)]) == 0
    assert "every copy is up to date" in capsys.readouterr().out
