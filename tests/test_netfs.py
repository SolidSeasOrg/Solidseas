"""Network file systems on Linux and macOS, from the mount table alone (solidseas.netfs):
the catalog, reads outside the roots and 3D Print treat them as Windows treats a share
or a mapped network drive."""

import ctypes
import os
import struct
import sys

import pytest

from solidseas import netfs

# Lines as /proc/self/mountinfo writes them: optional fields before the "-", a space in
# a mount point written as \040, and one line too short to read.
MOUNTINFO = "\n".join(
    [
        "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw",
        "30 22 0:26 / /mnt/share rw,relatime shared:5 - nfs4 server:/export rw,vers=4.2",
        "31 22 0:27 / /mnt/share2 rw,relatime - ext4 /dev/sdb1 rw",
        "32 22 0:28 / /mnt/team\\040drive rw,relatime - cifs //server/team rw",
        "33 30 0:29 / /mnt/share/local rw - tmpfs tmpfs rw",
        "34 22 0:30 / /srv/work/remote rw,nosuid shared:9 master:3 - fuse.sshfs user@server: rw",
        "35 22 0:31 / /mnt/over rw - nfs server:/a rw",
        "36 22 0:32 / /mnt/over rw - ext4 /dev/sdc1 rw",
        "garbage line",
    ]
)
TABLE = netfs.parse_mountinfo(MOUNTINFO)


def test_the_mount_table_is_read_as_the_kernel_writes_it():
    assert TABLE[:4] == [
        ("/", "ext4"),
        ("/mnt/share", "nfs4"),
        ("/mnt/share2", "ext4"),
        ("/mnt/team drive", "cifs"),
    ]
    assert len(TABLE) == 8  # the line that does not read as a mount is passed over


@pytest.mark.parametrize(
    ("path", "network"),
    [
        ("/mnt/share", True),
        ("/mnt/share/jobs/bracket.SLDPRT", True),
        ("/mnt/share2/jobs", False),  # the text begins alike, but it is another mount
        ("/mnt/team drive/jobs", True),
        ("/mnt/share/local/x", False),  # a local file system mounted inside the share
        ("/srv/work/remote/parts", True),
        ("/srv/work/parts", False),
        ("/mnt/over/x", False),  # a later mount on the same point hides the earlier
        ("/", False),
    ],
)
def test_a_path_is_on_the_longest_mount_its_text_begins_with(path, network):
    assert netfs.is_network(path, TABLE) is network


def test_nothing_is_known_without_a_mount_table(monkeypatch, tmp_path):
    monkeypatch.setattr(netfs.sys, "platform", "linux")
    monkeypatch.setattr(netfs, "MOUNTINFO", str(tmp_path / "missing"))
    monkeypatch.setattr(netfs, "_cache", None)
    assert netfs.mount_table() == [] and not netfs.is_network("/mnt/share")
    assert netfs.mount_type("/anywhere", []) is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the mount table is Linux's")
def test_this_machine_s_own_table_reads(monkeypatch):
    monkeypatch.setattr(netfs, "_cache", None)
    table = netfs.mount_table()
    assert table and any(point == "/" for point, _t in table)
    assert netfs.mount_type(os.getcwd()) is not None


def test_the_table_is_read_again_only_after_a_while(monkeypatch, tmp_path):
    info = tmp_path / "mountinfo"
    info.write_text(MOUNTINFO)
    monkeypatch.setattr(netfs.sys, "platform", "linux")
    monkeypatch.setattr(netfs, "MOUNTINFO", str(info))
    monkeypatch.setattr(netfs, "_cache", None)
    first = netfs.mount_table()
    info.write_text("")
    assert netfs.mount_table() is first  # within CACHE_S: not read again
    monkeypatch.setattr(netfs, "CACHE_S", 0.0)
    assert netfs.mount_table() == []


# macOS's struct statfs with 64-bit inodes, field by field, packed without padding: the
# offsets netfs reads from must fall where this puts them.
STATFS = "<Ii5Q2iIIII16s1024s1024sI7I"


def statfs(point: str, fstype: str, flags: int) -> bytes:
    return struct.pack(
        STATFS, 4096, 1 << 20, 1, 2, 3, 4, 5, 7, 8, 501, 26, flags, 0,
        fstype.encode(), point.encode(), b"//user@server/share", 0, *([0] * 7),
    )  # fmt: skip


