"""SolidSeas' own snapshots (solidseas.versions.snapstore): where they may be written,
that nothing is ever written beside the source or through a link, that what is read
back is checked, and the history and comparison they give a file outside Git."""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from solidseas import model, versions
from solidseas.errors import (
    BusyError,
    LinkRefusedError,
    PathRefusedError,
    VersionNotFoundError,
    VersionUnavailableError,
)
from solidseas.versions import snapstore

POSIX = os.name != "nt"


def content(n: int) -> bytes:
    return bytes(range(256)) * 50 + f"version {n}".encode()


def listing(folder: Path) -> dict[str, tuple[int, bytes]]:
    return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(folder.iterdir())}


@pytest.fixture
def source(tmp_path) -> Path:
    folder = tmp_path / "jobs"
    folder.mkdir()
    path = folder / "bracket.bin"
    path.write_bytes(content(1))
    return path


def test_the_default_store_is_in_the_users_data_folder_never_beside_the_file(source):
    before = listing(source.parent)
    data = versions.snapshot(source, note="first")
    assert data["new"] and data["versions"] == 1 and data["store"]["location"] == "data"
    store = Path(snapstore.data_dir()) / "history"
    assert data["store"]["path"] == str(store) and store.is_dir()
    assert Path(snapstore.data_dir()) == Path(os.environ["SOLIDSEAS_DATA_DIR"])  # conftest's, not the user's
    assert listing(source.parent) == before  # nothing beside the source
    snap = data["snapshot"]
    assert snap["kind"] == "snapshot" and snap["number"] == 1 and snap["subject"] == "first"
    assert snap["sha256"] == hashlib.sha256(content(1)).hexdigest() and snap["size"] == len(content(1))
    obj = store / "objects" / snap["sha256"][:2] / snap["sha256"]
    assert obj.read_bytes() == content(1)
    assert model.dumps(model.envelope("snapshot_taken", data))


def test_an_unchanged_file_stores_nothing_new_and_a_changed_one_does(source):
    first = versions.snapshot(source)
    again = versions.snapshot(source)
    assert again["new"] is False and again["snapshot"]["id"] == first["snapshot"]["id"]
    source.write_bytes(content(2))
    second = versions.snapshot(source, note="taller")
    assert second["new"] and second["snapshot"]["number"] == 2 and second["versions"] == 2
    data = versions.history(source)
    assert data["source"] == "snapshots" and data["working"]["state"] == "unchanged"
    assert [v["number"] for v in data["versions"]] == [2, 1]
    assert [v["subject"] for v in data["versions"]] == ["taller", None]
    source.write_bytes(content(3))
    data = versions.history(source)
    assert data["working"]["state"] == "changed" and data["versions"][0]["kind"] == "working"
    assert versions.read_version(source, "v1") == content(1)
    assert versions.read_version(source, second["snapshot"]["id"][:6]) == content(2)
    assert versions.read_version(source, "working") == content(3)
    # the same content again later is a new snapshot: the history says when it came back
    source.write_bytes(content(1))
    assert versions.snapshot(source)["new"] and len(versions.history(source)["versions"]) == 3


def test_a_file_with_no_snapshot_has_only_a_working_copy(source):
    data = versions.history(source)
    assert data["working"]["state"] == "new" and [v["kind"] for v in data["versions"]] == ["working"]
    with pytest.raises(VersionNotFoundError):
        versions.compare(source)
    with pytest.raises(VersionNotFoundError):
        versions.read_version(source, "latest")
    with pytest.raises(FileNotFoundError):
        versions.history(source.parent / "nothing.bin")
    with pytest.raises(IsADirectoryError):
        versions.history(source.parent)


