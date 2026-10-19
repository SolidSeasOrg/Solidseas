"""The path-leak report (``docs/API.md`` section 5.11) and the byte scan behind it.

Every planted value below is synthetic and distinctive (``zq7``), so a test that
finds it found what it planted. The leak test follows the
``leak-test-raw-html-words`` rule: the planted values must appear in the raw
output of every surface, nothing stripped, so the test cannot pass by the report
saying nothing. ``test_components_ground_truth.py`` checks the report against the fixture
kit's own scrub expectations.
"""

import json
import re
import struct
import time

import pytest

from builders import (
    TreeXml,
    assembly_with_tree,
    build_modern,
    build_propset,
    fixture_streams,
    rebuild,
    resolving_assembly,
)
from jsonschema_subset import validate
from solidseas import InvalidArgumentError, cli, model, open_document
from solidseas.formats.solidworks import container as container_mod
from solidseas.formats.solidworks.metadata import read_cstring
from solidseas.formats.solidworks.pathreport import (
    CATEGORIES,
    REWRITE_NOTE,
    ROLES,
    account_of,
    categorize,
    severity,
)
from solidseas.formats.solidworks.paths import _is_text, _path_char, is_noise, scan_bytes
from solidseas.formats.solidworks.propset import FMTID_USERDEFINED
from support import ASSEMBLY, NATIVE, fixture_path

O02 = fixture_path("o02_boxA.SLDPRT")
O08 = fixture_path(ASSEMBLY)
BIO = "_MO_VERSION_17000/Biography"

ACCOUNT = "zq7plant"
HOST, SHARE = "zq7files", "eng"
P_CSTRING = (
    "D:\\Zq7Jobs\\Kunde \u00c4r\u00f8\\\u041f\u0440\u043e\u0435\u043a\u0442 \u88fd\u56f3\\bracket-7.SLDPRT"
)
P_FREE16 = "F:\\Zq7Frei\\Gr\u00f6\u00dfe\\Zeichnung.SLDDRW"
P_UTF8 = "E:\\Zq7Daten\\Gr\u00f6\u00dfe \u5bf8\u6cd5\\note.txt"
P_ACCOUNT = f"C:\\Users\\{ACCOUNT}\\Documents\\Zq7Work\\plate.SLDPRT"
P_UNC = f"\\\\{HOST}\\{SHARE}\\Zq7Shared\\frame.SLDASM"
P_NESTED = "G:\\Zq7Nested\\\u00dcnter\\deep.SLDPRT"
P_DEEP = "H:\\Zq7Deeper\\\u0414\u0435\u0442\u0430\u043b\u044c\\inner.SLDPRT"
USER_H2, USER_AUTHOR, USER_CORE, USER_LAST = "zq7header2user", "zq7author", "zq7coresaver", "zq7lastsaver"
USER_NESTED = "zq7nesteduser"
# UTF-16 units that read as CJK letters: what a scan of "any letter" would run on into
GARBAGE = "\u4e00\u4e01\u4e02".encode("utf-16-le") + b"\x00\x00"


def cstring(text: str) -> bytes:
    raw = text.encode("utf-16-le")
    n = len(text)
    head = bytes([n]) if n < 0xFF else b"\xff" + struct.pack("<H", n)
    return b"\xff\xfe\xff" + head + raw


def with_users(header2: bytes, users: list[str]) -> bytes:
    """``Header2`` with its user list replaced."""
    marker = b"su_CStringArray"
    i = header2.index(marker) + len(marker)
    (n,) = struct.unpack_from("<H", header2, i)
    q = i + 2
    for _ in range(n):
        _s, q = read_cstring(header2, q)
    return header2[:i] + struct.pack("<H", len(users)) + b"".join(cstring(u) for u in users) + header2[q:]


def with_identity(streams: dict[str, bytes], *, core=None, author=None, last=None, users=None) -> dict:
    out = {}
    if core is not None:
        xml = streams["docProps/core.xml"]
        new, n = re.subn(rb"<dc:lastModifiedBy>[^<]*<", b"<dc:lastModifiedBy>" + core.encode() + b"<", xml)
        assert n == 1
        out["docProps/core.xml"] = new
    isw = streams["docProps/ISolidWorksInformation.xml"]
    for name, value in (("SW-Author", author), ("SW-Last Saved By", last)):
        if value is None:
            continue
        rx = rb'(<property name="' + name.encode() + rb'" pid="\d+"><vt:lpstr>)[^<]*<'
        isw, n = re.subn(rx, lambda m, v=value: m.group(1) + v.encode() + b"<", isw)
        assert n == 1, name
    out["docProps/ISolidWorksInformation.xml"] = isw
    if users is not None:
        out["Header2"] = with_users(streams["Header2"], users)
    return out


