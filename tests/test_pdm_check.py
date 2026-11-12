"""The PDM's self-contained check (``docs/PDM.md`` 5) on project trees built in ``tmp_path``.

A library folder ``Vault`` holds ``Projects/A`` (the project checked), its neighbour
``Projects/B`` and the common-parts folder ``Library``. The assemblies are crafted
(``builders.resolving_assembly``) to store chosen paths and creation times, beside
copies of o02 that claim chosen creation times (``builders.part_with_creation_time``),
as ``test_resolve.py`` does. Stored paths use the drive letter ``Q:``, which the
gateway is told does not exist, so every file is found by SOLIDWORKS' folder search
from where the document is now, never through a stored path.
"""

import functools
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, part_with_externals, resolving_assembly
from solidseas.pdm.check import (
    CheckResult,
    Finding,
    check_project,
    is_toolbox_path,
    plan_copies,
)
from solidseas.resolve import gateway as gateway_mod

CT = 1_700_000_000
OTHER = 1_600_000_000


@pytest.fixture(autouse=True)
def fake_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


@functools.cache
def part(ct: int = CT) -> bytes:
    return part_with_creation_time(ct)


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def assembly(refs, *, imported=()) -> bytes:
    """A top assembly using one instance of each stored path in ``refs``; file keys are
    "2", "3"... in order, and the indexes in ``imported`` carry ``swImportedPath``."""
    t = TreeXml()
    t.top("m1")
    for i, stored in enumerate(refs, start=2):
        attrs = {"swCreationTime": str(CT)}
        if i - 2 in imported:
            attrs["swImportedPath"] = "C:\\Imports\\thing.step"
        t.file(str(i), stored, **attrs)
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Vault"
    a = v / "Projects" / "A"
    write(a / "parts" / "p.SLDPRT", part())
    write(a / "d.SLDPRT", part(OTHER))  # the stored name, but another document
    write(v / "Projects" / "B" / "b.SLDPRT", part())
    write(v / "Library" / "bolt.SLDPRT", part())
    write(v / "SOLIDWORKS Data" / "browser" / "hex.SLDPRT", part())
    write(
        a / "asm.SLDASM",
        assembly(
            [
                "Q:\\Old\\A\\parts\\p.SLDPRT",  # ok: in the project
                "Q:\\Old\\B\\b.SLDPRT",  # outside: the neighbouring project
                "Q:\\Lib\\Library\\bolt.SLDPRT",  # outside: the library
                "Q:\\Old\\none.SLDPRT",  # missing
                "thing-1.SLDPRT",  # inside the parent: made by opening a STEP assembly
                "Q:\\SOLIDWORKS Data\\browser\\hex.SLDPRT",  # Toolbox, found outside
                "Q:\\Old\\A\\d.SLDPRT",  # different document
                "Q:\\SOLIDWORKS Data\\browser\\nut.SLDPRT",  # Toolbox, found nowhere
            ],
            imported=(4,),
        ),
    )
    write(a / "sub" / "asm2.SLDASM", assembly(["Q:\\Old\\B\\b.SLDPRT"]))
    write(a / "~$asm.SLDASM", b"lock")  # a SOLIDWORKS lock file is never read
    return v


def by_name(result: CheckResult) -> dict[tuple[str, str], Finding]:
    return {(f.document.name, (f.stored_path or "").rsplit("\\", 1)[-1]): f for f in result.findings}