def test_a_projects_store_only_when_named_and_it_moves_with_the_project(tmp_path):
    project = tmp_path / "proj"
    (project / "parts").mkdir(parents=True)
    path = project / "parts" / "bracket.bin"
    path.write_bytes(content(1))
    versions.snapshot(path)
    assert not (project / ".solidseas").exists()  # the default never writes into the project
    data = versions.snapshot(path, project=project)
    assert data["store"] == {"location": "project", "path": str(project / ".solidseas" / "history")}
    record = next((project / ".solidseas" / "history" / "files").rglob("*.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["path"] == "parts/bracket.bin"
    moved = tmp_path / "moved"
    project.rename(moved)
    data = versions.history(moved / "parts" / "bracket.bin", project=moved)
    assert len(data["versions"]) == 1 and data["working"]["state"] == "unchanged"
    outside = tmp_path / "other.bin"
    outside.write_bytes(content(2))
    with pytest.raises(PathRefusedError) as err:
        versions.snapshot(outside, project=moved)
    assert err.value.detail["rule"] == "outside_project"
    with pytest.raises(Exception) as err:
        versions.snapshot(outside, project=moved, store=tmp_path / "s")
    assert model.error_code(err.value) == "invalid_argument"


def test_a_store_named_by_folder(source, tmp_path):
    store = tmp_path / "stores" / "mine"
    data = versions.snapshot(source, store=store)
    assert data["store"] == {"location": "folder", "path": str(store)}
    assert versions.history(source, store=store)["versions"][0]["kind"] == "snapshot"
    assert versions.history(source)["working"]["state"] == "new"  # the user's own store has none


@pytest.mark.skipif(not POSIX, reason="file modes and symbolic links")
def test_the_store_is_private_and_never_written_through_a_link(source, tmp_path):
    store = tmp_path / "store"
    versions.snapshot(source, store=store)
    for p in [store, *store.rglob("*")]:
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == (0o700 if p.is_dir() else 0o600), (p, oct(mode))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # the store's folder, a folder in it, and a project's .solidseas folder as links
    linked = tmp_path / "linked-store"
    linked.symlink_to(elsewhere)
    with pytest.raises(LinkRefusedError):
        versions.snapshot(source, store=linked)
    with pytest.raises(LinkRefusedError):
        versions.history(source, store=linked)
    source.write_bytes(content(5))
    objects = store / "objects"
    for child in objects.iterdir():
        for f in child.iterdir():
            f.unlink()
        child.rmdir()
    objects.rmdir()
    objects.symlink_to(elsewhere)
    with pytest.raises(LinkRefusedError):
        versions.snapshot(source, store=store)
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".solidseas").symlink_to(elsewhere)
    inside = project / "p.bin"
    inside.write_bytes(content(1))
    with pytest.raises(LinkRefusedError):
        versions.snapshot(inside, project=project)
    assert list(elsewhere.iterdir()) == []  # nothing went through any of them
    # a source that is a link is not copied
    target = tmp_path / "real.bin"
    target.write_bytes(content(1))
    link = source.parent / "link.bin"
    link.symlink_to(target)
    with pytest.raises(LinkRefusedError):
        versions.snapshot(link, store=tmp_path / "s2")


@pytest.mark.skipif(not POSIX, reason="symbolic links")
def test_a_link_planted_where_an_object_goes_is_refused(source, tmp_path):
    store = tmp_path / "store"
    sha = hashlib.sha256(content(1)).hexdigest()
    folder = store / "objects" / sha[:2]
    folder.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep me")
    (folder / sha).symlink_to(victim)
    with pytest.raises(LinkRefusedError):
        versions.snapshot(source, store=store)
    assert victim.read_bytes() == b"keep me"
    assert not any(p.name.startswith(".tmp-") for p in (store / "objects").iterdir())


def test_a_wrong_file_planted_where_an_object_goes_is_replaced(source, tmp_path):
    store = tmp_path / "store"
    sha = hashlib.sha256(content(1)).hexdigest()
    folder = store / "objects" / sha[:2]
    folder.mkdir(parents=True)
    (folder / sha).write_bytes(b"x" * len(content(1)))  # the right name and size, other content
    assert versions.snapshot(source, store=store)["new"]
    assert (folder / sha).read_bytes() == content(1)
    assert versions.read_version(source, "v1", store=store) == content(1)


def test_what_is_read_back_is_checked(source, tmp_path):
    store = tmp_path / "store"
    data = versions.snapshot(source, store=store)
    sha = data["snapshot"]["sha256"]
    obj = store / "objects" / sha[:2] / sha
    obj.chmod(0o600)
    obj.write_bytes(content(1)[:-1] + b"!")  # the same size, other bytes
    with pytest.raises(snapstore.SnapshotDamagedError) as err:
        versions.read_version(source, "v1", store=store)
    info = model.error_info(err.value)
    assert (
        info["code"] == "damaged_file"
        and info["message"] == model.RULE_MESSAGES[("damaged_file", "snapshot_object")]
    )
    obj.unlink()
    listed = versions.history(source, store=store)["versions"]
    assert listed[0]["available"] is False
    with pytest.raises(VersionUnavailableError) as err:
        versions.read_version(source, "v1", store=store)
    assert err.value.detail["rule"] == "snapshot_missing"
    # taking the snapshot again puts the missing copy back, with no second record
    again = versions.snapshot(source, store=store)
    assert again["new"] is False and again["versions"] == 1 and obj.read_bytes() == content(1)
    obj.write_bytes(content(1)[:-1] + b"?")  # damaged again, at the same size: repaired the same way
    assert versions.snapshot(source, store=store)["new"] is False and obj.read_bytes() == content(1)
    assert versions.read_version(source, "v1", store=store) == content(1)


def test_records_that_do_not_hold_up_are_passed_over(source, tmp_path):
    store = tmp_path / "store"
    versions.snapshot(source, store=store)
    record = next((store / "files").rglob("*.json"))
    folder = record.parent
    good = json.loads(record.read_text(encoding="utf-8"))

    def plant(name: str, value) -> None:
        text = value if isinstance(value, str) else json.dumps(value)
        (folder / name).write_text(text, encoding="utf-8")

    plant("20260101T000000000000Z-aaaaaaaaaaaa.json", "{not json")
    plant(
        "20260101T000000000001Z-bbbbbbbbbbbb.json",
        {**good, "id": "bbbbbbbbbbbb", "path": "/somewhere/else.bin"},
    )
    plant("20260101T000000000002Z-cccccccccccc.json", {**good, "id": "not the name"})
    plant("20260101T000000000003Z-dddddddddddd.json", {**good, "id": "dddddddddddd", "size": -1})
    plant("20260101T000000000004Z-eeeeeeeeeeee.json", {**good, "id": "eeeeeeeeeeee", "sha256": "../../x"})
    plant("20260101T000000000005Z-ffffffffffff.json", {**good, "id": "ffffffffffff", "v": 99})
    plant("notes.txt", "a file that is not a record")
    data = versions.history(source, store=store)
    assert len(data["versions"]) == 1 and data["versions"][0]["id"] == good["id"]
    assert snapstore.parse_record(record.read_bytes(), record.name).sha256 == good["sha256"]
    assert snapstore.parse_record(b"{}", "x.json") is None


class _Later:
    """A stat result whose modification time is later than the file's by ``bump``."""

    def __init__(self, st, bump: int) -> None:
        self._st, self._bump = st, bump

    def __getattr__(self, name):
        return getattr(self._st, name)

    @property
    def st_mtime_ns(self) -> int:
        return self._st.st_mtime_ns + self._bump


def test_a_file_that_changes_while_it_is_copied_is_not_kept(source, tmp_path, monkeypatch):
    real = os.fstat
    calls = []

    def changing(fd):  # every look at the file finds it saved again since the last
        calls.append(fd)
        return _Later(real(fd), len(calls))

    store = tmp_path / "store"
    monkeypatch.setattr(snapstore.os, "fstat", changing)
    with pytest.raises(BusyError) as err:
        versions.snapshot(source, store=store)
    monkeypatch.undo()
    assert err.value.detail["rule"] == "file_changing"
    assert model.error_info(err.value)["message"] == model.RULE_MESSAGES[("busy", "file_changing")]
    assert [p for p in store.rglob("*") if p.is_file()] == []  # no record, no object, no temporary copy


def test_snapshots_of_two_files_never_mix(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(content(1))
    b.write_bytes(content(1))  # the same content: one object, two histories
    versions.snapshot(a)
    versions.snapshot(b)
    b.write_bytes(content(2))
    versions.snapshot(b)
    assert len(versions.history(a)["versions"]) == 1 and len(versions.history(b)["versions"]) == 2
    objects = Path(snapstore.data_dir()) / "history" / "objects"
    assert sum(1 for p in objects.rglob("*") if p.is_file()) >= 2


def test_bad_arguments(source):
    for kwargs, parameter in (
        ({"note": "x" * 2000}, "note"),
        ({"note": 5}, "note"),
    ):
        with pytest.raises(Exception) as err:
            versions.snapshot(source, **kwargs)
        assert (
            model.error_code(err.value) == "invalid_argument" and err.value.detail["parameter"] == parameter
        )
    for kwargs, parameter in (
        ({"source": "svn"}, "source"),
        ({"max_commits": 0}, "max_commits"),
        ({"max_commits": True}, "max_commits"),
    ):
        with pytest.raises(Exception) as err:
            versions.history(source, **kwargs)
        assert err.value.detail["parameter"] == parameter


@pytest.mark.parametrize("batch", [2, 5])
def test_many_files_at_once_keep_their_order_and_their_errors(source, tmp_path, monkeypatch, batch):
    monkeypatch.setattr(snapstore, "BATCH_FILES", batch)
    other = source.parent / "plate.bin"
    other.write_bytes(content(2))
    store = snapstore.open_store(store=tmp_path / "store")
    missing = source.parent / "gone.bin"
    paths = [str(source), str(missing), str(other), str(source), str(other)]
    results = store.add_many(paths, note="all at once", workers=3)
    first, gone, plate, again, plate_again = results
    assert isinstance(gone, FileNotFoundError)
    assert first[1] and plate[1] and first[0].sha256 != plate[0].sha256
    # a file named twice: stored once, in its own batch or in the same one
    assert again == (first[0], False) and plate_again == (plate[0], False)
    assert [s.id for s in store.snapshots(str(source))] == [first[0].id]
    assert store.read(first[0], limit=1 << 20) == content(1) and first[0].note == "all at once"
    assert not any(p.name.startswith(".tmp-") for p in (tmp_path / "store" / "objects").iterdir())


def count_temps(monkeypatch) -> list[str]:
    """Spy on the temporary copies the store writes: the list fills with their paths."""
    made: list[str] = []
    real = snapstore._new_temp

    def spy(objects):
        tmp, out = real(objects)
        made.append(tmp)
        return tmp, out

    monkeypatch.setattr(snapstore, "_new_temp", spy)
    return made


def test_content_the_store_holds_is_read_once_and_not_written_again(source, tmp_path, monkeypatch):
    store = snapstore.open_store(store=tmp_path / "store")
    copy = source.parent / "copy.bin"
    copy.write_bytes(content(1))
    made = count_temps(monkeypatch)
    ((snap, new),) = store.add_many([str(source)])
    assert new and len(made) == 1
    reads = []
    real_intact = snapstore.SnapshotStore._intact
    monkeypatch.setattr(
        snapstore.SnapshotStore,
        "_intact",
        lambda self, sha, size: reads.append(sha) or real_intact(self, sha, size),
    )
    third = source.parent / "third.bin"
    third.write_bytes(content(1))
    results = store.add_many([str(copy), str(third)], workers=1)
    assert all(r[1] and r[0].sha256 == snap.sha256 for r in results)
    assert len(made) == 1  # no copy written for content the store holds
    assert reads == [snap.sha256]  # the stored object is checked once per call
    assert store.read(results[0][0], limit=1 << 20) == content(1)


def test_a_damaged_object_is_written_again_when_its_content_comes_back(source, tmp_path, monkeypatch):
    store = snapstore.open_store(store=tmp_path / "store")
    ((snap, _new),) = store.add_many([str(source)])
    obj = Path(store.object_path(snap.sha256))
    obj.write_bytes(b"x" * snap.size)
    copy = source.parent / "copy.bin"
    copy.write_bytes(content(1))
    made = count_temps(monkeypatch)
    ((again, new),) = store.add_many([str(copy)])
    assert new and len(made) == 1 and obj.read_bytes() == content(1)


def test_a_file_larger_than_the_buffer_is_copied_as_it_is_read(source, tmp_path, monkeypatch):
    monkeypatch.setattr(snapstore, "BUFFER_BYTES", 1000)
    monkeypatch.setattr(snapstore, "COPY_CHUNK", 700)
    store = snapstore.open_store(store=tmp_path / "store")
    made = count_temps(monkeypatch)
    ((snap, new),) = store.add_many([str(source)])
    assert new and len(made) == 1 and store.read(snap, limit=1 << 20) == content(1)
    copy = source.parent / "copy.bin"
    copy.write_bytes(content(1))
    ((again, new),) = store.add_many([str(copy)])
    assert new and again.sha256 == snap.sha256 and len(made) == 2  # copied, then dropped
    assert not any(p.name.startswith(".tmp-") for p in (tmp_path / "store" / "objects").iterdir())


def test_temporary_copies_a_crash_left_are_cleared(source, tmp_path):
    store = snapstore.open_store(store=tmp_path / "store")
    store.add(str(source))
    objects = tmp_path / "store" / "objects"
    old, young = objects / ".tmp-0123456789abcdef", objects / ".tmp-fedcba9876543210"
    other = objects / ".tmp-notours"
    for p in (old, young, other):
        p.write_bytes(b"left over")
    day_ago = old.stat().st_mtime - snapstore.STALE_TEMP_SECONDS - 60
    os.utime(old, (day_ago, day_ago))
    os.utime(other, (day_ago, day_ago))
    plate = source.parent / "plate.bin"
    plate.write_bytes(content(2))
    store.add(str(plate))
    assert not old.exists()
    assert young.exists() and other.exists()  # one a running copy could own, and a name not ours
    assert (
        snapstore._clear_stale_temps(str(objects), now=young.stat().st_mtime + snapstore.STALE_TEMP_SECONDS)
        == 1
    )
    assert not young.exists() and other.exists()