LOCAL = netfs.MNT_LOCAL | 0x1  # local, and read-only as the system volume is
STATFS_RECORDS = [
    statfs("/", "apfs", LOCAL),
    statfs("/dev", "devfs", netfs.MNT_LOCAL),
    statfs("/System/Volumes/Data", "apfs", netfs.MNT_LOCAL),
    statfs("/System/Volumes/Data/home", "autofs", 0),
    statfs("/Volumes/Team Share", "smbfs", 0),
    statfs("/Volumes/Team Share/scratch", "apfs", netfs.MNT_LOCAL),  # a disk image inside it
    statfs("/Volumes/Old", "afpfs", 0),
    statfs("/Volumes/remote", "macfuse", 0),  # sshfs through macFUSE: only the flag says so
    statfs("/Volumes/Odd", "nfs", netfs.MNT_LOCAL),  # a network type is one, whatever its flags
    b"\0" * netfs.STATFS_SIZE,  # not a mount: passed over
]


def test_the_statfs_layout_is_the_64_bit_inode_one():
    assert struct.calcsize(STATFS) == netfs.STATFS_SIZE == 2168


def test_what_getfsstat_writes_is_read_as_mounts():
    mounts = netfs.parse_statfs(b"".join(STATFS_RECORDS) + b"\0" * 100)  # and a short tail
    assert mounts[0] == ("/", "apfs", LOCAL)
    assert mounts[4] == ("/Volumes/Team Share", "smbfs", 0)
    assert len(mounts) == len(STATFS_RECORDS) - 1


@pytest.mark.parametrize(
    ("fstype", "flags", "network"),
    [
        ("apfs", netfs.MNT_LOCAL, False),
        ("hfs", netfs.MNT_LOCAL, False),
        ("smbfs", 0, True),
        ("nfs", 0, True),
        ("afpfs", 0, True),
        ("webdav", 0, True),
        ("ftp", 0, True),
        ("cifs", 0, True),
        ("nfs", netfs.MNT_LOCAL, True),
        ("macfuse", 0, True),
        ("macfuse", netfs.MNT_LOCAL, False),  # mounted with -o local
        ("autofs", 0, False),
        ("devfs", 0, False),
        ("ext4", None, False),  # Linux gives no flags: only the type decides
        ("fuse.sshfs", None, True),
    ],
)
def test_a_mount_is_a_network_one_by_its_type_or_its_missing_local_flag(fstype, flags, network):
    assert netfs.network_mount(fstype, flags) is network