def test_each_reference_gets_a_result(vault):
    a = vault / "Projects" / "A"
    res = check_project(a, library=vault / "Library")
    assert res.documents == 4 and res.unreadable == ()  # asm, asm2, p and d
    f = by_name(res)
    ok = f["asm.SLDASM", "p.SLDPRT"]
    assert (ok.result, ok.place, ok.found, ok.searched) == ("ok", "project", a / "parts" / "p.SLDPRT", True)
    sib = f["asm.SLDASM", "b.SLDPRT"]
    assert (sib.result, sib.place, sib.found_in, sib.rule) == (
        "outside",
        "other_project",
        vault / "Projects" / "B",
        "suffix_probe",
    )
    assert sib.found == vault / "Projects" / "B" / "b.SLDPRT" and sib.identity == "match"
    lib = f["asm.SLDASM", "bolt.SLDPRT"]
    assert (lib.result, lib.place, lib.found_in, lib.searched) == (
        "outside",
        "library",
        vault / "Library",
        True,
    )
    assert (f["asm.SLDASM", "none.SLDPRT"].result, f["asm.SLDASM", "none.SLDPRT"].found) == ("missing", None)
    inside = f["asm.SLDASM", "thing-1.SLDPRT"]
    assert (inside.result, inside.status, inside.found) == ("inside_parent", "inside_parent", None)
    hex_ = f["asm.SLDASM", "hex.SLDPRT"]
    assert (hex_.result, hex_.toolbox, hex_.place) == ("toolbox", True, "elsewhere")
    assert f["asm.SLDASM", "nut.SLDPRT"].result == "toolbox"
    diff = f["asm.SLDASM", "d.SLDPRT"]
    assert (diff.result, diff.identity, diff.found) == ("different_document", "differ", a / "d.SLDPRT")
    assert f["asm2.SLDASM", "b.SLDPRT"].result == "outside"
    assert res.counts() == {
        "ok": 1,
        "outside": 3,
        "toolbox": 2,
        "inside_parent": 1,
        "missing": 1,
        "different_document": 1,
        "ambiguous": 0,
    }
    assert not res.self_contained and len(res.problems()) == 7


def test_toolbox_parts_are_no_problem_when_the_installation_loads_them(vault):
    res = check_project(vault / "Projects" / "A", library=vault / "Library", toolbox_mandatory=False)
    assert "toolbox" not in {f.result for f in res.problems()}
    assert all(c.source.name != "hex.SLDPRT" for c in plan_copies(res).copies)


def test_without_the_library_a_file_there_is_elsewhere(vault):
    res = check_project(vault / "Projects" / "A")
    lib = by_name(res)["asm.SLDASM", "bolt.SLDPRT"]
    assert (lib.result, lib.place, lib.found_in) == ("outside", "elsewhere", vault / "Library")


def test_a_library_part_beyond_the_search_is_found_by_name(tmp_path):
    """SOLIDWORKS' search would not reach this library, but it holds the file: the check
    says where, and that only SolidSeas' name index found it there."""
    project = tmp_path / "Work" / "Proj"
    write(project / "asm.SLDASM", assembly(["Q:\\Z\\washer.SLDPRT"]))
    library = tmp_path / "Elsewhere" / "Lib"
    write(library / "std" / "washer.SLDPRT", part())
    (f,) = check_project(project, library=library).findings
    assert (f.result, f.place, f.rule, f.searched) == ("outside", "library", "name_index", False)
    assert check_project(project).findings[0].result == "missing"


def test_a_parts_external_files_and_its_import_source_are_checked(tmp_path):
    project = tmp_path / "Projects" / "P"
    write(project / "thing.step", b"ISO-10303-21;\n")
    write(tmp_path / "Projects" / "Q" / "base.SLDPRT", part())
    write(
        project / "p.SLDPRT",
        part_with_externals(
            [("Q:\\Old\\thing.step", "PART", "MBimport"), ("Q:\\Old\\Q\\base.SLDPRT", "PART", "Stock")]
        ),
    )
    found = {f.relation: f for f in check_project(project).findings}
    assert (found["import_source"].result, found["import_source"].identity) == ("ok", "unknown")
    assert (found["base_part"].result, found["base_part"].place) == ("outside", "other_project")


