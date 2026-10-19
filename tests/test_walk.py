"""The one folder walker: links decided by reparse tag, placeholders never entered,
lock files skipped, bounds, and a real junction that leads out of the root.

Deduplicated files, cloud files and placeholders cannot be made on a local disk,
so the tag table runs on fake directory entries handed to the walker through
``walk._scandir``. Junctions and symbolic links are made for real.
"""

import os
import shutil
import stat
import time

import pytest

from fakefs import ARCHIVE, DIRECTORY, MTIME, REPARSE, FakeEntry, PosixEntry, fake_tree
from solidseas.walk import Walk, classify
from support import fixture_path

WINDOWS = os.name == "nt"
# Reparse tags and attributes, both directions in one table (windows-reparse-tags-not-links).
TAG_TABLE = [
    # name, attributes, tag, expected kind, expected reason, is a folder
    ("dedup.SLDPRT", ARCHIVE | REPARSE, 0x80000013, "file", None, False),
    ("cloud_folder", DIRECTORY | REPARSE, 0x9000701A, "folder", None, True),
    ("junction", DIRECTORY | REPARSE, 0xA0000003, "link", "junction", True),
    ("symlink.SLDPRT", ARCHIVE | REPARSE, 0xA000000C, "link", "symlink", False),
    ("dir_symlink", DIRECTORY | REPARSE, 0xA000000C, "link", "symlink", True),
    ("wsl_link", ARCHIVE | REPARSE, 0xA000001D, "link", "name_surrogate", False),
    ("global_link", DIRECTORY | REPARSE, 0xA0000019, "link", "name_surrogate", True),
    ("unreported", DIRECTORY | REPARSE, 0, "link", "unreported_tag", True),
    (
        "online_only.SLDPRT",
        ARCHIVE | REPARSE | 0x400000,
        0x9000601A,
        "placeholder",
        "recall_on_data_access",
        False,
    ),
    ("recall.SLDASM", ARCHIVE | 0x40000, 0, "placeholder", "recall_on_open", False),
    ("offline.SLDDRW", ARCHIVE | 0x1000, 0, "placeholder", "offline", False),
    (
        "cloud_placeholder_folder",
        DIRECTORY | REPARSE | 0x40000,
        0x9000701A,
        "placeholder",
        "recall_on_open",
        True,
    ),
    ("~$part.SLDPRT", ARCHIVE, 0, "skipped", "lock_file", False),
    ("plain.SLDPRT", ARCHIVE, 0, "file", None, False),
    ("sub", DIRECTORY, 0, "folder", None, True),
]


def test_reparse_tag_table(monkeypatch, tmp_path):
    entries = [FakeEntry(name, attrs, tag, size=1234) for name, attrs, tag, *_ in TAG_TABLE]
    listed = fake_tree(monkeypatch, tmp_path, {"": entries, "cloud_folder": [], "sub": []})
    walk = Walk(tmp_path)
    got = {e.rel: e for e in walk}
    assert len(got) == len(TAG_TABLE) == 15  # the table was actually read
    for name, _attrs, _tag, kind, reason, is_dir in TAG_TABLE:
        e = got[name]
        assert (e.kind, e.reason, e.is_dir) == (kind, reason, is_dir), name
    assert got["dedup.SLDPRT"].size == 1234  # a deduplicated file keeps its size
    assert got["online_only.SLDPRT"].size == 1234  # a placeholder is listed with its size
    assert got["junction"].size is None and got["junction"].mtime_ns == MTIME
    # only the two ordinary folders were entered: no link, no placeholder folder
    assert sorted(listed) == ["", "cloud_folder", "sub"]
    s = walk.stats
    assert (s.folders, s.links, s.placeholders, s.skipped, s.files) == (3, 6, 4, 1, 2)
    assert s.truncated is None


