"""Which folders are on another computer's file system, on Linux and macOS (provisional).

Windows says so by a drive letter's kind and by UNC paths
(:meth:`solidseas.resolve.Gateway.anchor_class`). On Linux a share is a mount
like any other, and its file system type says what it is: ``nfs``, ``cifs``, a
FUSE file system such as ``fuse.sshfs``. :func:`is_network` decides from a
path's text and the mount table the kernel keeps in memory
(``/proc/self/mountinfo``), so nothing is asked of the share itself and a server
that has gone away cannot make the answer wait. A path's mount is the longest
mount point its text begins with, a later mount on the same point hiding an
earlier one; a link from a local folder into a share is not followed, so it is
not seen (what writes there, the catalog and 3D Print, never writes through a
link anyway).

On macOS the table comes from ``getfsstat(2)`` with ``MNT_NOWAIT``, which
answers from what the kernel already holds and so asks nothing of a share
either. Each mount's ``struct statfs`` (the 64-bit inode layout, the only one
on Apple silicon and the default on Intel since 10.6) gives its mount point,
its type and its flags. A mount is a network one when its type says so
(``smbfs``, ``nfs``, ``afpfs``, ``webdav``, ``ftp``, ``cifs``) or when the
system does not mark it local (``MNT_LOCAL``), as it does not mark a macFUSE
file system such as sshfs. An automounter trigger (``autofs``) is not one,
since whatever it mounts appears as a mount of its own. Mount points are
compared without regard to case there, as macOS's own disks compare names.

Anywhere else, and wherever the table cannot be read, :func:`is_network`
answers False. It never raises.
"""

import ctypes
import os
import platform
import posixpath
import struct
import sys
import time

MOUNTINFO = "/proc/self/mountinfo"
CACHE_S = 5.0  # the mount table is read again after this long

# macOS's struct statfs with 64-bit inodes (<sys/mount.h>; MFSTYPENAMELEN 16, MAXPATHLEN
# 1024): f_bsize, f_iosize, five 64-bit counts, f_fsid, f_owner, f_type, then f_flags at
# byte 64, f_fssubtype, f_fstypename at 72, f_mntonname at 88, f_mntfromname at 1112, and
# f_flags_ext and seven reserved words up to 2168 bytes. Intel and Apple silicon Macs are
# both little-endian.
STATFS_SIZE = 2168
_FLAGS_AT = 64
_FSTYPENAME = slice(72, 88)
_MNTONNAME = slice(88, 1112)
MNT_LOCAL = 0x00001000
MNT_NOWAIT = 2  # answer from the kernel's own records, without asking any file system
# The getfsstat that fills that layout: on Apple silicon the plain name, on Intel the
# getfsstat$INODE64 symbol the SDK's headers bind getfsstat to. getfsstat64, deprecated
# but filling the same layout, is the fallback on both.
_GETFSSTAT = {"arm64": ("getfsstat", "getfsstat64")}
_GETFSSTAT_DEFAULT = ("getfsstat$INODE64", "getfsstat64")

# File system types whose files are kept on another computer. FUSE file systems are
# named fuse.<program>; GNOME's gvfs shows its SMB, SFTP and WebDAV shares through one.
NETWORK_TYPES = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smb3",
        "smbfs",
        "ncpfs",
        "afs",
        "coda",
        "ceph",
        "glusterfs",
        "lustre",
        "gpfs",
        "beegfs",
        "davfs",
        "fuse.sshfs",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.davfs2",
        "fuse.glusterfs",
        "fuse.cephfs",
        "fuse.gvfsd-fuse",
        "fuse.smbnetfs",
        "fuse.curlftpfs",
        # macOS's own names for AFP, WebDAV and FTP shares (SMB is smbfs, NFS nfs)
        "afpfs",
        "webdav",
        "ftp",
    }
)
# Types macOS does not mark local that still hold nothing of another computer's: the
# automounter's trigger points, and the device and descriptor file systems.
NOT_LOCAL_YET_HERE = frozenset({"autofs", "devfs", "fdesc"})

# (mount point, type, flags, or None where the system gives none), in mount order
Mount = tuple[str, str, int | None]

_cache: tuple[float, list[Mount], list[tuple[str, str]]] | None = None