def planted_part() -> bytes:
    """o02 with every kind of planted value: a non-ASCII path in a Biography CString
    followed by bytes that read as letters, a free UTF-16 path, a UTF-8 path, a path
    naming an account, a UNC path, and four user names."""
    s = fixture_streams(O02)
    extra = (
        b"\x00\x00"
        + P_FREE16.encode("utf-16-le")
        + b"\x00\x00\x07\x00"
        + cstring(P_ACCOUNT)
        + b"\x00"
        + cstring(P_UNC)
        + b'\x00<note v="'
        + P_UTF8.encode("utf-8")
        + b'"/>\x00'
    )
    changes = {BIO: s[BIO] + cstring(P_CSTRING) + GARBAGE, "Contents/Zq7Extra": extra}
    changes.update(with_identity(s, core=USER_CORE, author=USER_AUTHOR, last=USER_LAST, users=[USER_H2]))
    return rebuild(O02, changes)


def nested_part(path: str = P_NESTED, user: str = USER_NESTED) -> bytes:
    s = fixture_streams(O02)
    changes = {BIO: s[BIO] + cstring(path) + GARBAGE}
    changes.update(with_identity(s, core=user))
    return rebuild(O02, changes)


def with_virtual(member_name: str, member: bytes) -> bytes:
    t = TreeXml()
    t.file("2", "C:\\Temp\\VC~~\\top\\Zq7Virtual^top.SLDPRT")
    t.top("m1")
    t.model("m2", "2")
    t.ref("m1", "Zq7Virtual^top", 1, "m2", virtual=True)
    return assembly_with_tree(t, {member_name: member})


def by_path(rep) -> dict:
    return {p.path: p for p in rep.paths}


# --------------------------------------------------------------------------- the byte scan
def test_scan_reads_non_ascii_paths_whole_and_without_a_tail():
    data = (
        b"\x01\x02"
        + cstring(P_CSTRING)
        + GARBAGE
        + P_FREE16.encode("utf-16-le")
        + b"\x00\x00"
        + b'<x v="'
        + P_UTF8.encode("utf-8")
        + b'"/>'
    )
    found = scan_bytes(data)
    assert (P_CSTRING, "cstring") in found
    assert (P_FREE16, "utf16") in found
    # outside a stored string a path ends at the first character a path cannot hold,
    # such as a byte-order mark, even when letters follow it
    bom = b"\x00\x00" + (P_FREE16 + "\ufeff\u4e00\u4e01").encode("utf-16-le") + b"\x00\x00"
    assert scan_bytes(bom) == [(P_FREE16, "utf16")]
    assert (P_UTF8, "utf8") in found
    for planted in (P_CSTRING, P_FREE16, P_UTF8):
        assert [p for p, _ in found if p.startswith(planted)] == [planted], planted
    # the bytes after the CString do read as path characters, so only the stored length
    # stops the path there: without the CString marker the same bytes give a tail
    assert all(_path_char(ch) for ch in "\u4e00\u4e01\u4e02")
    unmarked = data.replace(b"\xff\xfe\xff", b"\x00\x00\x00", 1)
    tails = [p for p, _ in scan_bytes(unmarked) if p.startswith(P_CSTRING) and p != P_CSTRING]
    assert tails == [P_CSTRING + "\u4e00\u4e01\u4e02"]


def test_ff_fe_ff_inside_binary_data_does_not_hide_the_strings_it_would_cover():
    """A false marker whose "length" runs over real strings (seen once on the corpus): its
    text holds a byte-order mark and control characters, so it is not a string, and the
    real strings it covers are read from their own markers, without a tail."""
    real = "脴".encode("utf-16-le") + cstring(P_CSTRING) + "脴".encode("utf-16-le")
    false = b"\xff\xfe\xff\xff\x00\x01" + b"\x01\x00\x02\x00" + real + b"\xff\xfe\xff\x14" + bytes(600)
    found = scan_bytes(false)
    assert [p for p, _ in found if p.startswith(P_CSTRING)] == [P_CSTRING]
    assert (P_CSTRING, "cstring") in found


def test_what_reads_as_a_stored_string():
    assert _is_text(P_CSTRING) and _is_text("C:\\a\tb\r\n") and _is_text("D:\\\uff21\u30ff")
    for bad in ("\x01", "\ufeff", "\ud800", "\ue000", "\ufffd", "\uffff", "\u0378"):  # \u0378: unassigned
        assert not _is_text("C:\\x" + bad), repr(bad)


