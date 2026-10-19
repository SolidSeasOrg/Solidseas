"""Fake directory entries for the folder walker (``solidseas.walk._scandir``).

Deduplicated files, cloud files and placeholders cannot be made on a local disk,
so tests describe them as entries whose ``stat()`` carries the attributes and
reparse tag a real listing would. :class:`PosixEntry` does the same for what a
Linux listing reports (FIFOs, sockets, devices, other filesystems), so those
rules run on every operating system.
"""

import os
import stat

from solidseas import walk as walk_mod

ARCHIVE, DIRECTORY, REPARSE = 0x20, 0x10, 0x400
MTIME = 1_790_292_487_123_456_789


class FakeStat:
    def __init__(self, attrs: int, tag: int = 0, size: int = 0) -> None:
        self.st_file_attributes = attrs
        self.st_reparse_tag = tag
        self.st_size = size
        self.st_mtime_ns = MTIME
        self.st_mode = 0o040777 if attrs & DIRECTORY else 0o100666


class FakeEntry:
    def __init__(self, name: str, attrs: int, tag: int = 0, size: int = 0, *, fails: bool = False) -> None:
        self.name = name
        self._stat = FakeStat(attrs, tag, size)
        self._fails = fails

    def stat(self, follow_symlinks: bool = True):
        assert follow_symlinks is False, "the walker must never follow a link to read details"
        if self._fails:
            raise FileNotFoundError(2, "vanished")
        return self._stat

    def is_symlink(self) -> bool:
        return False

    def is_junction(self) -> bool:
        return False


class PosixStat:
    """What ``lstat`` gives on Linux and macOS: a mode and a device, no Windows attributes."""

    def __init__(self, mode: int, dev: int, size: int = 0) -> None:
        self.st_mode = mode
        self.st_dev = dev
        self.st_size = size
        self.st_mtime_ns = MTIME


class PosixEntry:
    """A Linux or macOS directory entry: a FIFO, socket, device, mount point or ordinary entry."""

    def __init__(self, name: str, mode: int, dev: int, size: int = 0) -> None:
        self.name = name
        self._stat = PosixStat(mode, dev, size)

    def stat(self, follow_symlinks: bool = True):
        assert follow_symlinks is False, "the walker must never follow a link to read details"
        return self._stat

    def is_symlink(self) -> bool:
        return stat.S_ISLNK(self._stat.st_mode)

    def is_junction(self) -> bool:
        return False


class FakeDir:
    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, *exc):
        return False


def fake_tree(monkeypatch, root, tree: dict[str, list]):
    """Serve ``tree`` (relative folder -> entries) through walk._scandir; return the folders listed."""
    listed: list[str] = []

    def scandir(path):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        rel = "" if rel == "." else rel
        listed.append(rel)
        if rel not in tree:
            raise AssertionError(f"the walker listed {rel!r}, which it must not enter")
        value = tree[rel]
        if isinstance(value, BaseException):
            raise value
        return FakeDir(value)

    monkeypatch.setattr(walk_mod, "_scandir", scandir)
    return listed
