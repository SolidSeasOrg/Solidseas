"""Parasolid reading, writing and the LocalBodies fallback, on synthetic containers."""

import struct

import pytest

from builders import build_modern, wrap_zlb
from solidseas.formats.solidworks import ParasolidError, open_container
from solidseas.formats.solidworks import parasolid as ps
from solidseas.formats.solidworks.localbodies import LocalBodiesError, iter_local_bodies
from support import fixture_path


def _stream(name: str, fixture: str) -> bytes:
    with open_container(fixture_path(fixture)) as c:
        return c.read(name)


def _box_transmit() -> bytes:
    return ps.split_header(fixture_path("o02_boxA.x_b").read_bytes())[1]


def _cstring(text: str) -> bytes:
    raw = text.encode("utf-16-le")
    return b"\xff\xfe\xff" + bytes([len(text)]) + raw


def _local_bodies(feature: str, transmit: bytes) -> bytes:
    block = wrap_zlb(transmit)
    record = struct.pack("<IBIBI", 0, 0, len(block) + 5, 0, len(block)) + block
    return struct.pack("<I", 1) + _cstring(feature) + record


def _doc(partition_from: str) -> bytes:
    return build_modern(
        {
            "Contents/Config-0-Partition": _stream("Contents/Config-0-Partition", partition_from),
            "Config-0-FeatureBodies/LocalBodies": _local_bodies("Imported1", _box_transmit()),
        }
    )


def test_local_bodies_framing():
    items = list(iter_local_bodies(_local_bodies("Imported1", _box_transmit())))
    assert [(name, k) for name, k, _ in items] == [("Imported1", 0)]
    assert items[0][2] == _box_transmit()
    with pytest.raises(LocalBodiesError):
        list(iter_local_bodies(_local_bodies("Imported1", _box_transmit()) + b"junk"))


def test_empty_partition_falls_back_to_local_bodies():
    with open_container(_doc("o01_empty.SLDPRT")) as c:
        res = ps.extract_parasolid(c)
        assert [(b.name, b.source, b.feature, b.body_type) for b in res.bodies] == [
            ("Config-0/local/Imported1#0", "local-bodies", "Imported1", "solid")
        ]
        ref = ps.read_file(fixture_path("o02_boxA.x_b").read_bytes())
        assert ps.compare_brep(ps.read_file(res.bodies[0].x_b("imported")), ref)["identical"]
        assert ps.extract_parasolid(c, local_bodies="never").bodies == []


def test_partition_bodies_win_over_local_bodies():
    with open_container(_doc("o02_boxA.SLDPRT")) as c:
        assert [b.source for b in ps.extract_parasolid(c).bodies] == ["partition"]
        assert [b.source for b in ps.extract_parasolid(c, local_bodies="always").bodies] == [
            "partition",
            "local-bodies",
        ]


def test_capped_partition_does_not_fall_back():
    with open_container(_doc("o02_boxA.SLDPRT")) as c:
        res = ps.extract_parasolid(c, max_bytes=1000)
    assert res.bodies == []
    errors = [p["error"] for p in res.problems]
    assert any("exceeds the cap" in e for e in errors)
    assert any("partition could not be read" in e for e in errors)


def test_number_formatting_matches_parasolid_text():
    assert ps.fmt_double(0.03) == ".03"
    assert ps.fmt_double(-0.5) == "-.5"
    assert ps.fmt_double(1000.0) == "1e3"
    assert ps.fmt_double(1e-08) == "1e-8"
    assert ps.fmt_double(0.0) == "0"
    assert ps.fmt_double(ps.NULL_DOUBLE) == "?"


def test_text_round_trip_of_extracted_body():
    with open_container(fixture_path("o07_boxB_h31.SLDPRT")) as c:
        body = ps.extract_parasolid(c).bodies[0]
    xt_text = ps.read_file(body.x_t("b"))
    xt_bin = ps.read_file(body.x_b("b"))
    # text keeps 15 significant digits, as Parasolid's own text output does (1000.0000000000001 -> 1e3)
    assert [(n.type, n.index) for n in xt_text.nodes] == [(n.type, n.index) for n in xt_bin.nodes]
    assert ps.compare_brep(xt_text, xt_bin, tol=1e-14)["identical"]
    assert all(len(line) <= 80 for line in body.x_t("b").decode("latin-1").splitlines())


def test_header_is_ascii_and_anonymous():
    with open_container(fixture_path("o02_boxA.SLDPRT")) as c:
        body = ps.extract_parasolid(c).bodies[0]
    header, _ = ps.split_header(body.x_b("Деталь; part"))
    text = header.decode("ascii")
    assert "KEY=______^;^_part;" in text
    for field in ("USER=unknown;", "MC_ID=unknown;", "DATE=unknown;", "SCH=SCH_3501251_35102;"):
        assert field in text


def test_damaged_transmits_raise_parasolid_errors():
    good = _box_transmit()
    with pytest.raises(ParasolidError):
        ps.parse_binary(b"PS\x00\x00" + b"\xff" * 40)
    with pytest.raises(ParasolidError):
        ps.parse_binary(good[: len(good) // 2])
    with pytest.raises(ParasolidError):
        ps.parse_binary(good.replace(b"SCH_3501251_35102_13006", b"SCH_1800141_18007_99999"))
    assert ps.validate(ps.parse_binary(good + b"\0\0"))["ok"] is False  # trailing bytes
