"""A document held open is read lazily: opening reads the directory, ``peek``
reads the head of a stream, and a legacy ``__ZLB`` stream is sized from its
chunk headers. The answers are the same as from a whole-file read."""

import random
import struct

import pytest

from builders import build_cfb, wrap_zlb
from solidseas.formats.solidworks import SldFormatError, open_container, open_document
from solidseas.formats.solidworks import container as container_mod
from solidseas.formats.solidworks._io import ReadOnlyFile, pread
from support import NATIVE, fixture_path


class Counting:
    """Wraps the handle open_readonly returns and counts the bytes read through it."""

    def __init__(self, fh, log: list[int]) -> None:
        self._fh, self._log = fh, log

    def read(self, n=-1):
        data = self._fh.read(n)
        self._log.append(len(data))
        return data

    def __getattr__(self, name):
        return getattr(self._fh, name)


@pytest.fixture
def counted(monkeypatch) -> list[int]:
    log: list[int] = []
    real = container_mod.open_readonly
    monkeypatch.setattr(container_mod, "open_readonly", lambda p: Counting(real(p), log))
    return log


# --------------------------------------------------------------------------- the unbuffered handle
class Trickle:
    """A raw file that returns at most 3 bytes per read, as a raw read may."""

    def __init__(self, data: bytes) -> None:
        self.data, self.pos, self.closed = data, 0, False

    def read(self, n=-1):
        n = len(self.data) - self.pos if n is None or n < 0 else n
        out = self.data[self.pos : self.pos + min(n, 3)]
        self.pos += len(out)
        return out

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else (self.pos + offset if whence == 1 else len(self.data) + offset)
        return self.pos

    def tell(self):
        return self.pos

    def close(self):
        self.closed = True


def test_read_only_file_returns_whole_reads_from_short_raw_reads():
    f = ReadOnlyFile(Trickle(bytes(range(100))))
    assert f.read(10) == bytes(range(10)) and f.tell() == 10
    assert pread(f, 50, 20) == bytes(range(50, 70))
    f.seek(95)
    assert f.read(10) == bytes(range(95, 100)) and f.read(4) == b""
    with pytest.raises(SldFormatError):
        pread(f, 90, 20)  # past the end: an error, never a short answer
    f.close()
    assert f.closed


# --------------------------------------------------------------------------- the modern container
@pytest.mark.parametrize("name", NATIVE)
def test_opening_a_held_modern_file_reads_its_directory_only(name, counted):
    size = fixture_path(name).stat().st_size
    with open_container(fixture_path(name), hold_open=True) as c:
        opened = sum(counted)
        assert 0 < opened < 16 << 10 and opened < size // 2, opened  # a 64 KiB tail read would fail
        streams = len(c.streams())
        assert c.peek("PreviewPNG", 8) == b"\x89PNG\r\n\x1a\n"
    assert streams >= 20


def test_held_and_whole_reads_agree_on_every_fixture():
    for name in NATIVE:
        with (
            open_document(fixture_path(name)) as whole,
            open_document(fixture_path(name), hold_open=True) as held,
        ):
            assert held.summary() == whole.summary(), name
            for s in whole.streams():
                assert held.read_stream(s.name) == whole.read_stream(s.name), (name, s.name)


# --------------------------------------------------------------------------- the legacy container
def _legacy(tmp_path):
    big = bytes(range(256)) * 800  # 204,800 bytes in regular sectors
    packed = random.Random(7).randbytes(128_000)  # incompressible: the stored stream is as large
    streams = {
        "Contents/Big": big,
        "Contents/Packed__ZLB": wrap_zlb(packed, chunk=8192),  # 16 chunks
        "Contents/Small": b"small stream in the mini stream",
        "Header2": b"\0" * 10,
    }
    path = tmp_path / "legacy.SLDPRT"
    path.write_bytes(build_cfb(streams))
    return path, big, packed


def test_legacy_streams_are_read_lazily(tmp_path, counted):
    path, big, packed = _legacy(tmp_path)
    size = path.stat().st_size
    with open_container(path, hold_open=True) as c:
        opened = sum(counted)
        # header, allocation tables, directory and the 16 chunk headers: not the 330 KB of data
        assert opened < 8 << 10 and opened < size // 20, opened
        info = c.info("Contents/Packed")
        assert (info.codec, info.size) == ("zlb", len(packed))
        counted.clear()
        assert c.peek("Contents/Big", 2) == big[:2] and sum(counted) == 2
        counted.clear()
        assert c.read("Contents/Big") == big
        assert sum(counted) == len(big) and len(counted) <= 4  # contiguous sectors in few reads
        assert c.read("Contents/Packed") == packed
        assert c.read("Contents/Small") == b"small stream in the mini stream"
    with open_container(path) as whole:  # read whole: the same streams and sizes
        held = open_container(path, hold_open=True)
        try:
            assert whole.streams() == held.streams()
            assert all(whole.read(n) == held.read(n) for n in whole.names())
        finally:
            held.close()


def test_a_broken_sector_chain_is_a_format_error(tmp_path):
    path, _big, _packed = _legacy(tmp_path)
    import olefile

    data = bytearray(path.read_bytes())
    ole = olefile.OleFileIO(bytes(data))
    start = ole.direntries[ole._find("Contents/Big")].isectStart
    ole.close()
    fat_sector = struct.unpack_from("<I", data, 76)[0]  # the first DIFAT entry in the header
    struct.pack_into("<I", data, (fat_sector + 1) * 512 + 4 * start, 0xFFFFFFFE)  # end the chain at once
    for hold_open in (False, True):
        broken = tmp_path / f"broken{hold_open}.SLDPRT"
        broken.write_bytes(bytes(data))
        with open_container(broken, hold_open=hold_open) as c:
            assert c.read("Contents/Small") == b"small stream in the mini stream"  # the rest still reads
            for call in (c.read, c.read_raw, lambda n: c.peek(n, 2)):
                with pytest.raises(SldFormatError, match="sector chain"):
                    call("Contents/Big")
