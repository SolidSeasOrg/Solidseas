"""Crafted and hostile inputs, and the command line's write guards.

Every input here is synthetic, built from the fixtures or from scratch. Each test
reproduces a problem found by review and checks that it stays fixed: a pointer
cycle, a flood of fake directory records, quadratic string scans, decompression
with no per-document budget, a batch that stopped at one bad file, output paths
that aliased a SOLIDWORKS file, and a file handle that blocked replacing the file.
"""

import csv
import dataclasses
import json
import os
import shutil
import struct
import time

import pytest

from builders import build_cfb, build_modern, wrap_zlb
from solidseas import cli
from solidseas.formats.solidworks import (
    LockedFileError,
    ParasolidError,
    SldError,
    SldFormatError,
    open_container,
    open_document,
)
from solidseas.formats.solidworks import metadata as md
from solidseas.formats.solidworks import parasolid as ps
from support import fixture_path

WINDOWS = os.name == "nt"


def _box() -> ps.XtTransmit:
    return ps.parse_binary(ps.split_header(fixture_path("o02_boxA.x_b").read_bytes())[1])


def _set(xt: ps.XtTransmit, node, name: str, value) -> None:
    node.vals[xt.field_names(node.type).index(name)] = value


# --------------------------------------------------------------------------- Parasolid
def test_loop_cycle_is_reported_not_followed():
    xt = _box()
    loop = next(n for n in xt.nodes if n.tname == "LOOP")
    _set(xt, loop, "next", loop.index)
    start = time.monotonic()
    rep = ps.validate(xt)
    assert time.monotonic() - start < 5
    assert not rep["ok"] and any("pointer cycle" in e for e in rep["errors"])


def test_fin_cycle_is_reported_not_followed():
    xt = _box()
    idx = xt.by_index()
    loop = next(n for n in xt.nodes if n.tname == "LOOP")
    second = idx[xt.get(idx[xt.get(loop, "halfedge")], "forward")]
    _set(xt, second, "forward", second.index)
    rep = ps.validate(xt)
    assert not rep["ok"] and any("pointer cycle" in e for e in rep["errors"])


def test_field_missing_from_the_schema_is_a_parasolid_error():
    xt = _box()
    body = xt.by_index()[1]
    xt.layouts[body.type] = [f for f in xt.layouts[body.type] if f[0] != "body_type"]
    with pytest.raises(ParasolidError):
        ps.body_type_name(xt, body)