def test_the_01_scan_cut_these_paths_at_their_first_non_ascii_character():
    """What the upgrade fixes: the ASCII-only scan of 0.1 saw only the start of each."""
    u16_ascii = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
    old = [m.group().decode("utf-16-le") for m in u16_ascii.finditer(cstring(P_CSTRING))]
    assert old and P_CSTRING not in old and P_CSTRING.startswith(old[0].lstrip("\x00 "))


def test_noise_is_dropped_and_long_runs_stay_bounded():
    assert is_noise("f:\\!") and is_noise("y:\\w") and is_noise("\\\\F=^\\")
    assert not is_noise("D:\\Zq7Jobs") and not is_noise("C:\\\u88fd\u56f3\u9762")
    assert scan_bytes(b"\x00f\x00:\x00\\\x00!\x00\x00\x00") == []
    # inside a CString the stored length says where the text ends, so nothing is noise there
    assert scan_bytes(cstring("C:\\\u88fd\u56f3")) == [("C:\\\u88fd\u56f3", "cstring")]
    hostile = b"C\x00:\x00\\\x00" * (1 << 18) + b"\xff\xfe\xff\xff\xff\xff" * (1 << 16) + b"\\\\" * (1 << 18)
    t0 = time.perf_counter()
    found = scan_bytes(hostile)
    assert time.perf_counter() - t0 < 10
    assert all(len(p) <= 32_767 for p, _ in found)


# --------------------------------------------------------------------------- 8-bit strings
P_8BIT = "F:\\Zq7Jobs\\Caf\u00e9 Noir\\Gr\u00f6\u00dfe\\teil.SLDPRT"
P_CYRILLIC = "G:\\Zq7\u0414\u0435\u0442\u0430\u043b\u0438\\\u043a\u043e\u0440\u043f\u0443\u0441.SLDPRT"


def counted(text: str, codec: str = "cp1252", *, pad: int = 0, count: int | None = None) -> bytes:
    """An MS-OLEPS CodePageString: a u32 byte count, the text, a NUL and ``pad`` NULs the
    count includes."""
    raw = text.encode(codec) + b"\0" * (1 + pad)
    return struct.pack("<I", len(raw) if count is None else count) + raw


def propset_with(text: str, codepage: int, codec: str) -> bytes:
    """A one-section property set declaring ``codepage``, with one string property."""
    data = build_propset([(FMTID_USERDEFINED, [(2, 0x1E, text)], {2: "Zq7Path"}, codepage)])
    assert text.encode(codec) in data
    return data


def test_counted_8bit_strings_are_read_whole_in_their_code_page():
    # no code page declared: cp1252
    assert scan_bytes(b"\x01\x02" + counted(P_8BIT) + b"\x07\xe9\xe8 tail") == [(P_8BIT, "ansi")]
    # the path need not open the string, and the count may include padding
    assert scan_bytes(b"\x1e\x00\x00\x00" + counted("Folder: " + P_8BIT, pad=3)) == [(P_8BIT, "ansi")]
    # a property set says its code page; without it the same bytes read as cp1252 letters
    cyrillic = propset_with(P_CYRILLIC, 1251, "cp1251")
    assert scan_bytes(cyrillic) == [(P_CYRILLIC, "ansi")]
    as_cp1252 = P_CYRILLIC.encode("cp1251").decode("cp1252")
    assert scan_bytes(counted(P_CYRILLIC, "cp1251")) == [(as_cp1252, "ansi")]
    # a UTF-8 section, or valid UTF-8 where nothing is declared, is read as UTF-8, as before
    assert scan_bytes(propset_with(P_8BIT, 65001, "utf-8")) == [(P_8BIT, "utf8")]
    assert scan_bytes(b"\x01" + counted(P_8BIT, "utf-8")) == [(P_8BIT, "utf8")]
    # a counted string is a stored string: a short path in it is not noise
    assert scan_bytes(b"\x01" + counted("Q:\\\u00dc")) == [("Q:\\\u00dc", "ansi")]


def test_a_declared_8bit_code_page_wins_over_utf8():
    """A section that declares an 8-bit code page is read in it, as the property set
    reader reads it, even where its bytes would also be valid UTF-8 (MS-OLEPS); the same
    bytes outside a property set read as UTF-8. Pure ASCII reads the same either way and
    is left to the UTF-8 pass."""
    as_utf8 = "F:\\Zq7Jobs\\Caf\u00e9\\a.SLDPRT"
    stored = as_utf8.encode("utf-8").decode("cp1252")  # the bytes C3 A9 in cp1252: "\u00c3\u00a9"
    assert scan_bytes(propset_with(stored, 1252, "cp1252")) == [(stored, "ansi")]
    assert scan_bytes(b"\x01" + counted(as_utf8, "utf-8")) == [(as_utf8, "utf8")]
    ascii_path = "F:\\Zq7Jobs\\Plain\\a.SLDPRT"
    assert scan_bytes(propset_with(ascii_path, 1252, "cp1252")) == [(ascii_path, "utf8")]