class FakeGetfsstat:
    """getfsstat as libc answers it: the count without a buffer, else as many records as
    fit, and the number written. ``hidden`` records appear only once a buffer is given,
    as mounts made between the two calls do."""

    def __init__(self, records, hidden=0):
        self.records, self.hidden, self.calls = records, hidden, []

    def __call__(self, buf, size, flags):
        self.calls.append((buf is None, size, flags))
        if buf is None:
            return len(self.records) - self.hidden
        n = min(len(self.records), size // netfs.STATFS_SIZE)
        ctypes.memmove(buf, b"".join(self.records[:n]), n * netfs.STATFS_SIZE)
        return n


class FakeLibc:
    def __init__(self, **symbols):
        self.__dict__.update({name.replace("_INODE64", "$INODE64"): f for name, f in symbols.items()})


@pytest.mark.parametrize(
    ("machine", "symbol"),
    [("arm64", "getfsstat"), ("x86_64", "getfsstat$INODE64")],
)
def test_the_64_bit_inode_getfsstat_is_called_without_waiting_on_any_share(monkeypatch, machine, symbol):
    monkeypatch.setattr(netfs.platform, "machine", lambda: machine)
    monkeypatch.setattr(netfs.sys, "platform", "darwin")
    fn = FakeGetfsstat(STATFS_RECORDS, hidden=6)
    wrong = FakeGetfsstat([statfs("/wrong", "smbfs", 0)])
    libc = FakeLibc(**{symbol.replace("$INODE64", "_INODE64"): fn})
    if symbol == "getfsstat$INODE64":
        libc.getfsstat = wrong  # the 32-bit inode layout on Intel: never called
    mounts = netfs._read_mounts(libc)
    assert [m[0] for m in mounts][:2] == ["/", "/dev"] and len(mounts) == len(STATFS_RECORDS) - 1
    assert all(flags == netfs.MNT_NOWAIT for _none, _size, flags in fn.calls) and not wrong.calls
    assert len(fn.calls) == 3  # the count, a buffer too small for the mounts made since, a bigger one


def test_getfsstat64_is_the_fallback(monkeypatch):
    monkeypatch.setattr(netfs.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(netfs.sys, "platform", "darwin")
    libc = FakeLibc(getfsstat64=FakeGetfsstat(STATFS_RECORDS[:2]))
    assert netfs._read_mounts(libc) == [("/", "apfs", LOCAL), ("/dev", "devfs", netfs.MNT_LOCAL)]


def broken(*_args):
    raise OSError("no")


@pytest.mark.parametrize(
    "libc",
    [
        FakeLibc(),
        FakeLibc(getfsstat=lambda *a: -1, getfsstat_INODE64=lambda *a: -1),
        FakeLibc(getfsstat=broken),
    ],
)
def test_a_getfsstat_that_fails_tells_nothing(monkeypatch, libc):
    monkeypatch.setattr(netfs.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(netfs.sys, "platform", "darwin")
    assert netfs._read_mounts(libc) == []
    read = netfs._read_mounts
    monkeypatch.setattr(netfs, "_read_mounts", lambda: read(libc))
    monkeypatch.setattr(netfs, "_cache", None)
    assert not netfs.is_network("/Volumes/Team Share") and not netfs.readable()


@pytest.mark.parametrize(
    ("path", "network"),
    [
        ("/Volumes/Team Share/jobs/bracket.SLDPRT", True),
        ("/volumes/team share/jobs", True),  # macOS compares names without regard to case
        ("/Volumes/Team Share/scratch/x", False),
        ("/Volumes/Team Shares/x", False),
        ("/Volumes/Old/a", True),
        ("/Volumes/remote/parts", True),
        ("/Volumes/Odd", True),
        ("/System/Volumes/Data/home/someone", False),
        ("/Users/someone/parts", False),
        ("/", False),
    ],
)
def test_a_path_on_macos_is_on_the_mount_getfsstat_names(monkeypatch, path, network):
    mounts = netfs.parse_statfs(b"".join(STATFS_RECORDS))
    monkeypatch.setattr(netfs.sys, "platform", "darwin")
    monkeypatch.setattr(netfs, "_read_mounts", lambda: mounts)
    monkeypatch.setattr(netfs, "_cache", None)
    assert netfs.is_network(path) is network
    assert netfs.readable() and ("/Volumes/Old", "afpfs") in netfs.mount_table()
    assert netfs.mount_type("/VOLUMES/OLD/x") == "afpfs"


@pytest.mark.skipif(sys.platform != "darwin", reason="getfsstat is macOS's")
def test_this_mac_s_own_mounts_read(monkeypatch):
    monkeypatch.setattr(netfs, "_cache", None)
    mounts = netfs._read_mounts()
    assert any(point == "/" for point, _t, _f in mounts) and netfs.readable()
    assert all(isinstance(flags, int) for _p, _t, flags in mounts)
    assert netfs.mount_type("/") and not netfs.is_network("/")


@pytest.fixture
def shares(monkeypatch):
    """This machine's mount table, with /mnt/share an NFS mount, on any system."""
    monkeypatch.setattr(netfs, "mount_table", lambda: TABLE)
    monkeypatch.setattr(netfs.sys, "platform", "linux")


@pytest.mark.skipif(os.name == "nt", reason="Windows decides by drive letters and UNC paths")
def test_the_catalog_is_never_kept_on_a_network_mount(shares):
    from solidseas import catalog
    from solidseas.catalog import store
    from solidseas.errors import PathRefusedError

    assert store.is_network("/mnt/share/jobs") and not store.is_network("/srv/work/jobs")
    with pytest.raises(PathRefusedError) as err:
        catalog.open("/mnt/share/jobs", location="project")
    assert err.value.detail["rule"] == "network_location"


@pytest.mark.skipif(os.name == "nt", reason="Windows decides by drive letters and UNC paths")
def test_reads_outside_the_roots_never_touch_a_network_mount(shares):
    from solidseas.resolve import Gateway
    from solidseas.resolve.names import host_split

    g = Gateway(allow_outside_roots=True)
    assert g.anchor_class(host_split("/mnt/share/jobs/a.SLDPRT")) == "network_drive"
    assert g.anchor_class(host_split("/srv/work/a.SLDPRT")) == "local"
    assert g.point_lookup(host_split("/mnt/share/jobs/a.SLDPRT")) == "network_drive"
    assert g.calls[-1] == ("point", "/mnt/share/jobs/a.SLDPRT", "refused:network_drive")


@pytest.mark.skipif(os.name == "nt", reason="Windows decides by drive letters and UNC paths")
def test_a_print_never_goes_into_a_network_mount_outside_the_opened_folder(shares):
    from solidseas_app.viewer import printing

    assert not printing._local("/mnt/share/jobs") and printing._local("/srv/work/jobs")
    assert printing._may_look("/mnt/share/jobs/sub", "/mnt/share/jobs")  # inside the opened folder
    assert not printing._may_look("/mnt/share/other", "/srv/work/jobs")