def test_posix_fifos_sockets_and_devices_are_skipped_never_files(monkeypatch, tmp_path):
    """Linux reports no Windows attributes; anything not a folder and not a regular file
    is skipped, so nothing ever opens a FIFO (which blocks until a writer appears)."""
    dev = os.stat(tmp_path).st_dev
    entries = [
        PosixEntry("trap.SLDPRT", stat.S_IFIFO | 0o644, dev),
        PosixEntry("sock.SLDASM", stat.S_IFSOCK | 0o755, dev),
        PosixEntry("tty.SLDDRW", stat.S_IFCHR | 0o620, dev),
        PosixEntry("disk.SLDPRT", stat.S_IFBLK | 0o660, dev),
        PosixEntry("part.SLDPRT", stat.S_IFREG | 0o644, dev, size=99),
        PosixEntry("sub", stat.S_IFDIR | 0o755, dev),
        PosixEntry("ln.SLDPRT", stat.S_IFLNK | 0o777, dev),
    ]
    fake_tree(monkeypatch, tmp_path, {"": entries, "sub": []})
    walk = Walk(tmp_path)
    got = {e.rel: (e.kind, e.reason, e.size) for e in walk}
    assert got == {
        "trap.SLDPRT": ("skipped", "not_regular_file", None),
        "sock.SLDASM": ("skipped", "not_regular_file", None),
        "tty.SLDDRW": ("skipped", "not_regular_file", None),
        "disk.SLDPRT": ("skipped", "not_regular_file", None),
        "part.SLDPRT": ("file", None, 99),
        "sub": ("folder", None, None),
        "ln.SLDPRT": ("link", "symlink", None),
    }
    s = walk.stats
    assert (s.skipped, s.files, s.links, s.folders) == (4, 1, 1, 2)


def test_posix_mount_points_are_links_never_entered(monkeypatch, tmp_path):
    """An entry on another device than the root is another filesystem: a link, as a
    Windows volume mount point (a junction) is. The fake tree fails if "mnt" is listed."""
    dev = os.stat(tmp_path).st_dev
    tree = {
        "": [
            PosixEntry("mnt", stat.S_IFDIR | 0o755, dev + 1),
            PosixEntry("bound.SLDPRT", stat.S_IFREG | 0o644, dev + 1, size=5),
            PosixEntry("same", stat.S_IFDIR | 0o755, dev),
        ],
        "same": [PosixEntry("inner.SLDPRT", stat.S_IFREG | 0o644, dev, size=7)],
    }
    listed = fake_tree(monkeypatch, tmp_path, tree)
    walk = Walk(tmp_path)
    got = {e.rel: (e.kind, e.reason, e.is_dir) for e in walk}
    assert got == {
        "bound.SLDPRT": ("link", "mount_point", False),
        "mnt": ("link", "mount_point", True),
        "same": ("folder", None, True),
        "same/inner.SLDPRT": ("file", None, False),
    }
    assert sorted(listed) == ["", "same"] and walk.stats.links == 2
    # Windows listings carry no device number: a Windows-style entry is never a mount point.
    assert classify(FakeEntry("d", DIRECTORY), "x", "", 1, root_dev=dev + 1).kind == "folder"


def test_tag_zero_without_the_reparse_attribute_is_ordinary():
    plain = classify(FakeEntry("a.SLDPRT", ARCHIVE, 0), "x", "", 1)
    assert plain.kind == "file"


def test_python_link_flags_count_even_without_a_tag(tmp_path):
    class Linky(FakeEntry):
        def is_symlink(self):
            return True

    class Junctiony(FakeEntry):
        def is_junction(self):
            return True

    assert classify(Linky("l", ARCHIVE), "x", "", 1).reason == "symlink"
    assert classify(Junctiony("j", DIRECTORY), "x", "", 1).kind == "link"


def test_entries_are_sorted_case_folded_and_breadth_first(monkeypatch, tmp_path):
    tree = {
        "": [FakeEntry("b", DIRECTORY), FakeEntry("A.sldprt", ARCHIVE), FakeEntry("a", DIRECTORY)],
        "a": [FakeEntry("deep", DIRECTORY)],
        "b": [FakeEntry("x.SLDPRT", ARCHIVE)],
        "a/deep": [FakeEntry("y.SLDPRT", ARCHIVE)],
    }
    fake_tree(monkeypatch, tmp_path, tree)
    assert [e.rel for e in Walk(tmp_path)] == [
        "a",
        "A.sldprt",
        "b",
        "a/deep",
        "b/x.SLDPRT",
        "a/deep/y.SLDPRT",
    ]


def test_depth_limit_and_non_recursive(monkeypatch, tmp_path):
    tree = {
        "": [FakeEntry("a", DIRECTORY), FakeEntry("top.SLDPRT", ARCHIVE)],
        "a": [FakeEntry("b", DIRECTORY), FakeEntry("mid.SLDPRT", ARCHIVE)],
    }
    listed = fake_tree(monkeypatch, tmp_path, tree)
    walk = Walk(tmp_path, max_depth=2)
    entries = {e.rel: e for e in walk}
    assert entries["a/b"].reason == "max_depth" and "a/b" not in listed
    assert walk.stats.depth_limited == 1 and max(e.depth for e in entries.values()) == 2
    listed.clear()
    flat = Walk(tmp_path, recursive=False)
    assert [e.rel for e in flat] == ["a", "top.SLDPRT"] and listed == [""]
    assert flat.stats.depth_limited == 0