def test_8bit_text_without_a_count_and_a_nul_is_not_read_past_ascii():
    """Only the count and the NUL say where 8-bit text ends, so without them nothing
    runs on into the bytes after the path: those cases read as before, to the first
    byte that is not UTF-8."""
    cut = "F:\\Zq7Jobs\\Caf"
    raw = P_8BIT.encode("cp1252")
    undefined = raw.replace(b"\xe9", b"\xe9\x81")  # 0x81 is not a cp1252 character
    cases = [
        b"\x05\x00\x00\x00\x00" + raw + b"\x00",  # no count
        b"\x01" + counted(P_8BIT, count=len(raw) + 9),  # a count that is not the string's
        b"\x01" + counted(P_8BIT, pad=4) + bytes(8),  # four NULs of padding: one more than allowed
        b"\x01" + counted(P_8BIT)[:-1] + b"\x03\xe9\xe8",  # ends at a control byte, not a NUL
        b"\x01" + struct.pack("<I", len(undefined) + 1) + undefined + b"\x00",
    ]
    for data in cases:
        assert scan_bytes(data) == [(cut, "utf8")], data[:12]


def test_the_8bit_pass_looks_at_each_run_of_text_once():
    many = (b"\x00" + b"x" * 100 + b"C:\\Zq7\xe9\x00") * 20_000  # each needs the search back
    long_run = b"\x00\x00\x00\x00" + (b"C:\\Zq7" + b"\xe9" * 50) * 20_000 + b"\x00"
    t0 = time.perf_counter()
    assert scan_bytes(many) == [("C:\\Zq7", "utf8")] * 20_000
    assert scan_bytes(long_run) == [("C:\\Zq7", "utf8")] * 20_000
    assert time.perf_counter() - t0 < 10


# --------------------------------------------------------------------------- classification
CATEGORY_TABLE = [
    ("\\\\fs01\\eng\\jobs\\a.SLDPRT", "unc", "fs01", "eng", None),
    ("\\\\fs01@SSL@443\\DavWWWRoot\\x", "unc", "fs01", "DavWWWRoot", None),
    ("\\\\?\\UNC\\fs02\\data\\x", "unc", "fs02", "data", None),
    ("\\\\host\\share\\Users\\bob\\x", "unc", "host", "share", "bob"),
    ("\\\\?\\C:\\Jobs\\x\\y.sldprt", "project", None, None, None),
    ("C:/Jobs/A/b.sldprt", "project", None, None, None),
    ("D:\\Jobs\\A", "project", None, None, None),
    ("D:\\", "drive_root", None, None, None),
    ("D:\\Jobs", "drive_root", None, None, None),
    ("C:\\Users\\Public\\Documents\\x", "profile", None, None, None),
    ("C:\\Users\\zq\\Documents\\Jobs", "profile", None, None, "zq"),
    ("C:\\Users\\Default\\AppData\\Local\\Temp\\x", "temp", None, None, None),
    ("C:\\Users\\zq\\AppData\\Local\\Temp\\swx1\\VC~~\\a", "temp", None, None, "zq"),
    ("C:\\Documents and Settings\\zq\\Local Settings\\Temp\\", "temp", None, None, "zq"),
    ("C:\\Documents and Settings\\zq\\Desktop\\a", "desktop", None, None, "zq"),
    ("C:\\Documents and Settings\\All Users\\Desktop", "desktop", None, None, None),
    ("C:\\Users\\Default User\\x", "profile", None, None, None),
    ("C:\\Windows\\system32\\", "windows", None, None, None),
    ("C:\\WINNT\\fonts", "windows", None, None, None),
    ("C:\\Windows\\Temp\\x", "temp", None, None, None),
    ("C:\\Temp\\VC~~\\a", "temp", None, None, None),
    ("C:\\Program Files (x86)\\x", "program", None, None, None),
    ("C:\\ProgramData\\SolidWorks\\x", "program", None, None, None),
]


@pytest.mark.parametrize(("path", "category", "host", "share", "account"), CATEGORY_TABLE)
def test_categories_hosts_and_accounts(path, category, host, share, account):
    assert categorize(path) == (category, host, share)
    assert account_of(path) == account


