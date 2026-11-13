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
import json
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, part_with_externals, resolving_assembly
from jsonschema_subset import validate
from solidseas import cli, model, pdm
from solidseas.pdm.check import (
    CheckResult,
    Finding,
    check_project,
    is_toolbox_path,
    plan_copies,
)
from solidseas.resolve import ResolutionInput, resolve_references
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


def assembly(refs, *, imported=(), folder_at_save: str = "") -> bytes:
    """A top assembly using one instance of each stored path in ``refs``; file keys are
    "2", "3"... in order, and the indexes in ``imported`` carry ``swImportedPath``.
    ``folder_at_save`` is the folder the assembly says it was saved in."""
    t = TreeXml()
    t.top("m1")
    for i, stored in enumerate(refs, start=2):
        attrs = {"swCreationTime": str(CT)}
        if i - 2 in imported:
            attrs["swImportedPath"] = "C:\\Imports\\thing.step"
        t.file(str(i), stored, **attrs)
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t, folder_at_save=folder_at_save)


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
    res = check_project(a, library=vault / "Library", copy_toolbox=True)
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
        "needs_confirmation": 0,
        "toolbox": 2,
        "inside_parent": 1,
        "missing": 1,
        "different_document": 1,
        "ambiguous": 0,
        "toolbox_not_found": 1,
    }
    assert not res.self_contained and len(res.problems()) == 7


def test_toolbox_parts_are_no_problem_by_default_because_the_installation_loads_them(vault):
    res = check_project(vault / "Projects" / "A", library=vault / "Library")
    assert "toolbox" not in {f.result for f in res.problems()}
    assert all(c.source.name != "hex.SLDPRT" for c in plan_copies(res).copies)
    # the one found nowhere is counted on its own, though it is no problem either
    nut = by_name(res)["asm.SLDASM", "nut.SLDPRT"]
    assert (nut.result, nut.found) == ("toolbox", None) and nut not in res.problems()
    assert res.counts()["toolbox"] == 2 and res.counts()["toolbox_not_found"] == 1


def test_without_the_library_a_file_there_is_elsewhere(vault):
    res = check_project(vault / "Projects" / "A")
    lib = by_name(res)["asm.SLDASM", "bolt.SLDPRT"]
    assert (lib.result, lib.place, lib.found_in) == ("outside", "elsewhere", vault / "Library")


def test_a_library_part_beyond_the_search_is_missing_with_the_file_as_a_candidate(tmp_path):
    """SOLIDWORKS' search would not reach this library, so the reference is missing,
    and the file the library holds is named as a candidate, not as found."""
    project = tmp_path / "Work" / "Proj"
    write(project / "asm.SLDASM", assembly(["Q:\\Z\\washer.SLDPRT"]))
    library = tmp_path / "Elsewhere" / "Lib"
    write(library / "std" / "washer.SLDPRT", part())
    res = check_project(project, library=library)
    (f,) = res.findings
    assert (f.result, f.found, f.place, f.rule) == ("missing", None, None, None)
    assert f.candidates == (library / "std" / "washer.SLDPRT",)
    assert not res.self_contained and plan_copies(res).copies == ()
    assert check_project(project).findings[0].candidates == ()


def test_a_file_only_the_name_index_finds_is_missing_and_a_toolbox_part_stays_toolbox(tmp_path):
    """A file of that name deeper in the project is out of SOLIDWORKS' search: the
    reference is missing with the file as a candidate, and the default rules still
    find it by name. A Toolbox part whose copy only the name index finds stays toolbox."""
    a = tmp_path / "Projects" / "A"
    write(a / "deep" / "far.SLDPRT", part())
    write(a / "_Toolbox parts" / "hex.SLDPRT", part())
    write(a / "deep" / "other" / "gone.SLDPRT", part(OTHER))  # another document: no candidate
    doc = write(
        a / "asm.SLDASM",
        assembly(
            [
                "Q:\\Old\\far.SLDPRT",
                "Q:\\SOLIDWORKS Data\\browser\\hex.SLDPRT",
                "Q:\\Old\\gone.SLDPRT",
            ]
        ),
    )
    assert resolve_default(doc, a).results["2"].rule == "name_index"  # the default rules are unchanged
    res = check_project(a)
    f = by_name(res)
    far = f["asm.SLDASM", "far.SLDPRT"]
    assert (far.result, far.status, far.found, far.searched) == ("missing", "missing", None, False)
    assert far.candidates == (a / "deep" / "far.SLDPRT",) and far in res.problems()
    hex_ = f["asm.SLDASM", "hex.SLDPRT"]
    assert (hex_.result, hex_.toolbox, hex_.found) == ("toolbox", True, None)
    assert hex_.candidates == (a / "_Toolbox parts" / "hex.SLDPRT",) and hex_ not in res.problems()
    gone = f["asm.SLDASM", "gone.SLDPRT"]
    assert (gone.result, gone.candidates) == ("missing", ())
    assert res.counts()["missing"] == 2 and res.counts()["toolbox_not_found"] == 1