def test_entry_and_time_bounds(monkeypatch, tmp_path):
    tree = {"": [FakeEntry(f"f{i:02}.SLDPRT", ARCHIVE) for i in range(20)]}
    fake_tree(monkeypatch, tmp_path, tree)
    walk = Walk(tmp_path, max_examined=5)
    assert len(list(walk)) == 5 and walk.stats.truncated == "max_examined"
    late = Walk(tmp_path, deadline=time.monotonic() - 1)
    assert list(late) == [] and late.stats.truncated == "deadline"
    whole = Walk(tmp_path)
    assert len(list(whole)) == 20 and whole.stats.truncated is None


def test_unreadable_folders_and_entries_do_not_stop_the_walk(monkeypatch, tmp_path):
    tree = {
        "": [
            FakeEntry("denied", DIRECTORY),
            FakeEntry("gone.SLDPRT", ARCHIVE, fails=True),
            FakeEntry("ok", DIRECTORY),
        ],
        "denied": PermissionError(13, "Access is denied"),
        "ok": [FakeEntry("part.SLDPRT", ARCHIVE)],
    }
    fake_tree(monkeypatch, tmp_path, tree)
    walk = Walk(tmp_path)
    entries = {e.rel: e for e in walk}
    assert entries["gone.SLDPRT"].kind == "error" and isinstance(
        entries["gone.SLDPRT"].error, FileNotFoundError
    )
    denied = [e for e in entries.values() if e.kind == "error" and e.is_dir]
    assert [e.rel for e in denied] == ["denied"] and isinstance(denied[0].error, PermissionError)
    assert entries["ok/part.SLDPRT"].kind == "file"
    assert walk.stats.errors == 2 and walk.stats.folders == 2


def test_the_root_itself_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Walk(tmp_path / "missing")
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(NotADirectoryError):
        Walk(tmp_path / "file.txt")


def test_a_walk_runs_once(tmp_path):
    walk = Walk(tmp_path)
    list(walk)
    with pytest.raises(RuntimeError):
        list(walk)


# --------------------------------------------------------------------------- real links
def _outside_with_a_document(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), outside / "secret.SLDPRT")
    shutil.copyfile(fixture_path("o07_boxB_h31.SLDPRT"), root / "inside.SLDPRT")
    return root, outside


@pytest.mark.skipif(not WINDOWS, reason="directory junctions")
def test_a_real_junction_out_of_the_root_is_never_followed(tmp_path):
    import _winapi

    root, outside = _outside_with_a_document(tmp_path)
    junction = root / "jn"
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        # Control: the junction really leads out of the root, to a SOLIDWORKS document.
        assert (junction / "secret.SLDPRT").is_file()
        assert os.path.commonpath([os.path.realpath(junction), str(root.resolve())]) != str(root.resolve())
        walk = Walk(root)
        entries = {e.rel: e for e in walk}
        assert entries["jn"].kind == "link" and entries["jn"].reason == "junction" and entries["jn"].is_dir
        assert set(entries) == {"jn", "inside.SLDPRT"}
        assert not any("secret" in e.rel for e in entries.values())
        assert walk.stats.links == 1 and walk.stats.folders == 1
    finally:
        os.rmdir(junction)
    assert (outside / "secret.SLDPRT").is_file()  # removing the junction left the target alone


def test_a_real_symbolic_link_is_never_followed(tmp_path):
    root, outside = _outside_with_a_document(tmp_path)
    try:
        os.symlink(outside, root / "ln", target_is_directory=True)
        os.symlink(outside / "secret.SLDPRT", root / "secret_link.SLDPRT")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links need extra rights here")
    assert (root / "ln" / "secret.SLDPRT").is_file()  # control: the link leads out
    entries = {e.rel: e for e in Walk(root)}
    assert entries["ln"].kind == "link" and entries["secret_link.SLDPRT"].kind == "link"
    assert set(entries) == {"ln", "secret_link.SLDPRT", "inside.SLDPRT"}


@pytest.mark.skipif(not WINDOWS, reason="directory junctions")
def test_a_junction_root_is_accepted(tmp_path):
    import _winapi

    root, outside = _outside_with_a_document(tmp_path)
    alias = tmp_path / "alias"
    _winapi.CreateJunction(str(outside), str(alias))
    try:
        assert [e.rel for e in Walk(alias)] == ["secret.SLDPRT"]  # a root is configuration (C6)
    finally:
        os.rmdir(alias)