def test_plan_copies_puts_each_file_where_every_document_using_it_finds_it(vault):
    a = vault / "Projects" / "A"
    plan = plan_copies(check_project(a, library=vault / "Library"))
    copies = {c.source.name: c for c in plan.copies}
    assert set(copies) == {"b.SLDPRT", "bolt.SLDPRT", "hex.SLDPRT"}
    b = copies["b.SLDPRT"]
    assert b.source == vault / "Projects" / "B" / "b.SLDPRT"
    assert b.destination == a / "b.SLDPRT"  # the folder that holds asm and sub/asm2
    assert set(b.referenced_by) == {a / "asm.SLDASM", a / "sub" / "asm2.SLDASM"}
    assert (copies["bolt.SLDPRT"].destination, copies["bolt.SLDPRT"].place) == (a / "bolt.SLDPRT", "library")
    assert plan.conflicts == () and plan.present == ()
    assert not (a / "b.SLDPRT").exists()  # a plan writes nothing


def test_plan_copies_never_writes_over_another_file(tmp_path):
    projects = tmp_path / "Projects"
    a = projects / "A"
    write(projects / "B" / "gear.SLDPRT", part())
    write(projects / "C" / "gear.SLDPRT", part_with_creation_time(CT, keywords=False))  # other content
    write(projects / "B" / "deep" / "sub" / "x.SLDPRT", part())
    write(a / "asm.SLDASM", assembly(["Q:\\X\\B\\gear.SLDPRT", "Q:\\X\\C\\gear.SLDPRT"]))
    write(a / "deep" / "sub" / "asm.SLDASM", assembly(["Q:\\X\\B\\deep\\sub\\x.SLDPRT"]))
    res = check_project(a)
    plan = plan_copies(res)
    assert [(c.source, c.destination) for c in plan.copies] == [
        (projects / "B" / "gear.SLDPRT", a / "gear.SLDPRT"),
        (projects / "B" / "deep" / "sub" / "x.SLDPRT", a / "deep" / "sub" / "x.SLDPRT"),
    ]
    (clash,) = plan.conflicts
    assert (clash.source, clash.destination) == (projects / "C" / "gear.SLDPRT", a / "gear.SLDPRT")
    # a file already at the destination: the same content needs no copy, another is a conflict
    write(a / "gear.SLDPRT", part())
    write(a / "deep" / "sub" / "x.SLDPRT", part(OTHER))
    found = [f for f in res.findings if f.result == "outside"]
    plan = plan_copies(CheckResult(a, None, True, 2, tuple(found)))
    assert plan.copies == ()
    assert [c.destination for c in plan.present] == [a / "gear.SLDPRT"]
    assert sorted(c.destination for c in plan.conflicts) == [
        a / "deep" / "sub" / "x.SLDPRT",
        a / "gear.SLDPRT",
    ]
    assert (a / "deep" / "sub" / "x.SLDPRT").read_bytes() == part(OTHER)


def test_an_unreadable_document_is_listed_not_raised(tmp_path):
    project = tmp_path / "P"
    write(project / "broken.SLDPRT", b"not a document")
    res = check_project(project)
    assert res.documents == 1 and [p.name for p, _e in res.unreadable] == ["broken.SLDPRT"]
    assert not res.self_contained
    with pytest.raises(FileNotFoundError):
        check_project(tmp_path / "nowhere")


@pytest.mark.parametrize(
    "path, toolbox",
    [
        ("C:\\SOLIDWORKS Data\\browser\\ansi inch\\hex.sldprt", True),
        ("C:\\solidworks data (2)\\browser\\hex.sldprt", True),
        ("D:\\Shared\\Toolbox\\hex.sldprt", True),
        ("C:\\Jobs\\toolbox.SLDPRT", False),
        ("C:\\Jobs\\SOLIDWORKS Data Sheets\\a.SLDPRT", False),
        (None, False),
    ],
)
def test_toolbox_paths(path, toolbox):
    assert is_toolbox_path(path) is toolbox