def test_the_first_file_the_search_reaches_decides(tmp_path):
    """Beside the document is a file of that name made as another document. SOLIDWORKS'
    first probe lands there, so the check reports it as a different document and does
    not go on to the right file further up or in another folder."""
    a = tmp_path / "Projects" / "A"
    write(a / "sub" / "w.SLDPRT", part(OTHER))
    write(a / "Z" / "w.SLDPRT", part())  # under a stored tail, one folder up: the next step
    write(a / "sub" / "x.SLDPRT", part(OTHER))
    write(a / "deep" / "x.SLDPRT", part())  # only by name
    write(a / "sub" / "u.SLDPRT", part())
    doc = write(
        a / "sub" / "asm.SLDASM",
        assembly(["Q:\\Old\\Z\\w.SLDPRT", "Q:\\Old\\x.SLDPRT", "Q:\\Old\\u.SLDPRT"]),
    )
    default = resolve_default(doc, a).results
    assert (default["2"].identity, default["3"].rule) == ("match", "name_index")  # the default rules
    res = check_project(a)
    f = by_name(res)
    w = f["asm.SLDASM", "w.SLDPRT"]
    assert (w.result, w.found, w.identity, w.rule) == (
        "different_document",
        a / "sub" / "w.SLDPRT",
        "differ",
        "same_folder",
    )
    assert "identity_mismatch" in w.warnings
    x = f["asm.SLDASM", "x.SLDPRT"]
    assert (x.result, x.found, x.candidates) == ("different_document", a / "sub" / "x.SLDPRT", ())
    u = f["asm.SLDASM", "u.SLDPRT"]
    assert (u.result, u.found) == ("ok", a / "sub" / "u.SLDPRT")
    assert plan_copies(res).copies == ()


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


def test_plan_copies_puts_each_file_beside_each_document_using_it(vault):
    """SOLIDWORKS tries the bare name only in the document's own folder, so a copy in a
    folder above it would not be found: each document's folder gets its own copy."""
    a = vault / "Projects" / "A"
    plan = plan_copies(check_project(a, library=vault / "Library", copy_toolbox=True))
    copies = {c.destination: c for c in plan.copies}
    assert set(copies) == {
        a / "b.SLDPRT",
        a / "sub" / "b.SLDPRT",
        a / "bolt.SLDPRT",
        a / "hex.SLDPRT",
    }
    b = copies[a / "b.SLDPRT"]
    assert b.source == vault / "Projects" / "B" / "b.SLDPRT" and b.referenced_by == (a / "asm.SLDASM",)
    assert copies[a / "sub" / "b.SLDPRT"].referenced_by == (a / "sub" / "asm2.SLDASM",)
    assert copies[a / "bolt.SLDPRT"].place == "library"
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


# --------------------------------------------------------------------------- the documented search order
def resolve_default(doc: Path, project: Path):
    """The resolver's default rules, as every caller but the check uses them."""
    from solidseas.formats.solidworks import open_document

    with open_document(doc, hold_open=True) as d:
        inp = ResolutionInput.from_document(d)
    return resolve_references(inp, {"project": str(project)}, search_above_roots=True)


