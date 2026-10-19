"""Reference resolution (``docs/API.md`` section 3.10) on folder trees built in ``tmp_path``.

Each test writes a crafted assembly (``builders.resolving_assembly``) whose
component tree stores chosen paths and creation times, next to copies of o02
that claim chosen creation times (``builders.part_with_creation_time``), and
checks which file each rule picks. Stored paths use the drive letter ``Q:``,
which the gateway is told does not exist, so no test touches a real drive
through a stored path; tests that need a stored path to be a real path on this
machine run on Windows only, where stored Windows paths are host paths.
``test_resolve_safety.py`` holds the filesystem safety tests.
"""

import functools
import os
import sys
import time
import unicodedata
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, resolving_assembly
from fakefs import ARCHIVE, FakeEntry, fake_tree
from jsonschema_subset import validate
from solidseas import Root, Roots, cli, model, open_document
from solidseas.errors import InvalidArgumentError, PathRefusedError
from solidseas.formats.solidworks.metadata import parse_header2
from solidseas.resolve import Gateway, IndexCache, Location, parse_path_map, parse_stored, resolve_references
from solidseas.resolve import gateway as gateway_mod
from solidseas.resolve.identity import own_identity, parse_creation_time
from solidseas.resolve.index import FolderIndex
from solidseas.resolve.names import fold, host_split, nfc_fold, suffix_score
from support import ASSEMBLY, fixture_path

CT = 1_700_000_000  # the creation time the assemblies store
OTHER = 1_600_000_000  # an unrelated document's
WINDOWS = sys.platform == "win32"
windows_only = pytest.mark.skipif(
    not WINDOWS, reason="a stored path is a path on this machine only on Windows"
)


@pytest.fixture(autouse=True)
def fake_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


@functools.cache
def part(ct: int | None = CT, **kwargs) -> bytes:
    return part_with_creation_time(ct, **kwargs)


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def assembly(refs, *, folder_at_save: str = "", members=None, virtual=(), imported=()) -> bytes:
    """A top assembly using one instance of each stored path in ``refs`` (path, creation
    time); file keys are "2", "3"... in order."""
    t = TreeXml()
    t.top("m1")
    for i, (stored, ct) in enumerate(refs, start=2):
        attrs = {} if ct is None else {"swCreationTime": str(ct)}
        if i - 2 in imported:
            attrs["swImportedPath"] = "C:\\Imports\\thing.step"
        t.file(str(i), stored, **attrs)
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}", virtual=(i - 2) in virtual)
    return resolving_assembly(t, folder_at_save=folder_at_save, members=members)


def resolve(path: Path, roots=None, **kwargs):
    with open_document(path) as doc:
        return resolve_references(doc, roots, **kwargs)


def codes(r) -> list[str]:
    return [w.code for w in r.warnings]


# --------------------------------------------------------------------------- the rules
@windows_only
def test_an_unmoved_document_finds_its_stored_paths(tmp_path):
    proj = tmp_path / "Proj"
    stored = write(proj / "parts" / "p.SLDPRT", part())
    doc = write(proj / "asm.SLDASM", assembly([(str(stored), CT)], folder_at_save=str(proj) + "\\"))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.confidence, r.identity) == ("resolved", "stored_unmoved", "high", "match")
    assert r.match == Location("document", "parts/p.SLDPRT", str(stored)) and r.warnings == ()
    assert r.match.host_path == str(stored)


def test_a_project_moved_with_its_parts_is_rebased(tmp_path):
    proj = tmp_path / "New" / "Proj"
    write(proj / "parts" / "p.SLDPRT", part())
    doc = write(
        proj / "asm.SLDASM",
        assembly([("Q:\\Old\\Proj\\parts\\p.SLDPRT", CT)], folder_at_save="Q:\\Old\\Proj\\"),
    )
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.confidence, r.identity) == ("moved", "rebased", "high", "match")
    assert (r.match.root, r.match.path) == ("document", "parts/p.SLDPRT")
    assert r.stored_path == "Q:\\Old\\Proj\\parts\\p.SLDPRT" and r.candidates == ()


def test_a_rebased_path_above_the_document_folder(tmp_path):
    new = tmp_path / "New"
    lib = write(new / "lib" / "p.SLDPRT", part())
    doc = write(
        new / "Proj" / "asm.SLDASM",
        assembly([("Q:\\Old\\lib\\p.SLDPRT", CT)], folder_at_save="Q:\\Old\\Proj\\"),
    )
    # the default root is the document's folder; the library lies outside it
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.identity) == ("moved", "rebased", "match")
    assert r.match.root is None and r.match.path == str(lib) and "outside_roots" in codes(r)
    # the REST service never looks outside its roots
    gw = Gateway(allow_outside_roots=False)
    (r,) = resolve(doc, gateway=gw).results.values()
    assert r.status == "missing" and r.match is None
    assert ("point", str(lib), "refused:outside_roots") in gw.calls
    # a root that holds both makes the match root-relative
    (r,) = resolve(doc, {"jobs": new}).results.values()
    assert (r.status, r.rule, r.match.root, r.match.path) == ("moved", "rebased", "jobs", "lib/p.SLDPRT")
    assert "outside_roots" not in codes(r)