def test_the_category_table_covers_every_category():
    assert len(CATEGORY_TABLE) >= 20
    assert {row[1] for row in CATEGORY_TABLE} == set(CATEGORIES)


def test_severity_rules_in_order():
    assert severity("unc", ("history",), None, False) == ("high", "unc_share")
    assert severity("temp", ("references",), "zq", False) == ("high", "referenced_document")
    assert severity("profile", ("imported_from",), "zq", False) == ("high", "referenced_document")
    assert severity("temp", ("save_location", "history"), "zq", False) == ("high", "save_location")
    assert severity("project", ("history",), None, False) == ("high", "folder_names")
    assert severity("temp", ("history",), "zq", False) == ("medium", "account_name")
    # critique 3.13: an account probably inherited from a template is not ranked lower
    assert severity("temp", ("history",), "zq", True) == ("medium", "inherited_template")
    assert severity("profile", ("history",), None, False) == ("medium", "profile_folder")
    assert severity("windows", ("history",), None, False) == ("low", "standard_folder")


# --------------------------------------------------------------------------- the report on crafted files
def test_planted_paths_are_found_whole_with_their_roles():
    with open_document(planted_part(), name="planted.SLDPRT") as doc:
        rep = doc.path_report()
    paths = by_path(rep)
    assert rep.complete and rep.incomplete == ()
    for planted in (P_CSTRING, P_FREE16, P_UTF8, P_ACCOUNT, P_UNC):
        assert planted in paths, planted
        assert [p for p in paths if p.casefold().startswith(planted.casefold())] == [planted]
    assert paths[P_CSTRING].roles == ("history",) and paths[P_CSTRING].sources == ("biography",)
    assert (paths[P_CSTRING].category, paths[P_CSTRING].severity) == ("project", "high")
    assert paths[P_ACCOUNT].account == ACCOUNT and paths[P_ACCOUNT].roles == ("references",)
    assert (paths[P_UNC].host, paths[P_UNC].share, paths[P_UNC].reason) == (HOST, SHARE, "unc_share")
    assert paths[P_UTF8].roles == ("other",) and paths[P_UTF8].sources == ("scan",)
    hosts = {h.host: h for h in rep.hosts}
    assert hosts[HOST].shares == (SHARE,) and hosts[HOST].severity == "high"
    fields = {(f.field, f.value) for f in rep.identity_fields}
    assert {
        ("header2_user", USER_H2),
        ("core_last_modified_by", USER_CORE),
        ("sw_author", USER_AUTHOR),
        ("sw_last_saved_by", USER_LAST),
    } <= fields
    accounts = {a.name: a for a in rep.accounts}
    assert {ACCOUNT, USER_H2, USER_CORE, USER_AUTHOR, USER_LAST} <= set(accounts)
    assert all(a.severity == "medium" for a in rep.accounts)


def test_every_category_and_role_is_counted():
    with open_document(planted_part()) as doc:
        rep = doc.path_report()
    counts = rep.counts()
    assert list(counts["by_category"]) == list(CATEGORIES) and list(counts["by_role"]) == list(ROLES)
    assert sum(counts["by_category"].values()) == counts["paths"] == len(rep.paths) > 5
    for cat in ("unc", "project", "profile", "temp", "program", "windows"):
        assert counts["by_category"][cat] >= 1, cat
    assert sum(counts["by_role"].values()) >= counts["paths"]


def test_an_account_seen_only_in_history_is_inherited_and_stays_medium():
    s = fixture_streams(O02)
    template_path = "C:\\Users\\zq7tmplauthor\\AppData\\Local\\Temp\\"
    bio = s[BIO] + cstring(template_path)
    only_history = rebuild(O02, {BIO: bio, **with_identity(s, users=["zq7oldsaver"])})
    with open_document(only_history) as doc:
        rep = doc.path_report()
    accounts = {a.name: a for a in rep.accounts}
    author = accounts["zq7tmplauthor"]
    assert (author.history_only, author.inherited_likely, author.severity) == (True, True, "medium")
    assert accounts["zq7oldsaver"].inherited_likely and not accounts["zq7oldsaver"].history_only
    p = by_path(rep)[template_path]
    assert (p.history_only, p.inherited_likely, p.severity, p.reason) == (
        True,
        True,
        "medium",
        "inherited_template",
    )
    # the control: the same account as the current author is not inherited
    current = rebuild(O02, {BIO: bio, **with_identity(s, author="zq7tmplauthor")})
    with open_document(current) as doc:
        rep = doc.path_report()
    author = {a.name: a for a in rep.accounts}["zq7tmplauthor"]
    assert (author.history_only, author.inherited_likely) == (True, False)
    assert by_path(rep)[template_path].reason == "account_name"