def test_damaged_text_transmits_raise_only_library_errors():
    data = fixture_path("o02_boxA.x_t").read_bytes()
    step = max(1, len(data) // 60)
    for n in range(0, len(data), step):
        try:
            ps.read_file(data[:n])
        except SldError:
            pass
    with pytest.raises(ParasolidError):
        ps.parse_text("T 3 abc 23 SCH_3501251_35102_13006 " + "30 C " * 200)


# --------------------------------------------------------------------------- container
def _eocd_flood(candidates: int) -> bytes:
    """A modern container whose tail holds many self-consistent fake end records.

    Every candidate's directory starts at the same plausible first record and
    covers most of the file, which made each candidate cost a large read."""
    cd_off = 100
    cd_start = 8 + cd_off
    first = b"\x55\x66\x77\x88" + struct.pack(
        "<HHHHHHIIIHHHHHII", 0, 20, 6, 8, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0
    )
    out = bytearray(b"\x10\x20\x30\x40\x00\x00\x00\x04" + bytes(cd_off))
    out += first + b"x"
    out += bytes(4096)
    for _ in range(candidates):
        p = len(out)
        out += b"\x99\xaa\xbb\xcc" + struct.pack("<HHHHIIH", 0, 0, 1, 1, p - cd_start, cd_off, 0)
    return bytes(out)


def test_eocd_flood_fails_fast():
    data = _eocd_flood(20_000)
    start = time.monotonic()
    with pytest.raises(SldFormatError):
        open_container(data)
    assert time.monotonic() - start < 5


def _legacy_crafted(
    sector: int, *, root_size: int | None = None, loop_root: bool = False, minifat_count: int | None = None
) -> bytes:
    """A small legacy container with its mini stream or mini allocation table lied about.

    ``root_size`` replaces the root entry's size (the size of the mini stream),
    ``loop_root`` points the last sector of the mini stream's chain at itself, and
    ``minifat_count`` replaces the header's count of mini allocation table sectors,
    whose chain is then pointed at itself too."""
    streams = {"Header2": b"H" * 300, "Contents/Config-0": b"x" * 10, "Contents/Big": bytes(5000)}
    data = bytearray(build_cfb(streams, sector=sector))
    first_dir = struct.unpack_from("<I", data, 48)[0]
    fat_off = (struct.unpack_from("<I", data, 76)[0] + 1) * sector  # the first DIFAT entry
    root_off = (first_dir + 1) * sector  # directory entry 0 is the root
    if root_size is not None:
        struct.pack_into("<Q", data, root_off + 120, root_size)
    if loop_root:
        s = struct.unpack_from("<I", data, root_off + 116)[0]
        while (nxt := struct.unpack_from("<I", data, fat_off + 4 * s)[0]) < 0xFFFFFFF0:
            s = nxt
        struct.pack_into("<I", data, fat_off + 4 * s, s)
    if minifat_count is not None:
        struct.pack_into("<I", data, 0x40, minifat_count)
        first_minifat = struct.unpack_from("<I", data, 0x3C)[0]
        struct.pack_into("<I", data, fat_off + 4 * first_minifat, first_minifat)
    return bytes(data)


LEGACY_LIES = {
    # 0.86 s spent on 8 million sector numbers, and no error, before the fix
    "v3 mini stream of 4 GiB, looped": dict(sector=512, root_size=0xFFFFFF00, loop_root=True),
    # 6.9 s and half a gigabyte of sector numbers before the fix
    "v4 mini stream of 2**38 bytes, looped": dict(sector=4096, root_size=1 << 38, loop_root=True),
    # 1.5 s from bytes and 4.3 s held open (512 MiB of reads) before the fix
    "v3 mini allocation table of 2**20 sectors, looped": dict(sector=512, minifat_count=0x100000),
}


@pytest.mark.parametrize("label", LEGACY_LIES)
def test_a_legacy_file_that_lies_about_its_mini_stream_fails_fast(label, tmp_path):
    data = _legacy_crafted(**LEGACY_LIES[label])
    path = tmp_path / "crafted.SLDPRT"
    path.write_bytes(data)
    for src, hold_open in ((data, False), (path, True)):  # whole bytes, and the listing's lazy reads
        start = time.monotonic()
        with open_container(src, hold_open=hold_open) as c, pytest.raises(SldFormatError, match="more than"):
            c.read("Header2")
        assert time.monotonic() - start < 1.0, (label, hold_open)
    # control: the same file before the lie reads normally
    plain = _legacy_crafted(LEGACY_LIES[label]["sector"])
    with open_container(plain) as c:
        assert c.read("Header2") == b"H" * 300


def test_a_sector_chain_longer_than_its_table_is_refused():
    data = _legacy_crafted(512)
    with open_container(data) as c:
        with pytest.raises(SldFormatError, match="must loop"):
            c._chain(0, 4, [1, 2, 0], "crafted")  # four sectors from a table of three: a loop
        assert c._chain(0, 3, [1, 2, 0], "crafted") == [0, 1, 2]


# --------------------------------------------------------------------------- metadata
def _runaway_strings(units: int, prefix: bytes = b"") -> bytes:
    """Markers whose declared string runs to the end of the data (10 or 14 bytes each)."""
    unit = len(prefix) + 10
    total = units * unit
    out = bytearray()
    for _ in range(units):
        remaining = (total - (len(out) + unit)) // 2
        out += prefix + b"\xff\xfe\xff\xff\xff\xff" + struct.pack("<I", remaining)
    return bytes(out)


def test_header2_and_cusprops_scans_are_linear():
    start = time.monotonic()
    md.parse_header2(_runaway_strings(20_000))
    md.parse_cusprops(_runaway_strings(20_000, b"\x09\x00\x00\x00"))
    assert time.monotonic() - start < 3


def test_long_cstrings_count_as_no_string():
    data = b"\xff\xfe\xff\xff\xff\xff" + struct.pack("<I", 40_000) + bytes(80_000)
    assert md.read_cstring(data, 0) == (None, 0)
    assert md.read_cstring(data, 0, max_chars=50_000)[0] is not None


def test_xml_with_a_doctype_is_refused():
    warnings: list[str] = []
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;&a;</x>'
    assert md._parse_xml(bomb, "test", warnings) is None
    assert warnings and "DOCTYPE" in warnings[0]


def _with_streams(fixture: str, changes: dict[str, bytes]) -> bytes:
    with open_container(fixture_path(fixture)) as c:
        streams = {n: c.read(n) for n in c.names()}
    return build_modern({**streams, **changes})


def _streams(fixture: str, *names: str) -> list[bytes]:
    with open_container(fixture_path(fixture)) as c:
        return [c.read(n) for n in names]


def test_material_placeholder_yields_to_materialtree():
    (kw,) = _streams("o05_boxA_props_mat.SLDPRT", "swXmlContents/KeyWords")
    for replacement in (b'Material="Material &lt;not specified&gt;"', b""):
        data = _with_streams(
            "o05_boxA_props_mat.SLDPRT",
            {"swXmlContents/KeyWords": kw.replace(b'Material="1060 Alloy"', replacement)},
        )
        with open_document(data) as doc:
            assert doc.material == "1060 Alloy"
            assert [c.material for c in doc.configurations] == ["1060 Alloy"]


def test_materialtree_does_not_invent_configurations():
    (mt,) = _streams("o05_boxA_props_mat.SLDPRT", "swXmlContents/MATERIALTREE")
    text = mt.decode("utf-16")  # MATERIALTREE is UTF-16 with a byte-order mark
    ghost = (
        '<configuration name="Ghost" material="SOLIDWORKS Materials|1060 Alloy|14"/>\n'
        "</configurationslist>"
    )
    assert "</configurationslist>" in text
    data = _with_streams(
        "o05_boxA_props_mat.SLDPRT",
        {"swXmlContents/MATERIALTREE": text.replace("</configurationslist>", ghost).encode("utf-16")},
    )
    with open_document(data) as doc:
        assert [c.name for c in doc.configurations] == ["Default"]
        assert any("Ghost" in w for w in doc.warnings)


# --------------------------------------------------------------------------- decompression budget
def _local_bodies(feature: str, payloads: list[bytes]) -> bytes:
    name = b"\xff\xfe\xff" + bytes([len(feature)]) + feature.encode("utf-16-le")
    records = b""
    for p in payloads:
        block = wrap_zlb(p)
        records += struct.pack("<IBIBI", 0, 0, len(block) + 5, 0, len(block)) + block
    return struct.pack("<I", 1) + name + struct.pack("<II", 0, len(payloads)) + records


def test_decompression_is_budgeted_per_document(monkeypatch):
    (partition,) = _streams("o01_empty.SLDPRT", "Contents/Config-0-Partition")
    data = build_modern(
        {
            "Contents/Config-0-Partition": partition,
            "Config-0-FeatureBodies/LocalBodies": _local_bodies("Imported1", [bytes(200_000)] * 5),
        }
    )
    inflated = []
    real = ps.unwrap_zlb

    def counting(block, *args, **kwargs):
        out = real(block, *args, **kwargs)
        inflated.append(len(out))
        return out

    monkeypatch.setattr(ps, "unwrap_zlb", counting)
    with open_container(data) as c:
        res = ps.extract_parasolid(c, max_bytes=300_000, max_total_bytes=500_000)
        assert sum(n for n in inflated if n == 200_000) == 400_000  # two bodies, then the budget is spent
        assert sum("decompression budget" in p["error"] for p in res.problems) == 3
        inflated.clear()
        res = ps.extract_parasolid(c, max_bytes=100_000)
        assert 200_000 not in inflated  # over the per-transmit cap: never inflated
        assert sum("exceeds the cap" in p["error"] for p in res.problems) == 5


# --------------------------------------------------------------------------- file handles and locks
def _copy(tmp_path, name: str = "o02_boxA.SLDPRT", to: str = "part.SLDPRT"):
    folder = tmp_path / "src"
    folder.mkdir(exist_ok=True)
    dst = folder / to
    shutil.copyfile(fixture_path(name), dst)
    return dst


def test_open_document_does_not_hold_the_file(tmp_path):
    src = _copy(tmp_path)
    other = _copy(tmp_path, "o07_boxB_h31.SLDPRT", "other.SLDPRT")
    with open_document(src) as doc:
        os.replace(other, src)  # what an editor does when it saves through a temporary file
        assert doc.doc_type == "part" and doc.parasolid().bodies


@pytest.mark.skipif(not WINDOWS, reason="Windows sharing rules")
def test_hold_open_keeps_a_shared_handle(tmp_path):
    src = _copy(tmp_path)
    other = _copy(tmp_path, "o07_boxB_h31.SLDPRT", "other.SLDPRT")
    with open_document(src, hold_open=True) as doc:
        with pytest.raises(PermissionError):
            os.replace(other, src)
        assert doc.doc_type == "part"


@pytest.mark.skipif(not WINDOWS, reason="byte-range locks through msvcrt")
@pytest.mark.parametrize("hold_open", [False, True])
def test_byte_range_lock_is_reported_as_locked(tmp_path, hold_open):
    import msvcrt

    src = _copy(tmp_path)
    size = src.stat().st_size
    with open(src, "rb") as holder:
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, size)
        try:
            with pytest.raises(LockedFileError):
                with open_document(src, hold_open=hold_open) as doc:
                    doc.info()
        finally:
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, size)