@windows_only
def test_a_document_moved_alone_finds_the_stored_path(tmp_path):
    stored = write(tmp_path / "Orig" / "p.SLDPRT", part())
    doc = write(
        tmp_path / "Moved" / "asm.SLDASM",
        assembly([(str(stored), CT)], folder_at_save=str(tmp_path / "Orig") + "\\"),
    )
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.confidence, r.identity) == ("resolved", "stored_path", "medium", "match")
    assert r.match == Location(None, str(stored), str(stored)) and codes(r) == ["outside_roots"]


def test_a_flattened_package_resolves_by_folder(tmp_path):
    pkg = tmp_path / "Pkg"
    write(pkg / "a.SLDPRT", part())
    write(pkg / "b.SLDPRT", part())
    doc = write(
        pkg / "asm.SLDASM",
        assembly([("Q:\\Old\\Proj\\sub1\\a.SLDPRT", CT), ("Q:\\Old\\Proj\\sub2\\b.SLDPRT", CT)]),
    )
    res = resolve(doc)
    assert [(r.status, r.rule, r.match.path, r.confidence) for r in res.results.values()] == [
        ("moved", "same_folder", "a.SLDPRT", "high"),
        ("moved", "same_folder", "b.SLDPRT", "high"),
    ]
    assert res.counts()["moved"] == 2 and not res.index_partial


def test_a_renamed_parent_folder_is_found_by_the_suffix_probe(tmp_path):
    top = tmp_path / "Renamed"
    write(top / "Parts" / "p.SLDPRT", part())
    doc = write(top / "Assemblies" / "asm.SLDASM", assembly([("Q:\\Old\\Proj\\Parts\\p.SLDPRT", CT)]))
    (r,) = resolve(doc, {"proj": top}).results.values()
    assert (r.status, r.rule, r.confidence) == ("moved", "suffix_probe", "high")
    assert (r.match.root, r.match.path) == ("proj", "Parts/p.SLDPRT")
    # the probe never climbs above the root: with the document's folder as the root it finds nothing
    (r,) = resolve(doc).results.values()
    assert r.status == "missing" and r.rule is None and r.confidence == "none"


def test_an_unrelated_file_with_the_same_name_is_vetoed(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part(OTHER))  # same name, another document
    write(folder / "archive" / "p.SLDPRT", part())  # the right one
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.identity, r.confidence) == ("moved", "name_index", "match", "high")
    assert r.match.path == "archive/p.SLDPRT"
    assert [(c.location.path, c.found_by, c.identity) for c in r.candidates] == [
        ("p.SLDPRT", "same_folder", "differ")
    ]


def test_an_identity_match_is_preferred_over_an_unknown_identity(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "a" / "p.SLDPRT", b"not a SOLIDWORKS file" * 10)  # identity unknown
    write(folder / "b" / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.identity, r.match.path) == ("moved", "name_index", "match", "b/p.SLDPRT")
    assert [(c.location.path, c.identity) for c in r.candidates] == [("a/p.SLDPRT", "unknown")]


def test_the_rebased_path_comes_before_the_same_folder(tmp_path):
    proj = tmp_path / "Proj"
    write(proj / "parts" / "p.SLDPRT", part())
    write(proj / "p.SLDPRT", part())  # a copy beside the assembly
    doc = write(
        proj / "asm.SLDASM",
        assembly([("Q:\\Old\\Proj\\parts\\p.SLDPRT", CT)], folder_at_save="Q:\\Old\\Proj\\"),
    )
    (r,) = resolve(doc).results.values()
    assert (r.rule, r.match.path) == ("rebased", "parts/p.SLDPRT")


def test_when_only_an_unrelated_file_is_found_it_comes_back_with_low_confidence(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part(OTHER))
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.identity, r.confidence) == ("moved", "same_folder", "differ", "low")
    assert r.match.path == "p.SLDPRT" and "identity_mismatch" in codes(r)


def test_explorer_copies_are_told_apart_by_folder_suffix_or_called_ambiguous(tmp_path):
    root = tmp_path / "Root"
    write(root / "A" / "Proj" / "Parts" / "p.SLDPRT", part())
    write(root / "B" / "Other" / "p.SLDPRT", part())
    doc = write(root / "Docs" / "asm.SLDASM", assembly([("Q:\\Work\\Proj\\Parts\\p.SLDPRT", CT)]))
    (r,) = resolve(doc, {"root": root}).results.values()
    assert (r.status, r.rule, r.identity, r.confidence) == ("moved", "name_index_suffix", "match", "low")
    assert r.match.path == "A/Proj/Parts/p.SLDPRT"
    assert [c.location.path for c in r.candidates] == ["B/Other/p.SLDPRT"]
    # two copies the stored folder says nothing about: ambiguous, with both
    doc2 = write(root / "Docs" / "asm2.SLDASM", assembly([("Q:\\Work\\Elsewhere\\p.SLDPRT", CT)]))
    (r,) = resolve(doc2, {"root": root}).results.values()
    assert (r.status, r.rule, r.match, r.confidence) == ("ambiguous", None, None, "none")
    assert sorted(c.location.path for c in r.candidates) == ["A/Proj/Parts/p.SLDPRT", "B/Other/p.SLDPRT"]
    assert all(c.found_by == "name_index" and c.identity == "match" for c in r.candidates)