def test_a_nested_documents_paths_and_names_are_included():
    asm = with_virtual("VirtualComp/Zq7Virtual-sldprt", nested_part())
    with open_document(asm, name="top.SLDASM") as doc:
        own_scan = {p.path for p in doc.embedded_paths()[0]}
        rep = doc.path_report()
    # only opening the nested document finds them: its bytes are compressed inside the parent
    assert P_NESTED not in own_scan and len(own_scan) > 5
    p = by_path(rep)[P_NESTED]
    assert {loc.nested for loc in p.locations} == {("VirtualComp/Zq7Virtual-sldprt",)}
    assert [q for q in by_path(rep) if q.startswith(P_NESTED)] == [P_NESTED]
    nested_fields = [f for f in rep.identity_fields if f.value == USER_NESTED]
    assert nested_fields and nested_fields[0].location.nested == ("VirtualComp/Zq7Virtual-sldprt",)
    assert [d.nested for d in rep.documents] == [(), ("VirtualComp/Zq7Virtual-sldprt",)]
    assert rep.complete and rep.counts()["documents"] == 2


def test_nested_documents_are_followed_to_any_depth():
    inner = with_virtual("VirtualComp/Zq7Inner-sldprt", nested_part(P_DEEP, "zq7deepuser"))
    asm = with_virtual("VirtualComp/Zq7Sub-sldasm", inner)
    with open_document(asm) as doc:
        rep = doc.path_report()
    chain = ("VirtualComp/Zq7Sub-sldasm", "VirtualComp/Zq7Inner-sldprt")
    assert {loc.nested for loc in by_path(rep)[P_DEEP].locations} == {chain}
    assert [d.nested for d in rep.documents] == [(), chain[:1], chain]
    assert rep.complete


def test_a_stream_over_the_cap_makes_the_report_incomplete():
    big = {"Contents/Zq7Big": bytes(17 << 20)}  # over the 16 MiB default, compresses to little
    with open_document(rebuild(O02, big)) as doc:
        rep = doc.path_report()
    assert not rep.complete
    gaps = [(i.reason, i.nested, i.stream) for i in rep.incomplete]
    assert gaps == [("stream_over_cap", (), "Contents/Zq7Big")]
    with open_document(O02) as doc:  # the control: the fixture itself is complete
        assert doc.path_report().complete


def test_an_over_cap_stream_in_a_nested_document_counts_too():
    inner = rebuild(O02, {"Contents/Zq7Big": bytes(2 << 20)})
    with open_document(with_virtual("VirtualComp/Zq7Virtual-sldprt", inner)) as doc:
        rep = doc.path_report(max_stream_bytes=1 << 20)
        cap = max(s.size for s in doc.streams() if not s.name.startswith("VirtualComp/"))
    assert cap < 1 << 20  # the parent's own streams are all under the cap
    assert ("stream_over_cap", ("VirtualComp/Zq7Virtual-sldprt",), "Contents/Zq7Big") in {
        (i.reason, i.nested, i.stream) for i in rep.incomplete
    }
    assert not rep.complete


def test_a_nested_document_that_does_not_open_is_reported_and_scanned_raw():
    junk = b"not a document " + cstring("J:\\Zq7Junk\\raw.SLDPRT")
    with open_document(with_virtual("VirtualComp/Zq7Broken-sldprt", junk)) as doc:
        rep = doc.path_report()
    assert not rep.complete
    assert ("nested_unreadable", (), "VirtualComp/Zq7Broken-sldprt") in {
        (i.reason, i.nested, i.stream) for i in rep.incomplete
    }
    assert "J:\\Zq7Junk\\raw.SLDPRT" in by_path(rep)


def test_nesting_deeper_than_the_container_allows_stops_cleanly(monkeypatch):
    monkeypatch.setattr(container_mod, "MAX_NEST_DEPTH", 2)
    doc_bytes = nested_part()
    for depth in range(4):
        doc_bytes = with_virtual(f"VirtualComp/Zq7Level{depth}-sldasm", doc_bytes)
    with open_document(doc_bytes) as doc:
        rep = doc.path_report()
    assert [i.reason for i in rep.incomplete] == ["nested_unreadable"]
    assert len(rep.incomplete[0].nested) == 2 and len(rep.documents) == 3


def test_an_unreadable_identity_carrier_makes_the_report_incomplete():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;&a;</x>'
    with open_document(rebuild(O02, {"docProps/core.xml": bomb})) as doc:
        rep = doc.path_report()
    assert not rep.complete
    assert [(i.reason, i.stream) for i in rep.incomplete] == [("carrier_unreadable", "docProps/core.xml")]
    assert [w.code for w in rep.warnings] == ["xml_doctype_refused"]
    assert not any(f.field == "core_last_modified_by" for f in rep.identity_fields)


