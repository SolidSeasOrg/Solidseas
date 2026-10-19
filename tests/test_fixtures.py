"""Checks on the synthetic fixtures themselves.

These pin down facts the format readers rely on, using only the exports that
SOLIDWORKS wrote alongside the native files. Reader tests build on top of them.
"""

import struct
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
NATIVE = sorted(p for p in FIXTURES.iterdir() if p.suffix.upper() in {".SLDPRT", ".SLDASM", ".SLDDRW"})
PARASOLID_HEADER = b"**ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"


def test_all_expected_fixtures_present():
    names = {p.name for p in FIXTURES.iterdir()}
    for expected in (
        "o01_empty.SLDPRT",
        "o02_boxA.SLDPRT",
        "o03_boxA_again.SLDPRT",
        "o04_boxA_props.SLDPRT",
        "o05_boxA_props_mat.SLDPRT",
        "o06_boxA_props_mat_cfg.SLDPRT",
        "o07_boxB_h31.SLDPRT",
        "o08_asm_2x_boxA.SLDASM",
        "o09_import_step.SLDPRT",
        "o10_import_step_cut.SLDPRT",
        "o11_curved.SLDPRT",
        "o12_multibody.SLDPRT",
        "o13_two_geometry_configs.SLDPRT",
        "o14_property_types.SLDPRT",
        "o15_sub_asm.SLDASM",
        "o16_asm_features.SLDASM",
        "o17_деталь.SLDPRT",
        "o18_drw_boxA.SLDDRW",
        "o19_drw_asm.SLDDRW",
        "o02_boxA.x_t",
        "o02_boxA.x_b",
        "o07_boxB_h31.x_b",
        "o11_curved.x_b",
        "o12_multibody.x_b",
        "o02_boxA.step",
        "o02_boxA.STL",
        "o02_boxA.3mf",
        "ground_truth.json",
        "generation.log",
        "scrub_report.txt",
        "SHA256SUMS.txt",
    ):
        assert expected in names


def test_fixture_files_match_the_kit_checksums():
    """SHA256SUMS.txt is the fixture kit's own list; every file it names is committed unchanged."""
    import hashlib

    lines = (FIXTURES / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    listed = dict(reversed(line.split("  ", 1)) for line in lines if line.strip())
    assert len(listed) == 30
    for name, digest in listed.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name
    on_disk = {p.name for p in FIXTURES.iterdir() if p.is_file()}
    # The private overlay (support.ground_truth) is not one of the kit's files.
    assert on_disk - set(listed) - {"ground_truth.private.json"} == {"README.md", "SHA256SUMS.txt"}


def test_files_made_by_script_match_their_checksums():
    """``tests/generated`` holds files a script there writes (fixtures/README.md, Files made
    by script), each listed in its own SHA256SUMS.txt."""
    import hashlib

    folder = FIXTURES.parent / "generated"
    lines = (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    listed = dict(reversed(line.split("  ", 1)) for line in lines if line.strip())
    assert set(listed) == {p.name for p in folder.iterdir() if p.is_file()} - {"SHA256SUMS.txt"}
    for name, digest in listed.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


def test_every_native_fixture_is_checked():
    assert len(NATIVE) == 19 and {p.suffix.upper() for p in NATIVE} == {".SLDPRT", ".SLDASM", ".SLDDRW"}


@pytest.mark.parametrize("path", NATIVE, ids=lambda p: p.name)
def test_native_files_use_the_2015_container(path):
    """Bytes 4 to 7 are 00 00 00 04 in every file saved by SOLIDWORKS 2015 and later."""
    head = path.read_bytes()[:8]
    assert head[4:8] == b"\x00\x00\x00\x04"


def test_resaving_unchanged_document_changes_bytes():
    """o03 is o02 saved again with no edits. Readers must not assume identical bytes."""
    a = (FIXTURES / "o02_boxA.SLDPRT").read_bytes()
    b = (FIXTURES / "o03_boxA_again.SLDPRT").read_bytes()
    assert a != b


@pytest.mark.parametrize("name", ["o02_boxA.x_t", "o02_boxA.x_b", "o07_boxB_h31.x_b"])
def test_parasolid_exports_carry_transmit_header(name):
    assert (FIXTURES / name).read_bytes().startswith(PARASOLID_HEADER)


def test_parasolid_differs_between_boxes():
    assert (FIXTURES / "o02_boxA.x_b").read_bytes() != (FIXTURES / "o07_boxB_h31.x_b").read_bytes()


def test_step_export_header():
    assert (FIXTURES / "o02_boxA.step").read_bytes().startswith(b"ISO-10303-21;")


def _stl_triangles(data):
    count = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + 50 * count
    for i in range(count):
        base = 84 + i * 50
        yield [struct.unpack_from("<3f", data, base + 12 + 12 * k) for k in range(3)]


def _signed_volume(a, b, c):
    """Signed volume of the tetrahedron from the origin to triangle abc."""
    cross = (b[1] * c[2] - c[1] * b[2], c[0] * b[2] - b[0] * c[2], b[0] * c[1] - c[0] * b[1])
    return (a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]) / 6.0


def test_stl_matches_solidworks_mass_properties():
    """SOLIDWORKS reported 6.0e-6 m^3 for box A; the exported mesh must agree (STL is in mm)."""
    tris = list(_stl_triangles((FIXTURES / "o02_boxA.STL").read_bytes()))
    assert len(tris) == 12
    volume = sum(_signed_volume(a, b, c) for a, b, c in tris)
    assert volume == pytest.approx(6000.0, rel=1e-6)
    xs, ys, zs = zip(*(p for t in tris for p in t), strict=True)
    assert (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) == pytest.approx((10.0, 20.0, 30.0))


def test_3mf_package_contents():
    with zipfile.ZipFile(FIXTURES / "o02_boxA.3mf") as z:
        names = set(z.namelist())
    assert {"3D/3dmodel.model", "Metadata/thumbnail.png"} <= names


def test_package_version_is_semver():
    import re

    import solidseas

    assert re.fullmatch(r"\d+\.\d+\.\d+", solidseas.__version__)