def test_a_copy_beside_the_document_wins_over_the_old_relative_position(tmp_path):
    """The assembly was saved in Q:\\Old\\A and stores Q:\\Old\\B\\b.SLDPRT. Projects A
    and B were copied side by side, so the old relative position still holds a file,
    but the same file sits beside the assembly too: SOLIDWORKS' search looks there
    first, and has no relative-position step."""
    projects = tmp_path / "Projects"
    a = projects / "A"
    write(projects / "B" / "b.SLDPRT", part())
    write(a / "b.SLDPRT", part())
    doc = write(a / "asm.SLDASM", assembly(["Q:\\Old\\B\\b.SLDPRT"], folder_at_save="Q:\\Old\\A\\"))
    assert resolve_default(doc, a).results["2"].rule == "rebased"  # the default rules are unchanged
    (f,) = check_project(a).findings
    assert (f.result, f.rule, f.found, f.identity) == ("ok", "same_folder", a / "b.SLDPRT", "match")
    assert plan_copies(check_project(a)).copies == ()


def test_an_imported_bare_name_with_a_real_file_beside_it_is_that_file(tmp_path):
    a = tmp_path / "Projects" / "A"
    write(a / "real.SLDPRT", part())  # the stored creation time: the file the assembly used
    write(a / "other.SLDPRT", part(OTHER))  # that name, but another document
    write(a / "deep" / "far.SLDPRT", part())  # only below the folder: SOLIDWORKS would not look
    doc = write(
        a / "asm.SLDASM",
        assembly(
            ["real.SLDPRT", "other.SLDPRT", "far.SLDPRT", "gone.SLDPRT"],
            imported=(0, 1, 2, 3),
        ),
    )
    assert resolve_default(doc, a).results["2"].status == "inside_parent"  # the default rules
    f = by_name(check_project(a))
    real = f["asm.SLDASM", "real.SLDPRT"]
    assert (real.result, real.rule, real.found, real.identity) == (
        "ok",
        "same_folder",
        a / "real.SLDPRT",
        "match",
    )
    for name in ("other.SLDPRT", "far.SLDPRT", "gone.SLDPRT"):
        got = f["asm.SLDASM", name]
        assert (got.result, got.status, got.found) == ("inside_parent", "inside_parent", None), name


def test_a_bare_name_found_only_in_a_folder_above_needs_confirmation(tmp_path):
    """The help topic tries the bare name only in the document's own folder, so a file
    found only as the bare name in a folder above is reported for the user to confirm
    in SOLIDWORKS, and the plan copies it beside the document."""
    a = tmp_path / "Projects" / "A"
    write(a / "w.SLDPRT", part())
    write(a / "sub" / "Z" / "z.SLDPRT", part())  # under a stored tail: the documented search
    doc = write(
        a / "sub" / "asm.SLDASM",
        assembly(["Q:\\Z\\w.SLDPRT", "Q:\\Y\\Z\\z.SLDPRT"]),
    )
    assert resolve_default(doc, a).results["2"].rule == "suffix_probe"  # the default rules
    res = check_project(a)
    f = by_name(res)
    w = f["asm.SLDASM", "w.SLDPRT"]
    assert (w.result, w.rule, w.found, w.place, w.searched) == (
        "needs_confirmation",
        "bare_name_above",
        a / "w.SLDPRT",
        "project",
        False,
    )
    assert w in res.problems() and not res.self_contained
    z = f["asm.SLDASM", "z.SLDPRT"]
    assert (z.result, z.rule) == ("ok", "suffix_probe")
    assert res.counts()["needs_confirmation"] == 1
    plan = plan_copies(res)
    assert [(c.source, c.destination, c.place) for c in plan.copies] == [
        (a / "w.SLDPRT", a / "sub" / "w.SLDPRT", "project")
    ]
    assert plan.conflicts == () and not (a / "sub" / "w.SLDPRT").exists()
    # with that copy made, the document finds it in its own folder
    write(a / "sub" / "w.SLDPRT", part())
    assert by_name(check_project(a))["asm.SLDASM", "w.SLDPRT"].result == "ok"