def test_an_unreadable_stream_makes_the_report_incomplete():
    from solidseas.errors import SldFormatError

    with open_document(O02) as doc:
        read = doc.container.read

        def failing(name, **kw):
            if name == "Contents/CMgr":
                raise SldFormatError("damaged member")
            return read(name, **kw)

        doc.container.read = failing
        rep = doc.path_report()
    assert [(i.reason, i.stream) for i in rep.incomplete] == [("stream_unreadable", "Contents/CMgr")]
    assert rep.documents[0].streams_scanned == rep.documents[0].streams - 1


def test_limits_make_the_report_incomplete_not_an_error():
    asm = with_virtual("VirtualComp/Zq7Virtual-sldprt", nested_part())
    with open_document(asm) as doc:
        rep = doc.path_report(max_paths=1)
        assert len(rep.paths) == 1 and [i.reason for i in rep.incomplete] == ["path_limit"]
        rep = doc.path_report(max_documents=1)
        assert len(rep.documents) == 1 and "document_limit" in {i.reason for i in rep.incomplete}
        rep = doc.path_report(max_total_bytes=1000)
        assert "byte_limit" in {i.reason for i in rep.incomplete} and not rep.complete
        # what was read before the limit is kept: here the structured carriers
        assert rep.paths and rep.identity_fields and len(rep.documents) == 1
        for bad in (0, -1, True, 1.5, "8"):
            with pytest.raises(InvalidArgumentError):
                doc.path_report(max_paths=bad)


# --------------------------------------------------------------------------- the fixtures
@pytest.mark.parametrize("name", NATIVE)
def test_the_report_holds_every_scanned_and_every_structured_path(name):
    with open_document(fixture_path(name)) as doc:
        rep = doc.path_report()
        scanned = {p.path.casefold().rstrip("\\") for p in doc.embedded_paths()[0]}
        md = doc.metadata
        structured = list(md.header2.get("ext_paths", []))
        tree = [f["path"] or "" for f in md.tree["files"].values()]
        structured += [p for p in tree if re.match(r"[A-Za-z]:\\", p)]
        structured += [i["value"] for i in md.identity if i["field"] == "folder_at_save"]
    keys = {p.path.casefold().rstrip("\\") for p in rep.paths}
    assert rep.complete and len(rep.paths) >= 5 and scanned
    assert scanned <= keys
    assert {s.casefold().rstrip("\\") for s in structured} <= keys


def test_fixture_reports_find_what_a_saved_file_always_holds():
    """Before asserting anything is absent, check the report finds what every saved file
    holds (tests-that-check-nothing): a temp folder, the SOLIDWORKS install and Windows."""
    with open_document(O02) as doc:
        rep = doc.path_report()
    counts = rep.counts()["by_category"]
    assert counts["temp"] >= 1 and counts["program"] >= 1 and counts["windows"] >= 1
    assert any(f.field == "core_last_modified_by" for f in rep.identity_fields)
    with open_document(O08) as doc:
        rep = doc.path_report()
    refs = [p for p in rep.paths if "references" in p.roles]
    assert any(p.path.lower().endswith("o02_boxa.sldprt") for p in refs)
    streams = {loc.stream for p in refs for loc in p.locations}
    assert {"Header2", "swXmlContents/COMPINSTANCETREE", "SwDocContentMgr/SwDocContentMgrInfo"} <= streams


# --------------------------------------------------------------------------- every surface
PLANTED = (P_CSTRING, P_FREE16, P_UTF8, P_ACCOUNT, P_UNC, ACCOUNT, HOST)
PLANTED_NAMES = (USER_H2, USER_AUTHOR, USER_CORE, USER_LAST)


def test_planted_values_reach_every_surface(tmp_path, capsys):
    """The leak-test rule turned around: the report exists to show these values, so each
    must be in the raw output of each surface, with nothing stripped."""
    path = tmp_path / "planted.SLDPRT"
    path.write_bytes(planted_part())
    with open_document(path) as doc:
        rep = doc.path_report()
        data = model.build_path_report(doc)
    python_values = (
        {p.path for p in rep.paths}
        | {p.account for p in rep.paths if p.account}
        | {h.host for h in rep.hosts}
        | {f.value for f in rep.identity_fields}
    )
    encoded = model.dumps(model.envelope("path_report", data))
    assert cli.main(["paths", str(path), "--json"]) == 0
    cli_json, cli_err = capsys.readouterr()
    assert cli.main(["paths", str(path)]) == 0
    cli_text, _ = capsys.readouterr()
    assert cli_err == ""
    for value in PLANTED + PLANTED_NAMES:
        as_json = json.dumps(value)[1:-1]  # how the strict, ASCII-only encoder writes it
        assert value in python_values, value
        assert as_json in encoded, value
        assert as_json in cli_json, value
        assert value in cli_text, value
    assert REWRITE_NOTE in cli_text and json.loads(cli_json)["data"]["rewrite"]["supported"] is False