def _unescape(field: str) -> str:
    """A mountinfo field as the path it names: the kernel writes a space, tab, newline
    or backslash in it as a backslash and three octal digits."""
    if "\\" not in field:
        return field
    out = []
    i = 0
    while i < len(field):
        code = field[i + 1 : i + 4]
        if field[i] == "\\" and len(code) == 3 and all(c in "01234567" for c in code):
            out.append(chr(int(code, 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def parse_mountinfo(text: str) -> list[tuple[str, str]]:
    """``[(mount point, file system type)]`` of a mountinfo text, in mount order. A line
    is the mount's id, its parent's, the device, the root, the mount point, its
    options, optional fields, a lone ``-``, then the type; a line that does not read so
    is passed over."""
    table = []
    for line in text.splitlines():
        fields = line.split(" ")
        try:
            sep = fields.index("-", 6)
        except ValueError:
            continue
        if sep + 1 < len(fields) and fields[4].startswith("/"):
            table.append((_unescape(fields[4]), fields[sep + 1]))
    return table


def parse_statfs(data: bytes) -> list[Mount]:
    """``[(mount point, file system type, flags)]`` of what macOS's ``getfsstat`` wrote:
    whole ``struct statfs`` records of :data:`STATFS_SIZE` bytes, in mount order. A
    record whose type is empty or whose mount point is not absolute (another layout, or
    garbage) is passed over, and a short tail is ignored."""
    out: list[Mount] = []
    for at in range(0, len(data) - STATFS_SIZE + 1, STATFS_SIZE):
        rec = data[at : at + STATFS_SIZE]
        fstype = rec[_FSTYPENAME].split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        point = rec[_MNTONNAME].split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        if fstype and point.startswith("/"):
            out.append((point, fstype, struct.unpack_from("<I", rec, _FLAGS_AT)[0]))
    return out


def _getfsstat(libc) -> list[Mount]:
    """Every mount macOS knows of, through ``libc``'s 64-bit inode ``getfsstat``; empty
    when there is none to call or it answers an error."""
    fn = None
    for name in _GETFSSTAT.get(platform.machine(), _GETFSSTAT_DEFAULT):
        try:
            fn = getattr(libc, name)
            break
        except AttributeError:
            continue
    if fn is None:
        return []
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    count = fn(None, 0, MNT_NOWAIT)
    for _attempt in range(3):  # a mount made between two calls asks for a bigger buffer
        if count <= 0:
            return []
        room = count + 4
        buf = ctypes.create_string_buffer(room * STATFS_SIZE)
        count = fn(buf, room * STATFS_SIZE, MNT_NOWAIT)
        if 0 <= count < room:
            return parse_statfs(buf.raw[: count * STATFS_SIZE])
    return []


def _read_mounts(libc=None) -> list[Mount]:
    """This system's mounts, read now: ``/proc/self/mountinfo`` on Linux, ``getfsstat``
    from ``libc`` (default: this process's C library) on macOS; nothing elsewhere or on
    any failure."""
    try:
        if sys.platform == "darwin":
            return _getfsstat(libc if libc is not None else ctypes.CDLL(None, use_errno=True))
        if sys.platform.startswith("linux"):
            with open(MOUNTINFO, encoding="utf-8", errors="surrogateescape") as fh:
                return [(point, fstype, None) for point, fstype in parse_mountinfo(fh.read())]
    except Exception:  # a table that cannot be read means only that nothing is known
        pass
    return []


def _mounts() -> tuple[list[Mount], list[tuple[str, str]]]:
    """The mounts and their ``(point, type)`` table, read at most every :data:`CACHE_S`
    seconds."""
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] >= CACHE_S:
        mounts = _read_mounts()
        _cache = (now, mounts, [(point, fstype) for point, fstype, _flags in mounts])
    return _cache[1], _cache[2]


def mount_table() -> list[tuple[str, str]]:
    """This process's mount table (read at most every :data:`CACHE_S` seconds); empty
    where it cannot be read."""
    return _mounts()[1]


def readable() -> bool:
    """Whether this system's mount table can be read, so that :func:`is_network` can
    tell a network file system: on Linux unless ``/proc`` is out of reach, on macOS
    unless ``getfsstat`` fails."""
    return (sys.platform.startswith("linux") or sys.platform == "darwin") and bool(mount_table())


def _mount_of(path: str, entries, fold: bool = False):
    """The entry of ``entries`` (each beginning with its mount point) that ``path`` lies
    on: the longest point its text begins with, the later one on the same point. With
    ``fold``, points are compared without regard to case."""
    text = os.fspath(path)
    # POSIX paths, as the table names them, whatever this system's own path rules are
    full = posixpath.normpath(text if text.startswith("/") else posixpath.join(os.getcwd(), text))
    if fold:
        full = full.casefold()
    best, found = -1, None
    for entry in entries:
        point = entry[0].casefold() if fold else entry[0]
        base = point.rstrip("/")
        if full == point or full.startswith(base + "/"):
            if len(base) >= best:
                best, found = len(base), entry
    return found


def mount_type(path: str, table: list[tuple[str, str]] | None = None) -> str | None:
    """The file system type of the mount ``path`` lies on, from its text and ``table``
    (default: :func:`mount_table`, compared without regard to case on macOS); None when
    no mount point holds it."""
    if table is None:
        entry = _mount_of(path, mount_table(), fold=sys.platform == "darwin")
    else:
        entry = _mount_of(path, table)
    return None if entry is None else entry[1]


def network_mount(fstype: str, flags: int | None = None) -> bool:
    """Whether a mount of type ``fstype`` holds another computer's files: a type in
    :data:`NETWORK_TYPES`, or, where the system gives the mount's ``flags`` (macOS), one
    it does not mark :data:`MNT_LOCAL`, unless the type is one of
    :data:`NOT_LOCAL_YET_HERE`."""
    if fstype in NETWORK_TYPES:
        return True
    return flags is not None and not flags & MNT_LOCAL and fstype not in NOT_LOCAL_YET_HERE


def is_network(path: str, table: list[tuple[str, str]] | None = None) -> bool:
    """Whether ``path`` lies on a network file system (:func:`network_mount`), from its
    text and the mount table alone. False outside Linux and macOS unless a ``table`` is
    given, and False whenever the table cannot be read."""
    try:
        if table is not None:
            return mount_type(path, table) in NETWORK_TYPES
        if sys.platform == "darwin":
            entry = _mount_of(path, _mounts()[0], fold=True)
            return entry is not None and network_mount(entry[1], entry[2])
        if not sys.platform.startswith("linux"):
            return False
        return mount_type(path) in NETWORK_TYPES
    except Exception:  # a refusal is never decided by raising
        return False


__all__ = [
    "CACHE_S",
    "MNT_LOCAL",
    "MNT_NOWAIT",
    "MOUNTINFO",
    "NETWORK_TYPES",
    "NOT_LOCAL_YET_HERE",
    "STATFS_SIZE",
    "is_network",
    "mount_table",
    "mount_type",
    "network_mount",
    "parse_mountinfo",
    "parse_statfs",
    "readable",
]