def test_another_document_reached_only_by_the_bare_name_above_is_missing(tmp_path):
    """The bare name above is no step of the help topic, so another document found only
    there decides nothing: the reference is missing, and the file is noted."""
    a = tmp_path / "Projects" / "A"
    write(a / "w.SLDPRT", part(OTHER))
    doc = write(a / "sub" / "asm.SLDASM", assembly(["Q:\\Z\\w.SLDPRT"]))
    from solidseas.formats.solidworks import open_document

    with open_document(doc, hold_open=True) as d:
        inp = ResolutionInput.from_document(d)
    r = resolve_references(
        inp,
        {"project": str(a)},
        allow_outside_roots=True,
        search_above_roots=True,
        search="documented",
    ).results["2"]
    assert (r.status, r.match, r.rule) == ("missing", None, None)
    assert [(c.location.path, c.found_by, c.identity) for c in r.candidates] == [
        ("w.SLDPRT", "bare_name_above", "differ")
    ]
    assert "other_document_above" in [w.code for w in r.warnings]
    assert "identity_mismatch" not in [w.code for w in r.warnings]
    res = check_project(a)
    w = by_name(res)["asm.SLDASM", "w.SLDPRT"]
    assert (w.result, w.found, w.rule, w.searched) == ("missing", None, None, False)
    assert "other_document_above" in w.warnings
    assert res.counts()["different_document"] == 0 and res.counts()["missing"] == 1
    assert plan_copies(res).copies == ()


def test_a_copy_beside_the_document_never_goes_over_another_file(tmp_path):
    """The file is in a folder above the document, but beside the document is a file of
    that name made as another document: the plan cannot put the copy there and says so."""
    a = tmp_path / "Projects" / "A"
    write(a / "w.SLDPRT", part())
    write(a / "sub" / "w.SLDPRT", part(OTHER))
    found = Finding(
        a / "sub" / "asm.SLDASM", "2", "Q:\\Z\\w.SLDPRT", "w.SLDPRT", None, "needs_confirmation",
        a / "w.SLDPRT", "project", a, "moved", "bare_name_above", "match", False, False,
    )  # fmt: skip
    plan = plan_copies(CheckResult(a, None, False, 1, (found,)))
    assert plan.copies == ()
    assert [(c.source, c.destination) for c in plan.conflicts] == [(a / "w.SLDPRT", a / "sub" / "w.SLDPRT")]
    assert (a / "sub" / "w.SLDPRT").read_bytes() == part(OTHER)


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


# --------------------------------------------------------------------------- pdm check on the command line
def run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


def checked(env: dict) -> dict:
    assert env["kind"] == "pdm_result" and env["ok"], env
    assert validate(env, model.envelope_schema("pdm_result"), strict=True) == []
    assert env["data"]["action"] == "check"
    return env["data"]["check"]


def test_pdm_check_and_plan_as_json(capsys, vault):
    pdm.init(vault)
    pdm.open(vault).library.add(vault / "Library" / "bolt.SLDPRT", description="M6 bolt")
    a = vault / "Projects" / "A"
    code, env = run(capsys, "pdm", "check", str(a / "sub"), "--plan")
    data = checked(env)
    (p,) = data["projects"]
    assert code == 0 and data["scope"] == "Projects/A" and data["plan"] and not data["fix"]
    assert p["project"]["path"] == "Projects/A" and p["documents"] == 4 and not p["self_contained"]
    assert sorted(f["result"] for f in p["findings"]) == [
        "different_document",
        "missing",
        "outside",
        "outside",
        "outside",
    ]
    copies = {Path(c["source"]).name: c for c in p["plan"]["copies"]}
    assert set(copies) == {"b.SLDPRT", "bolt.SLDPRT"}
    assert (copies["bolt.SLDPRT"]["item"], copies["b.SLDPRT"]["item"]) == ("SS-00001", None)
    assert p["fix"] is None and not (a / "b.SLDPRT").exists()
    code, env = run(capsys, "pdm", "check", str(a), "--copy-toolbox")
    p = checked(env)["projects"][0]
    assert p["plan"] is None and sum(f["result"] == "toolbox" for f in p["findings"]) == 2