# --------------------------------------------------------------------------- command line
@pytest.mark.skipif(not WINDOWS, reason="Windows path aliases")
@pytest.mark.parametrize("suffix", [".", " ", ". .", "::$DATA", ":stream"])
def test_aliases_of_a_solidworks_file_are_refused(tmp_path, suffix):
    victim = tmp_path / "other" / "victim.SLDPRT"
    victim.parent.mkdir()
    victim.write_bytes(b"keep")
    with pytest.raises(cli.Refused):
        cli.check_output_file(str(victim) + suffix, [str(tmp_path / "src" / "a.SLDPRT")],
                              allow_source_dir=False, force=True)
    assert victim.read_bytes() == b"keep"


@pytest.mark.skipif(not WINDOWS, reason="Windows device paths")
@pytest.mark.parametrize("path", ["\\\\?\\C:\\out\\a.bin", "\\\\.\\COM1", "//?/C:/out/a.bin"])
def test_device_and_extended_paths_are_refused(path):
    with pytest.raises(cli.Refused):
        cli.final_path(path)


def test_hard_links_are_never_overwritten(tmp_path):
    src = _copy(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "plain.bin").write_bytes(b"x")
    try:
        os.link(src, out / "link.bin")  # another name for the source
        os.link(out / "plain.bin", out / "twin.bin")  # shares data with an unrelated file
    except OSError:
        pytest.skip("hard links not supported here")
    for name in ("link.bin", "twin.bin"):
        with pytest.raises(cli.Refused):
            cli.check_output_file(str(out / name), [str(src)], allow_source_dir=False, force=True)
    before = src.read_bytes()
    code = cli.main(["dump", str(src), "PreviewPNG", "-o", str(out / "link.bin"), "--force"])
    assert code == cli.EXIT_REFUSED and src.read_bytes() == before


