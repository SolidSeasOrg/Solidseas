"""The legacy OLE path, on a synthetic compound file.

No legacy SOLIDWORKS file can be committed, so this test builds one: the
decoded streams of fixture o06 are placed in an MS-CFB file the way legacy
documents store them (``__ZLB`` wrapping, MS-OLEPS property sets, lower-case
``config-N`` names), and the reader must recover the same facts. Property sets
in 8-bit code pages carry planted accented and non-Latin paths, which the path
report must read whole.
"""

import pytest

from builders import build_cfb, build_propset, wrap_zlb
from solidseas.formats.solidworks import SldFormatError, open_container, open_document
from solidseas.formats.solidworks import parasolid as ps
from solidseas.formats.solidworks.propset import FMTID_DOCSUMMARY, FMTID_SUMMARY, FMTID_USERDEFINED
from solidseas.formats.solidworks.zlb import ZLB_MAGIC
from support import fixture_path

VT_I4, VT_LPSTR = 3, 0x1E


def _legacy_bytes(isw: tuple[list, dict] | None = None, extra: dict[str, bytes] | None = None) -> bytes:
    """o06's streams in a legacy compound file, with ``extra`` streams added or replaced."""
    with open_container(fixture_path("o06_boxA_props_mat_cfg.SLDPRT")) as c:
        plain = {
            name: c.read(name)
            for name in (
                "Contents/Definition",
                "Header2",
                "_MO_VERSION_17000/History",
                "Contents/Config-0-Partition",
                "PreviewPNG",
                "Preview",
            )
        }
        wrapped = {
            name + "__ZLB": wrap_zlb(c.read(name))
            for name in (
                "swXmlContents/KeyWords",
                "swXmlContents/Features",
                "swXmlContents/MATERIALTREE",
                "Contents/DisplayLists",
            )
        }
    streams = {**plain, **wrapped}
    streams["\x05SummaryInformation"] = build_propset(
        [
            (
                FMTID_SUMMARY,
                [(2, VT_LPSTR, "Legacy box"), (4, VT_LPSTR, "tester"), (8, VT_LPSTR, "tester")],
                None,
            )
        ]
    )
    streams["\x05DocumentSummaryInformation"] = build_propset(
        [
            (FMTID_DOCSUMMARY, [], None),
            (
                FMTID_USERDEFINED,
                [(2, VT_LPSTR, "ORACLE-PN-123"), (3, VT_I4, 42)],
                {2: "PartNo", 3: "Qty"},
            ),
        ]
    )
    streams["config-1-properties"] = build_propset(
        [(FMTID_USERDEFINED, [(2, VT_LPSTR, "ALT-VALUE")], {2: "CfgOnly"})]
    )
    isw_props, isw_names = isw or (
        [(2, VT_LPSTR, "Default"), (3, VT_LPSTR, "tester")],
        {2: "SW-Configuration Name", 3: "SW-Autor(Author)"},
    )
    streams["ISolidWorksInformation"] = build_propset([(FMTID_USERDEFINED, isw_props, isw_names)])
    streams.update(extra or {})
    return build_cfb(streams)


@pytest.fixture(scope="module")
def legacy() -> bytes:
    return _legacy_bytes()


def test_container_lists_and_unwraps_streams(legacy):
    with open_container(legacy) as c:
        assert c.format == "ole"
        info = c.info("swXmlContents/KeyWords")  # alias for the __ZLB name
        assert info.name == "swXmlContents/KeyWords__ZLB" and info.codec == "zlb"
        assert c.read_raw(info.name).startswith(ZLB_MAGIC)
        assert c.read("swXmlContents/KeyWords")[:1] == b"\x86"
        assert c.info("SummaryInformation").name == "\x05SummaryInformation"
        assert c.info("Config-1-Properties").name == "config-1-properties"
        small = c.read("Contents/Definition")  # held in the mini stream
        big = c.read("Preview")  # held in regular sectors
        assert len(small) < 4096 <= len(big)
    with open_container(fixture_path("o06_boxA_props_mat_cfg.SLDPRT")) as m:
        assert big == m.read("Preview")


def test_metadata_from_property_sets(legacy):
    with open_document(legacy) as doc:
        assert doc.format == "ole"
        assert doc.doc_type == "part"
        assert {p.name: (p.value, p.type) for p in doc.properties} == {
            "PartNo": ("ORACLE-PN-123", "text"),
            "Qty": (42, "number"),
        }
        assert [c.name for c in doc.configurations] == ["Default", "OracleAlt"]
        alt = doc.configurations[1]
        assert alt.comment == "oracle alt config"
        assert [(p.name, p.value) for p in alt.properties] == [("CfgOnly", "ALT-VALUE")]
        assert doc.active_configuration == "Default"
        assert doc.material == "1060 Alloy"
        summary = doc.metadata.summary
        assert summary["title"] == "Legacy box"
        assert summary["author"] == "tester"
        assert doc.metadata.checks["configuration_names_tree_vs_keywords"] is True
        assert doc.saved_version.format_version == 17000