def test_pdm_check_fix_copies_in_new_files_and_checks_again(capsys, vault):
    pdm.init(vault)
    pdm.open(vault).library.add(vault / "Library" / "bolt.SLDPRT")
    a = vault / "Projects" / "A"
    code, env = run(capsys, "pdm", "check", str(a), "--fix")
    data = checked(env)
    (p,) = data["projects"]
    assert code == 0 and data["fix"] and data["plan"]
    copied = {Path(c["destination"]): c for c in p["fix"]["copied"]}
    assert set(copied) == {a / "b.SLDPRT", a / "sub" / "b.SLDPRT", a / "bolt.SLDPRT"}
    assert p["fix"]["failed"] == []
    bolt = copied[a / "bolt.SLDPRT"]
    assert bolt["item"] == "SS-00001" and bolt["link"]["how"] == "fix"
    assert copied[a / "b.SLDPRT"]["link"] is None
    assert (a / "b.SLDPRT").read_bytes() == (vault / "Projects" / "B" / "b.SLDPRT").read_bytes()
    assert (a / "sub" / "b.SLDPRT").read_bytes() == (vault / "Projects" / "B" / "b.SLDPRT").read_bytes()
    # checked again: what is left cannot be fixed by a copy
    assert sorted(f["result"] for f in p["findings"]) == ["different_document", "missing"]
    assert p["plan"]["copies"] == []
    assert p["fix"]["checkin"]["note"].startswith("Copied 3 files into Projects/A")
    lib = pdm.open(vault).library
    (link,) = lib.links()
    assert (link.item, link.path, link.how) == ("SS-00001", "Projects/A/bolt.SLDPRT", "fix")
    assert lib.updates()["counts"]["current"] == 1
    # a second fix has nothing to copy
    code, env = run(capsys, "pdm", "check", str(a), "--fix")
    p = checked(env)["projects"][0]
    assert p["fix"]["copied"] == [] and len(lib.links()) == 1


def test_pdm_check_fix_never_writes_over_another_file(capsys, vault):
    pdm.init(vault)
    a = vault / "Projects" / "A"
    write(a / "bolt.SLDPRT", part(OTHER))  # another document of that name, already there
    code, env = run(capsys, "pdm", "check", str(a), "--fix")
    p = checked(env)["projects"][0]
    assert [Path(c["destination"]) for c in p["fix"]["copied"]] == [a / "b.SLDPRT", a / "sub" / "b.SLDPRT"]
    assert (a / "bolt.SLDPRT").read_bytes() == part(OTHER)


def test_pdm_check_every_project_that_is_not_archived(capsys, vault):
    pdm.init(vault)
    (vault / ".solidseas" / "vault" / "vault.json").write_text(
        json.dumps({"format": 1, "archive": ["SOLIDWORKS Data"]})
    )
    code, env = run(capsys, "pdm", "check", str(vault))
    data = checked(env)
    assert code == 0 and data["scope"] == ""
    rows = {p["project"]["path"]: p for p in data["projects"]}
    assert set(rows) == {"Projects/A", "Projects/B"}  # the archive and the library are not checked
    assert rows["Projects/B"]["self_contained"] and data["self_contained"] == 1
    code, env = run(capsys, "pdm", "check", str(vault / "Library"))
    assert code == 2 and env["error"]["code"] == "invalid_argument"