def _admin_share(path) -> str | None:
    """``\\\\localhost\\C$\\...`` for a local path on a drive, or None when that
    administrative share is not reachable here."""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    if not WINDOWS or len(drive) != 2:
        return None
    alias = f"\\\\localhost\\{drive[0]}${rest}"
    return alias if os.path.isdir(alias) else None


@pytest.mark.skipif(not WINDOWS, reason="Windows administrative shares")
def test_an_admin_share_alias_of_the_source_folder_is_refused(tmp_path):
    src = _copy(tmp_path)
    alias = _admin_share(src.parent)
    if alias is None:
        pytest.skip("the administrative share \\\\localhost\\C$ is not reachable here")
    assert os.path.samefile(alias, src.parent)  # control: the alias is the source folder
    for out_dir in (alias, alias + "\\new", alias.upper()):
        with pytest.raises(cli.Refused) as refused:
            cli.check_output_dir(out_dir, [str(src.parent)], allow_source_dir=False)
        assert refused.value.detail == {"rule": "source_folder"}
        with pytest.raises(cli.Refused):
            cli.check_output_file(out_dir + "\\out.png", [str(src)], allow_source_dir=False, force=True)
        with pytest.raises(cli.Refused):
            cli.check_output_file(
                out_dir + "\\out.png", [], allow_source_dir=False, force=True, source_dirs=[str(src.parent)]
            )
    elsewhere = tmp_path / "out"
    assert cli.check_output_dir(str(elsewhere), [str(src.parent)], allow_source_dir=False)