def test_conflicting_localised_configuration_names_follow_the_tree():
    # A stale English copy and a current localised copy of the active configuration name.
    # The configuration tree marks Default as most recently used.
    data = _legacy_bytes(
        (
            [(2, VT_LPSTR, "OracleAlt"), (3, VT_LPSTR, "Default"), (4, VT_I4, 5)],
            {2: "SW-Configuration Name", 3: "SW-Konfigurationsname(Configuration Name)", 4: "SW_UnitSystem"},
        )
    )
    with open_document(data) as doc:
        assert doc.active_configuration == "Default"
        assert doc.metadata.units["raw"] == {"SW_UnitSystem": 5}


def test_geometry_preview_and_mesh(legacy):
    ref = ps.read_file(fixture_path("o02_boxA.x_b").read_bytes())
    with open_document(legacy) as doc:
        bodies = doc.parasolid().bodies
        assert len(bodies) == 1
        assert ps.compare_brep(ps.read_file(bodies[0].x_b("box")), ref)["identical"]
        pv = doc.preview()
        assert (pv.mime, pv.width, pv.height) == ("image/png", 640, 480)
        mesh = doc.mesh()
        assert mesh.stream == "Contents/DisplayLists__ZLB"
        assert mesh.volume() == pytest.approx(6.0e-6, rel=1e-6)


def test_zlb_name_without_magic():
    doc = build_cfb({"Contents/Broken__ZLB": b"not a zlb block" * 10, "Header2": b"\0" * 10})
    with pytest.raises(SldFormatError):
        open_container(doc)
    with open_container(doc, strict=False) as c:
        assert c.read("Contents/Broken__ZLB") == b"not a zlb block" * 10
        assert any("ZLB magic is missing" in w for w in c.warnings)


# --------------------------------------------------------------------------- 8-bit paths
# Each planted path sits in a property set section of its own 8-bit code page: accented
# letters in cp1252, Cyrillic in cp1251, Japanese in cp932, where the folder's last
# character (U+8868) ends in the byte 0x5C, a backslash.
FOLDER_1252 = "C:\\Users\\Public\\Documents\\Zq7Jos\u00e9\\Gr\u00f6\u00dfe M\u00fcller\\"
P_1251 = "D:\\Zq7\u0414\u0435\u0442\u0430\u043b\u0438\\\u043a\u043e\u0440\u043f\u0443\u0441.SLDPRT"
P_932 = "E:\\Zq7\u56f3\u9762\u8868\\\u90e8\u54c1.SLDPRT"


@pytest.fixture(scope="module")
def legacy_8bit() -> bytes:
    isw = [(2, VT_LPSTR, "Default"), (3, VT_LPSTR, FOLDER_1252), (4, VT_LPSTR, "teil.SLDPRT")]
    isw_names = {2: "SW-Configuration Name", 3: "SW-Folder Name", 4: "SW-File Name"}
    custom = [(2, VT_LPSTR, "ORACLE-PN-123"), (3, VT_I4, 42), (4, VT_LPSTR, P_1251)]
    custom_names = {2: "PartNo", 3: "Qty", 4: "Zq7Source"}
    cfg = [(2, VT_LPSTR, "ALT-VALUE"), (3, VT_LPSTR, P_932)]
    extra = {
        "ISolidWorksInformation": build_propset([(FMTID_USERDEFINED, isw, isw_names, 1252)]),
        "\x05DocumentSummaryInformation": build_propset(
            [(FMTID_DOCSUMMARY, [], None), (FMTID_USERDEFINED, custom, custom_names, 1251)]
        ),
        "config-1-properties": build_propset([(FMTID_USERDEFINED, cfg, {2: "CfgOnly", 3: "Zq7Drw"}, 932)]),
    }
    return _legacy_bytes(extra=extra)


def test_8bit_property_sets_are_read_in_their_code_pages(legacy_8bit):
    """The bytes really are 8-bit: none of the planted paths is UTF-8 there."""
    with open_document(legacy_8bit) as doc:
        for stream, path, codec in (
            ("ISolidWorksInformation", FOLDER_1252, "cp1252"),
            ("\x05DocumentSummaryInformation", P_1251, "cp1251"),
            ("config-1-properties", P_932, "cp932"),
        ):
            data = doc.read_stream(stream)
            assert path.encode(codec) in data and path.encode("utf-8") not in data, stream
        assert doc.metadata.summary["folder_at_save"] == FOLDER_1252
        assert {p.name: p.value for p in doc.properties}["Zq7Source"] == P_1251
        alt = {p.name: p.value for p in doc.configurations[1].properties}
        assert alt["Zq7Drw"] == P_932


def test_path_report_reads_8bit_paths_whole(legacy_8bit):
    with open_document(legacy_8bit) as doc:
        rep = doc.path_report()
    found = {p.path.rstrip("\\"): p for p in rep.paths}
    for planted in (FOLDER_1252, P_1251, P_932):
        whole = planted.rstrip("\\")
        assert whole in found, planted
        # no copy cut short at the first byte that is not ASCII, as the scan gave before
        assert [p for p in found if whole.startswith(p) and p != whole] == [], planted
    folder = found[FOLDER_1252.rstrip("\\")]
    assert folder.sources == ("save_folder", "scan") and "save_location" in folder.roles
    assert found[P_1251].sources == ("scan",) and found[P_932].sources == ("scan",)
    assert found[P_1251].locations[0].stream == "\x05DocumentSummaryInformation"
    assert found[P_932].locations[0].stream == "config-1-properties"
    assert rep.complete