def test_the_json_matches_its_schema_and_the_python_report(tmp_path, capsys):
    path = tmp_path / "top.SLDASM"
    path.write_bytes(with_virtual("VirtualComp/Zq7Virtual-sldprt", nested_part()))
    with open_document(path) as doc:
        data = model.build_path_report(doc)
        rep = doc.path_report()
    assert validate(data, model.KINDS["path_report"].schema, strict=True) == []
    assert [p["path"] for p in data["paths"]] == [p.path for p in rep.paths]
    assert data["counts"] == rep.counts()
    assert cli.main(["paths", str(path), "--json"]) == 0
    env = json.loads(capsys.readouterr()[0])
    assert env["kind"] == "path_report" and env["data"] == data
    assert validate(env, model.envelope_schema("path_report"), strict=True) == []


def test_an_incomplete_report_exits_4(tmp_path, capsys):
    path = tmp_path / "broken.SLDASM"
    path.write_bytes(with_virtual("VirtualComp/Zq7Broken-sldprt", b"not a document"))
    assert cli.main(["paths", str(path), "--json"]) == 4
    env = json.loads(capsys.readouterr()[0])
    assert env["ok"] is True and env["data"]["complete"] is False
    assert cli.main(["paths", str(path)]) == 4
    out = capsys.readouterr()[0]
    assert "incomplete" in out and "nested_unreadable: VirtualComp/Zq7Broken-sldprt" in out


def test_structured_carriers_hold_what_the_scan_cannot_see():
    """Paths with forward slashes are invisible to the byte scan; only the structured
    carriers (the tree's swPath and swImportedPath, the folder at save) find them."""
    t = TreeXml()
    t.file("2", "C:/Zq7Slash/Jobs/part.SLDPRT")
    t.file("3", "C:/Zq7Slash/Jobs/imported.SLDPRT", swImportedPath="Q:/Zq7Import/Kunde/imported.step")
    t.top("m1")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "part", 1, "m2")
    t.ref("m1", "imported", 1, "m3")
    asm = resolving_assembly(t, folder_at_save="C:/Zq7Saved/Out/")
    with open_document(asm, name="top.SLDASM") as doc:
        scanned = {p.path for p in doc.embedded_paths()[0]}
        rep = doc.path_report()
    paths = by_path(rep)
    want = {
        "C:/Zq7Slash/Jobs/part.SLDPRT": (("references",), ("tree",)),
        "C:/Zq7Slash/Jobs/imported.SLDPRT": (("references",), ("tree",)),
        "Q:/Zq7Import/Kunde/imported.step": (("imported_from",), ("tree_imported",)),
        "C:/Zq7Saved/Out/": (("save_location",), ("save_folder",)),
    }
    for path, (roles, sources) in want.items():
        assert path not in scanned
        assert (paths[path].roles, paths[path].sources) == (roles, sources), path
        assert paths[path].severity == "high"
    assert paths["Q:/Zq7Import/Kunde/imported.step"].reason == "referenced_document"


def test_the_documents_own_path_is_where_it_was_saved_not_a_reference():
    s = fixture_streams(O02)
    own, other = "D:\\Zq7Own\\zq7own.SLDPRT", "D:\\Zq7Own\\zq7other.SLDPRT"
    part = rebuild(
        O02,
        {BIO: s[BIO] + cstring(own), "Contents/Zq7Extra": cstring(own.upper()) + b"\x00" + cstring(other)},
    )
    with open_document(part, name="zq7own.SLDPRT") as doc:
        rep = doc.path_report()
    paths = by_path(rep)
    assert paths[own].roles == ("save_location", "history") and paths[own].reason == "save_location"
    assert not paths[own].history_only
    assert paths[other].roles == ("references",)


def test_a_minimal_container_is_reported_without_carriers():
    with open_document(build_modern({"Contents/Zq7Only": cstring("K:\\Zq7Only\\x.SLDPRT")})) as doc:
        rep = doc.path_report()
    assert [p.path for p in rep.paths] == ["K:\\Zq7Only\\x.SLDPRT"] and rep.complete