def _folder_alias(target, link) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if not WINDOWS:
            pytest.skip("symbolic links are not available here")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_a_folder_alias_the_text_check_misses_is_caught_by_identity(tmp_path, monkeypatch):
    """Another name for the source folder that resolving links does not turn into the
    same text (an administrative share, a second share, a mount point) is caught by
    comparing device and file numbers. A link stands in for such a name here, with
    link resolution switched off."""
    src = _copy(tmp_path)
    alias = tmp_path / "alias"
    _folder_alias(src.parent, alias)
    try:
        monkeypatch.setattr(os.path, "realpath", os.path.abspath)
        for out_dir in (alias, alias / "new" / "deeper"):
            with pytest.raises(cli.Refused):
                cli.check_output_dir(str(out_dir), [str(src.parent)], allow_source_dir=False)
            with pytest.raises(cli.Refused):
                cli.check_output_file(
                    str(out_dir / "out.png"), [str(src)], allow_source_dir=False, force=False
                )
        assert cli.check_output_dir(str(tmp_path / "out"), [str(src.parent)], allow_source_dir=False)
    finally:
        monkeypatch.undo()
        if WINDOWS:
            os.rmdir(alias)  # removes the link or junction, not what it points at
        else:
            os.unlink(alias)


def _file_link(target, link) -> None:
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("file symbolic links need a privilege this account does not have")


def test_an_existing_output_that_is_a_link_is_never_followed(tmp_path):
    src = _copy(tmp_path)
    opened = src.parent
    victim = opened / "notes.png"  # not a SOLIDWORKS file, in the folder that was read
    victim.write_bytes(b"keep")
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(b"keep too")
    out = tmp_path / "out"
    out.mkdir()
    _file_link(victim, out / "into.png")
    _file_link(elsewhere, out / "away.png")
    with pytest.raises(cli.Refused) as refused:  # its target lies in the folder that was read
        cli.check_output_file(
            str(out / "into.png"), [], allow_source_dir=False, force=True, source_dirs=[opened]
        )
    assert refused.value.detail == {"rule": "source_folder"}
    with pytest.raises(cli.Refused) as refused:  # wherever it points, writing would follow it
        cli.check_output_file(str(out / "away.png"), [str(src)], allow_source_dir=False, force=True)
    assert refused.value.detail == {"rule": "link"}
    assert victim.read_bytes() == b"keep" and elsewhere.read_bytes() == b"keep too"