def test_pdm_check_plain_words(capsys, vault):
    pdm.init(vault)
    a = vault / "Projects" / "A"
    assert cli.main(["pdm", "check", str(a), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "Projects/A: 5 problems in 4 documents" in out
    assert "in another project" in out and "would copy" in out
    assert "1 Toolbox part found nowhere" in out
    assert cli.main(["pdm", "check", str(vault / "Projects" / "B")]) == 0
    assert "Projects/B: self-contained (1 document)" in capsys.readouterr().out
    assert cli.main(["pdm", "check", str(a), "--fix"]) == 0
    assert "copied    " in capsys.readouterr().out


def test_pdm_check_names_a_file_out_of_the_search(capsys, tmp_path):
    v = tmp_path / "Vault"
    a = v / "Projects" / "A"
    write(a / "deep" / "far.SLDPRT", part())
    write(a / "asm.SLDASM", assembly(["Q:\\Old\\far.SLDPRT"]))
    pdm.init(v)
    code, env = run(capsys, "pdm", "check", str(a))
    (f,) = checked(env)["projects"][0]["findings"]
    assert (f["result"], f["found"], f["candidates"]) == ("missing", None, [str(a / "deep" / "far.SLDPRT")])
    assert cli.main(["pdm", "check", str(a)]) == 0
    out = capsys.readouterr().out
    assert f"asm.SLDASM: far.SLDPRT, out of SOLIDWORKS' search: {a / 'deep' / 'far.SLDPRT'}" in out


# --------------------------------------------------------------------------- planning to closure
def top(refs) -> bytes:
    """An assembly using each stored path in ``refs`` with no stored creation time, so a
    sub-assembly (whose own creation time is the fixture's) is taken as found."""
    t = TreeXml()
    t.top("m1")
    for i, stored in enumerate(refs, start=2):
        kind = "ASSEMBLY" if stored.upper().endswith(".SLDASM") else "PART"
        t.file(str(i), stored, kind)
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t)


def make(plan) -> None:
    for c in plan.copies:
        c.destination.write_bytes(c.source.read_bytes())


def test_a_copied_subassembly_gets_the_parts_it_finds_only_above_its_new_folder(tmp_path):
    """The case met on a real library: the sub-assembly's parts sit beside it, but the
    copy goes beside the assembly using it, a folder down, from where its parts are found
    only by the bare name one folder above. The plan copies them beside the copy too."""
    a = tmp_path / "Projects" / "A"
    write(a / "p.SLDPRT", part())
    write(a / "sub.SLDASM", assembly(["Q:\\Z\\p.SLDPRT"]))
    write(a / "top" / "asm.SLDASM", top(["Q:\\Z\\sub.SLDASM"]))
    res = check_project(a)
    assert res.counts()["needs_confirmation"] == 1 and res.counts()["ok"] == 1
    plan = plan_copies(res)
    assert [(c.source, c.destination, c.round, c.referenced_by) for c in plan.copies] == [
        (a / "sub.SLDASM", a / "top" / "sub.SLDASM", 1, (a / "top" / "asm.SLDASM",)),
        (a / "p.SLDPRT", a / "top" / "p.SLDPRT", 2, (a / "top" / "sub.SLDASM",)),
    ]
    assert plan.rounds == 2 and plan.unplaced == () and plan.conflicts == ()
    assert not (a / "top" / "sub.SLDASM").exists()  # a plan writes nothing
    # one round only: the sub-assembly's part is left, and the plan says why
    short = plan_copies(res, max_rounds=1)
    assert [c.destination for c in short.copies] == [a / "top" / "sub.SLDASM"]
    (u,) = short.unplaced
    assert (u.document, u.name, u.reason, u.round, u.found) == (
        a / "top" / "sub.SLDASM",
        "p.SLDPRT",
        "round_limit",
        2,
        a / "p.SLDPRT",
    )
    make(plan)
    after = check_project(a)
    assert after.counts()["needs_confirmation"] == 0 and after.counts()["outside"] == 0
    assert after.self_contained and plan_copies(after).copies == ()


def test_a_plan_follows_a_chain_of_subassemblies(tmp_path):
    projects = tmp_path / "Projects"
    a, b = projects / "A", projects / "B"
    write(b / "p.SLDPRT", part())
    write(b / "s2.SLDASM", assembly(["Q:\\Old\\B\\p.SLDPRT"]))
    write(b / "s1.SLDASM", top(["Q:\\Old\\B\\s2.SLDASM"]))
    write(a / "asm.SLDASM", top(["Q:\\Old\\B\\s1.SLDASM"]))
    res = check_project(a)
    assert res.counts()["outside"] == 1
    plan = plan_copies(res)
    assert [(c.source, c.destination, c.round, c.referenced_by, c.place) for c in plan.copies] == [
        (b / "s1.SLDASM", a / "s1.SLDASM", 1, (a / "asm.SLDASM",), "other_project"),
        (b / "s2.SLDASM", a / "s2.SLDASM", 2, (a / "s1.SLDASM",), "other_project"),
        (b / "p.SLDPRT", a / "p.SLDPRT", 3, (a / "s2.SLDASM",), "other_project"),
    ]
    assert plan.rounds == 3 and plan.unplaced == ()
    short = plan_copies(res, max_rounds=2)
    assert short.rounds == 2 and [c.round for c in short.copies] == [1, 2]
    assert [(u.document, u.reason, u.round) for u in short.unplaced] == [(a / "s2.SLDASM", "round_limit", 3)]
    make(plan)
    after = check_project(a)
    assert after.self_contained and after.documents == 4


def test_a_conflict_in_a_later_round_is_reported_with_its_round(tmp_path):
    """Two sub-assemblies copied into one folder each need a part of the same name, from
    different files: the first takes the name, the second is a conflict of round 2. A
    reference a copy cannot find at all is listed as unplaced."""
    projects = tmp_path / "Projects"
    a, b, c = projects / "A", projects / "B", projects / "C"
    write(b / "p.SLDPRT", part())
    write(c / "p.SLDPRT", part_with_creation_time(CT, keywords=False))  # other content
    write(b / "s1.SLDASM", assembly(["Q:\\Old\\B\\p.SLDPRT"]))
    write(c / "s2.SLDASM", assembly(["Q:\\Old\\C\\p.SLDPRT", "Q:\\Old\\C\\gone.SLDPRT"]))
    write(a / "asm.SLDASM", top(["Q:\\Old\\B\\s1.SLDASM", "Q:\\Old\\C\\s2.SLDASM"]))
    plan = plan_copies(check_project(a))
    assert [(c.source, c.destination, c.round) for c in plan.copies] == [
        (b / "s1.SLDASM", a / "s1.SLDASM", 1),
        (c / "s2.SLDASM", a / "s2.SLDASM", 1),
        (b / "p.SLDPRT", a / "p.SLDPRT", 2),
    ]
    (clash,) = plan.conflicts
    assert (clash.source, clash.destination, clash.referenced_by, clash.round) == (
        c / "p.SLDPRT",
        a / "p.SLDPRT",
        (a / "s2.SLDASM",),
        2,
    )
    assert clash.reason == "another planned copy has this name here"
    (gone,) = plan.unplaced
    assert (gone.document, gone.source, gone.name, gone.reason, gone.round) == (
        a / "s2.SLDASM",
        c / "s2.SLDASM",
        "gone.SLDPRT",
        "missing",
        2,
    )


def test_pdm_check_fix_makes_the_closed_plan(capsys, tmp_path):
    """The part of a copied sub-assembly sits a folder above its source: from the copy's
    new folder it is outside, so the plan copies it too, and one --fix leaves nothing
    outside and nothing to confirm."""
    v = tmp_path / "Vault"
    a, b = v / "Projects" / "A", v / "Projects" / "B"
    write(b / "p.SLDPRT", part())
    write(b / "sub" / "sub.SLDASM", assembly(["Q:\\Old\\B\\p.SLDPRT"]))
    write(a / "asm.SLDASM", top(["Q:\\Old\\B\\sub\\sub.SLDASM"]))
    pdm.init(v)
    code, env = run(capsys, "pdm", "check", str(a), "--plan")
    p = checked(env)["projects"][0]
    assert p["plan"]["rounds"] == 2 and p["plan"]["unplaced"] == []
    rows = {Path(c["destination"]).name: c for c in p["plan"]["copies"]}
    assert {k: r["round"] for k, r in rows.items()} == {"sub.SLDASM": 1, "p.SLDPRT": 2}
    assert rows["p.SLDPRT"]["referenced_by"] == [str(a / "sub.SLDASM")]
    code, env = run(capsys, "pdm", "check", str(a), "--fix")
    p = checked(env)["projects"][0]
    assert sorted(Path(c["destination"]).name for c in p["fix"]["copied"]) == ["p.SLDPRT", "sub.SLDASM"]
    assert p["fix"]["failed"] == [] and p["self_contained"]
    assert p["counts"]["needs_confirmation"] == 0 and p["counts"]["outside"] == 0
    assert p["plan"]["copies"] == [] and p["plan"]["unplaced"] == []