@windows_only
def test_a_copied_project_warns_that_the_stored_path_still_exists(tmp_path):
    orig = write(tmp_path / "Orig" / "Proj" / "parts" / "p.SLDPRT", part())
    write(tmp_path / "Copy" / "Proj" / "parts" / "p.SLDPRT", part())
    doc = write(
        tmp_path / "Copy" / "Proj" / "asm.SLDASM",
        assembly([(str(orig), CT)], folder_at_save=str(tmp_path / "Orig" / "Proj") + "\\"),
    )
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.match.path) == ("moved", "rebased", "parts/p.SLDPRT")
    assert "stored_path_also_exists" in codes(r)
    assert [(c.location.root, c.location.path, c.found_by) for c in r.candidates] == [
        (None, str(orig), "stored_path")
    ]


def test_a_bare_stored_name_is_found_by_name(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "sub" / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("p.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.match.path) == ("moved", "name_index", "sub/p.SLDPRT")
    assert "stored_path_refused" not in codes(r)


def test_a_caret_in_a_name_does_not_make_a_component_virtual(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "Part1^top.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\Part1^top.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.match.path) == ("moved", "same_folder", "Part1^top.SLDPRT")


def test_a_virtual_component_is_never_looked_up_on_disk(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "Part1^top.SLDPRT", part())  # a decoy with the stored name and identity
    write(folder / "Part2^top.SLDPRT", part())
    write(folder / "q.SLDPRT", part())
    doc = write(
        folder / "asm.SLDASM",
        assembly(
            [("Q:\\Old\\Part1^top.SLDPRT", CT), ("Q:\\Old\\Part2^top.SLDPRT", CT), ("Q:\\Old\\q.SLDPRT", CT)],
            virtual=(0, 1),
            members={"VirtualComp/Part1": part()},
        ),
    )
    gw = Gateway()
    res = resolve(doc, gateway=gw)
    a, b, q = res.results.values()
    assert (
        q.status == "moved" and ("identity", str(folder / "q.SLDPRT"), "read") in gw.calls
    )  # the gateway ran
    assert (a.status, a.rule, a.nested, a.identity, a.confidence) == (
        "embedded",
        "embedded",
        "VirtualComp/Part1",
        "match",
        "high",
    )
    assert a.match is None and a.candidates == ()
    assert (b.status, b.nested, b.confidence) == ("embedded_not_found", None, "none")
    assert all("^top" not in path for _op, path, _o in gw.calls)
    # with only virtual files nothing is walked at all
    only = write(folder / "virtual.SLDASM", assembly([("Q:\\Old\\Part1^top.SLDPRT", CT)], virtual=(0,)))
    gw = Gateway()
    assert resolve(only, gateway=gw).results["2"].status == "embedded_not_found" and gw.calls == []


def test_a_virtual_component_inside_a_sub_assembly(tmp_path):
    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\Old\\sub.SLDASM", "ASSEMBLY", swCreationTime=str(CT))
    t.file("3", "Q:\\Old\\Part9^sub.SLDPRT", swCreationTime=str(CT))
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2")
    t.ref("m2", "Part9^sub", 1, "m3", virtual=True)
    doc = write(tmp_path / "Doc" / "asm.SLDASM", resolving_assembly(t))
    r = resolve(doc).results["3"]
    assert (r.status, r.rule, r.nested, r.match) == ("embedded_in_subassembly", "embedded", None, None)
    assert "from_parent_tree" in codes(r)


def test_an_imported_component_is_embedded_when_its_stream_exists(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "a.SLDPRT", part())
    write(folder / "b.SLDPRT", part())
    doc = write(
        folder / "asm.SLDASM",
        assembly(
            [("Q:\\Old\\a.SLDPRT", CT), ("Q:\\Old\\b.SLDPRT", CT)],
            imported=(0, 1),
            members={"ImportedComp/a.SLDPRT": part()},
        ),
    )
    a, b = resolve(doc).results.values()
    assert (a.status, a.nested, a.identity) == ("embedded", "ImportedComp/a.SLDPRT", "match")
    assert (b.status, b.rule, b.match.path) == ("moved", "same_folder", "b.SLDPRT")  # an ordinary file


def test_a_name_that_differs_only_by_case_is_found_with_a_warning(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "bracket.sldprt", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\BRACKET.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.match.path) == ("moved", "same_folder", "bracket.sldprt")
    assert "case_differs" in codes(r)


def test_two_names_that_differ_only_by_case_are_ambiguous(tmp_path, monkeypatch):
    """A case-sensitive filesystem can hold both; a fake listing stands in for one."""
    folder = tmp_path / "Doc"
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    listing = [FakeEntry("asm.SLDASM", ARCHIVE, size=10), FakeEntry("p.sldprt", ARCHIVE, size=10)]
    listing.append(FakeEntry("P.SLDPRT", ARCHIVE, size=10))
    fake_tree(monkeypatch, str(folder), {"": listing})
    (r,) = resolve(doc).results.values()
    assert (r.status, r.match) == ("ambiguous", None)
    assert sorted(c.location.path for c in r.candidates) == ["P.SLDPRT", "p.sldprt"]
    assert "identity_read_failed" in codes(r)  # the fake entries are not real files


def test_sharp_s_and_ss_stay_different_names(tmp_path):
    assert fold("ß") == "ß" and fold("Straße") == fold("STRAßE") and fold("Straße") != fold("STRASSE")
    assert fold("ﬁle") != fold("FILE") and fold("Ä") == fold("ä")
    folder = tmp_path / "Doc"
    write(folder / "Straße.SLDPRT", part())
    doc = write(
        folder / "asm.SLDASM",
        assembly([("Q:\\Old\\STRASSE.SLDPRT", CT), ("Q:\\Old\\STRAßE.SLDPRT", CT)]),
    )
    ss, sharp = resolve(doc).results.values()
    assert ss.status == "missing" and ss.candidates == ()
    assert (sharp.status, sharp.rule, sharp.match.path) == ("moved", "same_folder", "Straße.SLDPRT")


def test_a_name_equal_only_after_normalisation_is_found_with_a_warning(tmp_path):
    decomposed = unicodedata.normalize("NFD", "Café.SLDPRT")
    assert decomposed != "Café.SLDPRT" and fold(decomposed) != fold("Café.SLDPRT")
    assert nfc_fold(decomposed) == nfc_fold("CAFÉ.sldprt")
    folder = tmp_path / "Doc"
    write(folder / decomposed, part())
    if unicodedata.normalize("NFC", os.listdir(folder)[0]) == os.listdir(folder)[0]:
        pytest.skip("this filesystem normalises names")
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\Café.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule) == ("moved", "same_folder") and "normalization_differs" in codes(r)


# --------------------------------------------------------------------------- path maps and roots
@pytest.mark.parametrize(
    ("source", "stored", "below"),
    [
        ("S:\\", "S:\\Eng\\Proj\\p.SLDPRT", ("Eng", "Proj")),
        ("s:/eng", "S:\\Eng\\Proj\\p.SLDPRT", ("Proj",)),
        ("\\\\fs01\\eng", "\\\\fs01\\eng\\Proj\\p.SLDPRT", ("Proj",)),
        ("\\\\FS01\\Eng\\Proj\\", "\\\\fs01\\eng\\Proj\\p.SLDPRT", ()),
    ],
    ids=["drive", "drive-folder", "unc", "unc-folder"],
)
def test_a_path_map_reads_stored_prefixes_as_local_folders(tmp_path, source, stored, below):
    mount = tmp_path / "mount"
    target = write(mount.joinpath(*below, "p.SLDPRT"), part())
    doc = write(tmp_path / "Doc" / "asm.SLDASM", assembly([(stored, CT)]))
    gw = Gateway()
    (r,) = resolve(doc, path_map=[f"{source}={mount}"], gateway=gw).results.values()
    assert (r.status, r.rule, r.confidence, r.identity) == ("resolved", "path_map", "high", "match")
    assert r.match == Location(None, str(target), str(target))
    # the share itself is never touched: the gateway refused the stored path on its anchor
    share = [(op, outcome) for op, path, outcome in gw.calls if "fs01" in path.casefold()]
    assert share == ([("point", "refused:unc")] if WINDOWS and stored.startswith("\\\\") else [])
    # inside a root the match is root-relative
    (r,) = resolve(doc, {"mnt": mount}, path_map=[(source, str(mount))]).results.values()
    assert (r.status, r.match.root, r.match.path) == ("resolved", "mnt", "/".join((*below, "p.SLDPRT")))


@pytest.mark.parametrize("bad", ["nonsense", "C:rel=/x", "S:\\=relative", "\\\\?\\C:\\x=/y", "\\\\host=/x"])
def test_a_malformed_path_map_is_refused(bad):
    with pytest.raises(InvalidArgumentError):
        parse_path_map([bad])


def test_a_path_map_applies_at_a_component_boundary(tmp_path):
    (mapping,) = parse_path_map([f"S:\\Eng={tmp_path}"])
    assert mapping.apply(parse_stored("S:\\Engineering\\p.SLDPRT")) is None
    assert mapping.apply(parse_stored("T:\\Eng\\p.SLDPRT")) is None
    assert mapping.apply(parse_stored("s:/ENG/sub/p.SLDPRT")).parts[-2:] == ("sub", "p.SLDPRT")


def test_project_roots_come_before_library_roots(tmp_path):
    proj, lib = tmp_path / "Proj", tmp_path / "Lib"
    write(proj / "sub" / "both.SLDPRT", part())
    write(lib / "both.SLDPRT", part())
    write(lib / "std" / "onlylib.SLDPRT", part())
    doc = write(proj / "asm.SLDASM", assembly([("Q:\\X\\both.SLDPRT", CT), ("Q:\\X\\onlylib.SLDPRT", CT)]))
    roots = Roots([Root("proj", str(proj)), Root("lib", str(lib), role="library")])
    res = resolve(doc, roots)
    both, only = res.results.values()
    assert (both.rule, both.match.root, both.match.path) == ("name_index", "proj", "sub/both.SLDPRT")
    assert (only.rule, only.match.root, only.match.path) == ("name_index", "lib", "std/onlylib.SLDPRT")
    assert [(s.id, s.role, s.recursive) for s in res.roots] == [
        ("proj", "project", True),
        ("lib", "library", True),
    ]


def test_roots_are_checked(tmp_path):
    with pytest.raises(InvalidArgumentError):
        Root("Jobs", str(tmp_path))  # ids are lower case
    with pytest.raises(InvalidArgumentError):
        Root("jobs", str(tmp_path), role="archive")
    with pytest.raises(InvalidArgumentError):
        Roots([Root("a", str(tmp_path)), Root("a", str(tmp_path / "x"))])
    for refused, rule in [
        ("\\\\host@SSL\\share", "webdav"),
        ("\\\\host\\DavWWWRoot\\x", "webdav"),
        ("\\\\?\\C:\\x", "device_path"),
        ("\\\\.\\pipe\\x", "device_path"),
        ("relative\\folder", "not_absolute"),
    ]:
        with pytest.raises(PathRefusedError) as err:
            Root("r", refused)
        assert err.value.detail["rule"] == rule, refused
    if WINDOWS:
        assert Root("share", "\\\\fileserver\\eng").path == "\\\\fileserver\\eng"  # C6: a share is fine
        with pytest.raises(PathRefusedError):
            Root("r", "C:folder")
    assert Roots.from_mapping({"a": tmp_path}).ids() == ["a"]


def test_the_references_json_is_root_relative_and_valid(tmp_path):
    new = tmp_path / "New"
    write(new / "Proj" / "parts" / "p.SLDPRT", part())
    lib = write(new / "lib" / "q.SLDPRT", part())
    doc = write(
        new / "Proj" / "asm.SLDASM",
        assembly(
            [
                ("Q:\\Old\\Proj\\parts\\p.SLDPRT", CT),
                ("Q:\\Old\\lib\\q.SLDPRT", CT),
                ("Q:\\Old\\none.SLDPRT", CT),
            ],
            folder_at_save="Q:\\Old\\Proj\\",
        ),
    )
    with open_document(doc) as d:
        plain = model.build_references(d)
        data = model.build_references(d, resolution=resolve_references(d))
    assert plain["resolution"] is None and all(f["resolution"] is None for f in plain["files"])
    assert validate(data, model.KINDS["references"].schema, strict=True) == []
    model.dumps(model.envelope("references", data))
    p, q, none = (f["resolution"] for f in data["files"])
    assert p["match"] == {"root": "document", "path": "parts/p.SLDPRT"} and p["key"] == "2"
    assert q["match"] == {"root": None, "path": str(lib)}
    assert none["status"] == "missing" and none["match"] is None and none["candidates"] == []
    summary = data["resolution"]
    assert summary["roots"] == [
        {
            "id": "document",
            "role": "project",
            "recursive": True,
            "index_partial": False,
            "truncated_reason": None,
        }
    ]
    assert summary["counts"]["moved"] == 2 and summary["counts"]["missing"] == 1
    assert summary["outside_roots"] is True and summary["index_partial"] is False


def test_sub_assembly_files_and_shared_files_are_flagged(tmp_path):
    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\Old\\sub.SLDASM", "ASSEMBLY", swCreationTime=str(CT))
    t.file("3", "Q:\\Old\\shared.SLDPRT", swCreationTime=str(CT))
    t.file("4", "Q:\\Old\\inner.SLDPRT", swCreationTime=str(CT))
    for m, f in (("m2", "2"), ("m3", "3"), ("m4", "4")):
        t.model(m, f)
    t.ref("m1", "sub", 1, "m2")
    t.ref("m1", "shared", 1, "m3")
    t.ref("m2", "shared", 1, "m3")
    t.ref("m2", "inner", 1, "m4")
    folder = tmp_path / "Doc"
    for n in ("shared", "inner"):
        write(folder / f"{n}.SLDPRT", part())
    write(folder / "sub.SLDASM", part())  # its identity claims CT too
    doc = write(folder / "asm.SLDASM", resolving_assembly(t))
    res = resolve(doc).results
    assert codes(res["2"]) == [] and res["2"].status == "moved"
    assert codes(res["3"]) == ["context_varies"]
    assert codes(res["4"]) == ["from_parent_tree"] and res["4"].status == "moved"


# --------------------------------------------------------------------------- limits
def test_a_walk_cut_short_marks_every_result(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "a" / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    res = resolve(doc, max_examined=1)
    (r,) = res.results.values()
    assert res.index_partial and res.roots[0].truncated_reason == "max_examined"
    assert r.status == "missing" and {"index_partial", "search_incomplete"} <= set(codes(r))
    res = resolve(doc, max_seconds=0)
    assert res.index_partial and res.roots[0].truncated_reason == "deadline"
    assert resolve(doc).results["2"].status == "moved"  # and without a limit it is found


def test_the_identity_read_cap_leaves_identities_unknown(tmp_path, monkeypatch):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))

    def never(*args, **kwargs):
        raise AssertionError("a document was opened past the read cap")

    monkeypatch.setattr(gateway_mod, "_open_document", never)
    gw = Gateway(max_identity_reads=0)
    (r,) = resolve(doc, gateway=gw).results.values()
    assert (r.status, r.rule, r.identity, r.confidence) == ("moved", "same_folder", "unknown", "low")
    assert "search_incomplete" in codes(r)
    assert any(op == "identity" and outcome == "skipped" for op, _p, outcome in gw.calls)


def test_a_damaged_candidate_is_reported_and_kept(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", b"not a SOLIDWORKS file" * 10)
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.rule, r.identity, r.confidence) == ("moved", "same_folder", "unknown", "low")
    assert "identity_read_failed" in codes(r)


def test_resolution_arguments_are_checked(tmp_path):
    doc = write(tmp_path / "Doc" / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    for kwargs in ({"max_examined": 0}, {"max_seconds": -1}, {"max_candidates": True}, {"roots": "x"}):
        with pytest.raises(InvalidArgumentError):
            resolve(doc, **kwargs)
    with open_document(doc.read_bytes()) as d, pytest.raises(InvalidArgumentError):
        resolve_references(d)  # bytes have no folder: roots are needed


def test_a_part_has_nothing_to_resolve_and_walks_nothing(tmp_path):
    p = write(tmp_path / "Doc" / "p.SLDPRT", part())
    gw = Gateway()
    res = resolve(p, gateway=gw)
    assert res.results == {} and gw.calls == [] and not res.index_partial
    assert [(s.id, s.index_partial) for s in res.roots] == [("document", False)]


def test_one_cache_serves_many_documents(tmp_path, monkeypatch):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part())
    docs = [write(folder / f"a{i}.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)])) for i in range(3)]
    walks = []
    real = gateway_mod._Walk

    def walk(*args, **kwargs):
        walks.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(gateway_mod, "_Walk", walk)
    cache = IndexCache()
    for d in docs:
        assert resolve(d, cache=cache).results["2"].status == "moved"
    assert len(walks) == 1 and len(cache.identities) == 1


# --------------------------------------------------------------------------- identity
def test_creation_times_outside_the_window_are_unknown():
    now = time.time()
    assert parse_creation_time(CT) == CT == parse_creation_time(f" {CT} ")
    assert parse_creation_time(int(now)) == int(now)
    for bad in (0, "0", -5, "-5", int(now) + 2 * 86_400, "12abc", "", None, True, 1.5e9, "9" * 13):
        assert parse_creation_time(bad) is None, bad


def test_a_stored_creation_time_of_zero_is_unknown_not_different(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", 0)]))
    (r,) = resolve(doc).results.values()
    assert (r.status, r.identity, r.confidence) == ("moved", "unknown", "low")
    assert "identity_mismatch" not in codes(r)


def test_identity_falls_back_from_model_stamps_to_the_tree_and_keywords():
    with open_document(part()) as d:
        assert (own_identity(d).creation_time, own_identity(d).source) == (CT, "ModelStamps")
    with open_document(part(stamps=False)) as d:
        assert (own_identity(d).creation_time, own_identity(d).source) == (CT, "tree")
    with open_document(part(stamps=False, tree=False)) as d:
        assert (own_identity(d).creation_time, own_identity(d).source) == (CT, "keywords")
    with open_document(part(stamps=False, tree=False, keywords=False)) as d:
        assert own_identity(d).creation_time is None


def test_header2_records_carry_the_creation_time():
    with open_document(fixture_path(ASSEMBLY)) as d:
        md = d.metadata
        times = md.header2["creation_times"]
        tree = {f["path"]: int(f["creation_time"]) for f in md.tree["files"].values()}
    assert len(times) == 1 and all(tree[p] == ct for p, ct in times.items())
    assert parse_header2(b"")["creation_times"] == {}


# --------------------------------------------------------------------------- stored paths
@pytest.mark.parametrize(
    ("raw", "kind", "anchor", "folder", "name", "usable", "problem"),
    [
        ("C:\\Jobs\\A\\p.SLDPRT", "drive", "C:", ("Jobs", "A"), "p.SLDPRT", True, None),
        ("c:/Jobs/p.sldasm", "drive", "C:", ("Jobs",), "p.sldasm", True, None),
        ("C:\\Jobs\\\\.\\p.SLDPRT", "drive", "C:", ("Jobs",), "p.SLDPRT", True, None),
        ("\\\\fs01\\eng\\A\\p.SLDPRT", "unc", "\\\\fs01\\eng", ("A",), "p.SLDPRT", True, None),
        ("p.SLDPRT", "bare", "", (), "p.SLDPRT", False, None),
        ("\\\\?\\C:\\p.SLDPRT", "refused", "", (), "p.SLDPRT", False, "device_path"),
        ("\\\\.\\pipe\\p.SLDPRT", "refused", "", (), "p.SLDPRT", False, "device_path"),
        ("C:p.SLDPRT", "refused", "", (), "C:p.SLDPRT", False, "drive_relative"),
        ("\\Jobs\\p.SLDPRT", "refused", "", (), "p.SLDPRT", False, "rooted"),
        ("Jobs\\p.SLDPRT", "refused", "", (), "p.SLDPRT", False, "relative"),
        ("\\\\host\\p.SLDPRT", "refused", "", (), "p.SLDPRT", False, "malformed_unc"),
        ("", "refused", "", (), None, False, "empty"),
        ("C:\\" + "x\\" * 600 + "p.SLDPRT", "refused", "", (), None, False, "too_long"),
        ("C:\\a\\..\\p.SLDPRT", "drive", "C:", ("a", ".."), "p.SLDPRT", False, "dots_and_spaces"),
        ("C:\\a\\ . \\p.SLDPRT", "drive", "C:", ("a", " . "), "p.SLDPRT", False, "dots_and_spaces"),
        ("C:\\a\\x:y\\p.SLDPRT", "drive", "C:", ("a", "x:y"), "p.SLDPRT", False, "colon"),
        ("C:\\a\\CON.txt\\p.SLDPRT", "drive", "C:", ("a", "CON.txt"), "p.SLDPRT", False, "device_name"),
        ("C:\\a\\LPT\u00b9\\p.SLDPRT", "drive", "C:", ("a", "LPT\u00b9"), "p.SLDPRT", False, "device_name"),
        ("C:\\a\\NUL.SLDPRT", "drive", "C:", ("a",), "NUL.SLDPRT", False, "device_name"),
        ("C:\\a\\p.txt", "drive", "C:", ("a",), "p.txt", False, "not_a_document_name"),
        ("C:\\a\\b\x01\\p.SLDPRT", "drive", "C:", ("a", "b\x01"), "p.SLDPRT", False, "control_character"),
    ],
)
def test_stored_anchors_are_classified_into_a_closed_set(raw, kind, anchor, folder, name, usable, problem):
    sp = parse_stored(raw)
    assert (sp.kind, sp.anchor, sp.folder, sp.name, sp.usable, sp.problem) == (
        kind,
        anchor,
        folder,
        name,
        usable,
        problem,
    )
    assert sp.kind in ("drive", "unc", "bare", "refused")


def test_a_refused_stored_path_is_still_found_by_its_name(tmp_path):
    folder = tmp_path / "Doc"
    write(folder / "p.SLDPRT", part())
    doc = write(folder / "asm.SLDASM", assembly([("C:\\a\\..\\p.SLDPRT", CT), ("\\\\?\\C:\\q.SLDPRT", CT)]))
    gw = Gateway()
    a, b = resolve(doc, gateway=gw).results.values()
    assert (a.status, a.rule) == ("moved", "same_folder") and "stored_path_refused" in codes(a)
    assert b.status == "missing" and "stored_path_refused" in codes(b)
    assert all(".." not in path and "?" not in path for _op, path, _o in gw.calls)


def test_suffix_scores_and_index_lookups_fold_names():
    assert suffix_score(("x", "Proj", "Parts"), ("C:", "proj", "PARTS")) == 2
    assert suffix_score(("a",), ()) == 0
    index = FolderIndex(Root("r", str(Path.cwd())), host_split(str(Path.cwd())))
    index.add_folder("Sub", "Sub")
    index.add_file("Sub/p.sldprt", "p.sldprt", 1, 1, False)
    index.add_file("Sub/P.SLDPRT", "P.SLDPRT", 1, 1, False)
    index.add_file("Sub/notes.txt", "notes.txt", 1, 1, False)
    files, nfc = index.lookup(("SUB",), "p.SldPrt")
    assert sorted(f.rel for f in files) == ["Sub/P.SLDPRT", "Sub/p.sldprt"] and not nfc
    assert index.documents == 2 and index.by_name("NOTES.TXT") == ([], False)


# --------------------------------------------------------------------------- command line
def _run(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_references_resolve(tmp_path, capsys):
    import json

    proj = tmp_path / "Proj"
    write(proj / "parts" / "p.SLDPRT", part())
    lib = tmp_path / "Lib"
    write(lib / "q.SLDPRT", part())
    doc = write(
        proj / "asm.SLDASM",
        assembly(
            [("Q:\\Old\\Proj\\parts\\p.SLDPRT", CT), ("S:\\Std\\q.SLDPRT", CT), ("Q:\\Old\\none.SLDPRT", CT)],
            folder_at_save="Q:\\Old\\Proj\\",
        ),
    )
    code, out, err = _run(
        capsys,
        ["references", str(doc), "--resolve", "--root", f"proj={proj}", "--library", f"lib={lib}", "--json"],
    )
    env = json.loads(out)
    assert code == 0 and err == "" and env["kind"] == "references"
    files = env["data"]["files"]
    assert [f["resolution"]["status"] for f in files] == [
        "moved",
        "moved",
        "missing",
    ]  # missing still exits 0
    assert files[1]["resolution"]["match"] == {"root": "lib", "path": "q.SLDPRT"}
    assert [r["id"] for r in env["data"]["resolution"]["roots"]] == ["proj", "lib"]
    code, out, _err = _run(
        capsys, ["references", str(doc), "--resolve", "--path-map", f"S:\\Std={lib}", "--json"]
    )
    assert code == 0 and json.loads(out)["data"]["files"][1]["resolution"]["rule"] == "path_map"
    code, out, _err = _run(capsys, ["references", str(doc), "--resolve"])
    assert code == 0 and "resolution: moved 1, missing 2" in out and "rebased, high confidence" in out
    code, out, _err = _run(capsys, ["references", str(doc), "--json"])
    assert code == 0 and json.loads(out)["data"]["resolution"] is None


def test_cli_resolution_can_stay_inside_its_roots_as_the_service_does(tmp_path, capsys):
    """``--no-outside-roots`` gives the REST service's rule (C2): no point lookup outside the
    roots, a path mapping's target included, so the same roots give the service's answer."""
    import json

    proj = tmp_path / "Proj"
    write(proj / "parts" / "p.SLDPRT", part())
    lib = tmp_path / "Lib"  # not a root: reached only through the path map
    write(lib / "q.SLDPRT", part())
    doc = write(
        proj / "asm.SLDASM",
        assembly(
            [("Q:\\Old\\Proj\\parts\\p.SLDPRT", CT), ("S:\\Std\\q.SLDPRT", CT)],
            folder_at_save="Q:\\Old\\Proj\\",
        ),
    )
    mapping = f"S:\\Std={lib}"
    base = ["references", str(doc), "--resolve", "--root", f"proj={proj}", "--path-map", mapping, "--json"]
    code, out, _err = _run(capsys, base)
    data = json.loads(out)["data"]
    assert code == 0 and data["files"][1]["resolution"]["rule"] == "path_map"  # control: found outside
    assert data["resolution"]["outside_roots"] is True
    code, out, _err = _run(capsys, [*base, "--no-outside-roots"])
    data = json.loads(out)["data"]
    assert code == 0 and data["resolution"]["outside_roots"] is False
    assert [f["resolution"]["status"] for f in data["files"]] == ["moved", "missing"]
    with open_document(doc) as d:
        roots = Roots([Root("proj", str(proj))])
        res = resolve_references(d, roots, path_map=[f"S:\\Std={lib}"], allow_outside_roots=False)
        assert data == model.build_references(d, resolution=res)


@pytest.mark.parametrize(
    ("args", "exit_code", "error"),
    [
        (["--root", "proj=."], 2, "invalid_argument"),  # --root needs --resolve
        (["--no-outside-roots"], 2, "invalid_argument"),  # and so does staying inside them
        (["--resolve", "--root", "nofolder"], 2, "invalid_argument"),
        (["--resolve", "--root", "Bad=."], 2, "invalid_argument"),
        (["--resolve", "--path-map", "nonsense"], 2, "invalid_argument"),
        pytest.param(
            ["--resolve", "--root", "dav=\\\\host@SSL\\share"],
            3,
            "path_refused",
            # elsewhere a backslash is an ordinary character in a file name
            marks=pytest.mark.skipif(os.name != "nt", reason="a share path is a Windows path"),
        ),
        (["--resolve", "--root", "gone=MISSING_FOLDER"], 1, "not_found"),
    ],
)
def test_cli_references_resolve_errors(tmp_path, capsys, args, exit_code, error):
    import json

    doc = write(tmp_path / "Doc" / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    args = [a.replace("MISSING_FOLDER", str(tmp_path / "missing")) for a in args]
    code, out, err = _run(capsys, ["references", str(doc), *args, "--json"])
    env = json.loads(out)
    assert (code, env["ok"], env["error"]["code"], err) == (exit_code, False, error, "")


def test_cli_exits_4_when_an_index_was_cut_short(tmp_path, capsys, monkeypatch):
    import json

    doc = write(tmp_path / "Doc" / "asm.SLDASM", assembly([("Q:\\Old\\p.SLDPRT", CT)]))
    write(tmp_path / "Doc" / "sub" / "p.SLDPRT", part())  # a second entry: one is the limit
    real = cli.resolve_references
    monkeypatch.setattr(cli, "resolve_references", lambda *a, **k: real(*a, max_examined=1, **k))
    code, out, _err = _run(capsys, ["references", str(doc), "--resolve", "--json"])
    env = json.loads(out)
    assert code == 4 and env["ok"] and env["data"]["resolution"]["index_partial"] is True