def test_every_refusal_names_its_rule(tmp_path):
    from solidseas import model

    src = _copy(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "taken.png").write_bytes(b"x")
    def file(path, force=True, allow=False):
        return lambda: cli.check_output_file(str(path), [str(src)], allow_source_dir=allow, force=force)

    cases = {
        "exists": file(out / "taken.png", force=False),
        "solidworks_file": file(out / "a.SLDASM"),
        "source_document": lambda: cli.check_output_file(  # a source that is not a SOLIDWORKS file
            str(out / "taken.png"), [str(out / "taken.png")], allow_source_dir=True, force=True
        ),
        "source_folder": lambda: cli.check_output_dir(
            str(src.parent / "x"), [str(src.parent)], allow_source_dir=False
        ),
    }
    for rule, call in cases.items():
        with pytest.raises(cli.Refused) as refused:
            call()
        assert model.error_info(refused.value)["detail"] == {"rule": rule}, rule


def test_alias_through_the_cli_leaves_the_victim_alone(tmp_path):
    src = _copy(tmp_path)
    victim = tmp_path / "other" / "victim.SLDPRT"
    victim.parent.mkdir()
    victim.write_bytes(b"keep")
    code = cli.main(["dump", str(src), "PreviewPNG", "-o", str(victim) + ("." if WINDOWS else ""), "--force"])
    assert code == cli.EXIT_REFUSED and victim.read_bytes() == b"keep"


def test_colliding_body_names_get_distinct_files(tmp_path):
    with open_container(fixture_path("o02_boxA.SLDPRT")) as c:
        body = ps.extract_parasolid(c).bodies[0]
    res = ps.ParasolidResult()
    res.bodies = [
        dataclasses.replace(body, configuration_name="A/B"),
        dataclasses.replace(body, configuration_name="A_B", configuration_id=1),
    ]
    written = cli._write_parasolid(
        res, "part", str(tmp_path / "out"), [str(fixture_path("o02_boxA.SLDPRT"))],
        text=True, raw=False, allow_source_dir=False, force=False,
    )
    outputs = [w["output"] for w in written]
    assert len(set(outputs)) == 4 and all(os.path.exists(o) for o in outputs)


def test_batch_survives_an_unexpected_error(tmp_path, monkeypatch):
    _copy(tmp_path, to="a.SLDPRT")
    _copy(tmp_path, to="b.SLDPRT")
    real = cli.open_document

    def flaky(path, *args, **kwargs):
        if os.path.basename(path) == "a.SLDPRT":
            raise ValueError("unexpected")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(cli, "open_document", flaky)
    out = tmp_path / "out"
    argv = ["batch", str(tmp_path / "src"), "-o", str(out), "--no-parasolid", "--json", "--in-process"]
    code = cli.main(argv)  # in this process, where the stand-in open_document applies
    assert code == cli.EXIT_PARTIAL  # finished, with one item error
    with open(out / "report.csv", encoding="utf-8", newline="") as fh:
        rows = {r["file"]: r for r in csv.DictReader(fh)}
    assert rows["a.SLDPRT"]["status"] == "error" and "ValueError" in rows["a.SLDPRT"]["error"]
    assert rows["b.SLDPRT"]["status"] == "ok"
    assert len((out / "report.jsonl").read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.skipif(not WINDOWS, reason="directory junctions")
def test_batch_does_not_follow_junctions(tmp_path, capsys):
    import _winapi

    src = _copy(tmp_path).parent
    loop = src / "loop"
    _winapi.CreateJunction(str(src), str(loop))
    try:
        assert (loop / "part.SLDPRT").is_file()  # control: the junction does lead to a document
        out = tmp_path / "out"
        code = cli.main(["batch", str(src), "-o", str(out), "--no-parasolid", "--json"])
        env = json.loads(capsys.readouterr().out)
        assert code == 0 and env["data"]["files"] == 1 and env["data"]["walk"]["links"] == 1
        with open(out / "report.csv", encoding="utf-8", newline="") as fh:
            assert [r["file"] for r in csv.DictReader(fh)] == ["part.SLDPRT"]
    finally:
        os.rmdir(loop)


def test_unconvertible_preview_is_a_format_error():
    pytest.importorskip("PIL")
    from solidseas.formats.solidworks.preview import convert_image

    with pytest.raises(SldFormatError):
        convert_image(b"\x89PNG\r\n\x1a\n not really", "BMP")
