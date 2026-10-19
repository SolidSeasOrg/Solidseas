"""Container readers: the 2015+ container on the fixtures, synthetic edge cases, safety caps."""

import random
import struct
import zlib

import pytest

from builders import build_modern, wrap_zlb, zlb_chain
from solidseas.formats.solidworks import (
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
    UnknownFormatError,
    detect_format,
    open_container,
)
from solidseas.formats.solidworks.modern import decode_name, encode_name, lcg_signatures
from solidseas.formats.solidworks.zlb import ZLB_MAGIC, chain_sizes, iter_zlb_chain, unwrap_zlb, zlb_size
from support import NATIVE, fixture_path


def test_detect_format():
    assert detect_format(bytes.fromhex("d0cf11e0a1b11ae1")) == "ole"
    assert detect_format(b"\x12\x34\x56\x78\x00\x00\x00\x04") == "modern"
    assert detect_format(b"PK\x03\x04\x14\x00\x06\x00") is None
    with pytest.raises(UnknownFormatError):
        open_container(b"not a SOLIDWORKS document")


def test_name_encoding_is_a_nibble_swap():
    assert decode_name(bytes.fromhex("0527566796567705e474")) == "PreviewPNG"
    for name in ("Contents/Config-0-Partition", "VirtualComp/Деталь^Сборка.sldprt", "[Content_Types].xml"):
        assert decode_name(encode_name(name)) == name


@pytest.mark.parametrize("name", NATIVE)
def test_fixture_container_structure(name):
    with open_container(fixture_path(name)) as c:
        assert c.format == "modern"
        meta = c.meta
        # the end-of-central-directory record locates itself: 8 + cd_offset + cd_size == its own offset
        assert meta["cd_offset"] + meta["cd_size"] == meta["eocd_offset"]
        # SOLIDWORKS 2024 writes decoy records before the first real member and after the directory
        assert meta["first_local_header"] > 8 and meta["cd_slack"] > 0
        assert c.signatures_match_lcg() is True
        assert not c.warnings
        names = c.names()
        assert len(names) == len(set(names))
        for required in ("Contents/Definition", "Header2", "docProps/core.xml", "swXmlContents/KeyWords"):
            assert required in names


@pytest.mark.parametrize("name", NATIVE)
def test_every_stream_decodes_with_size_and_crc(name):
    with open_container(fixture_path(name)) as c:
        for s in c.streams():
            data = c.read(s.name, verify="strict")
            assert len(data) == s.size
            assert zlib.crc32(data) == s.crc32
            assert s.codec == "deflate"
            assert c.peek(s.name, 4) == data[:4]


def test_lcg_model_predicts_one_signature_triple():
    with open_container(fixture_path("o02_boxA.SLDPRT")) as c:
        preds = lcg_signatures(bytes.fromhex(c.meta["key"]))
        observed = (c.meta["lfh_signature"], c.meta["cd_signature"], c.meta["eocd_signature"])
    assert len(preds) == 1
    assert tuple(x.hex() for x in preds[0]) == observed


def test_partition_is_a_zlb_chain_of_partition_and_deltas():
    with open_container(fixture_path("o02_boxA.SLDPRT")) as c:
        data = c.read("Contents/Config-0-Partition")
    blocks = list(iter_zlb_chain(data))
    assert [b[:4] for b in blocks] == [b"PS\x00\x00", b"PS\x00\x00"]
    assert b"TRANSMIT FILE (partition)" in blocks[0][:90]
    assert b"TRANSMIT FILE (deltas)" in blocks[1][:90]
    assert chain_sizes(data) == [len(b) for b in blocks]


def test_lookup_is_case_insensitive_when_unique():
    with open_container(fixture_path("o02_boxA.SLDPRT")) as c:
        assert c.info("contents/config-0-partition").name == "Contents/Config-0-Partition"
        with pytest.raises(KeyError):
            c.info("no such stream")


def test_synthetic_modern_container_round_trip():
    members = {"Contents/Definition": b"\x00" * 64, "Empty": b"", "docProps/core.xml": b"<x/>" * 1000}
    with open_container(build_modern(members)) as c:
        assert c.names() == list(members)
        for name, data in members.items():
            assert c.read(name) == data
        assert c.signatures_match_lcg() is False  # arbitrary signatures in the builder


def test_declared_size_above_cap_is_refused_before_inflating():
    doc = build_modern({"big": b"x" * 1000}, declared={"big": 3 << 30})
    with open_container(doc) as c, pytest.raises(SldLimitError):
        c.read("big")


def test_member_inflating_beyond_declared_size_is_an_integrity_error():
    doc = build_modern({"bomb": b"\0" * 1_000_000}, declared={"bomb": 1000})
    with open_container(doc) as c, pytest.raises(SldIntegrityError):
        c.read("bomb")


def test_crc_mismatch_is_detected():
    doc = bytearray(build_modern({"a": b"hello world" * 10}))
    # flip one CRC byte in both the local header and the central directory copy
    for pos in (8 + 14, len(doc) - 22 - (46 + 1) + 16):
        doc[pos] ^= 0xFF
    with open_container(bytes(doc)) as c, pytest.raises(SldIntegrityError):
        c.read("a")


def test_truncated_and_corrupted_files_raise_only_library_errors():
    original = fixture_path("o02_boxA.SLDPRT").read_bytes()
    rng = random.Random(20260930)
    cases = [original[:n] for n in sorted(rng.sample(range(len(original)), 120))]
    for _ in range(120):
        b = bytearray(original)
        for _k in range(rng.randint(1, 8)):
            b[rng.randrange(len(b))] = rng.randrange(256)
        cases.append(bytes(b))
    outcomes = {"ok": 0, "error": 0}
    for data in cases:
        try:
            with open_container(data) as c:
                for s in c.streams():
                    c.read(s.name)
            outcomes["ok"] += 1
        except SldError:
            outcomes["error"] += 1
    assert outcomes["ok"] + outcomes["error"] == len(cases)
    assert outcomes["error"] > 0


def test_zlb_helpers():
    payload = bytes(range(256)) * 600
    block = wrap_zlb(payload, chunk=50_000)
    assert block.startswith(ZLB_MAGIC)
    assert zlb_size(block) == (len(payload), len(block))
    assert unwrap_zlb(block) == payload
    with pytest.raises(SldLimitError):
        unwrap_zlb(block, max_bytes=1000)
    with pytest.raises(SldFormatError):
        unwrap_zlb(b"\0" * 32)
    with pytest.raises(SldFormatError):
        unwrap_zlb(block + b"trailing")
    chain = zlb_chain([b"first", b"", payload])
    assert list(iter_zlb_chain(chain)) == [b"first", b"", payload]
    with pytest.raises(SldFormatError):
        list(iter_zlb_chain(chain[:-3]))


def test_corrupt_zlb_chunk_is_reported():
    block = bytearray(wrap_zlb(b"abc" * 1000))
    (_usize, csize) = struct.unpack_from("<II", block, 16)
    block[24 + csize // 2] ^= 0xFF
    with pytest.raises(SldFormatError):
        unwrap_zlb(bytes(block))
