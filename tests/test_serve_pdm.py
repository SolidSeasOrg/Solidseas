"""The service's PDM routes and their MCP tools (``docs/API.md`` 8.6 and 5.21), over a
library built in a temporary folder from synthetic files: the library may be the root,
lie above it or inside it, and every answer names paths relative to the root only.

The self-contained check runs on a crafted assembly (``builders.resolving_assembly``)
whose stored paths use the drive letter ``Q:``, as in ``test_pdm_check.py``, so each
file is found by SOLIDWORKS' folder search from where the assembly is now."""

import json
import os
import shutil
from pathlib import Path

import pytest

from builders import TreeXml, part_with_creation_time, resolving_assembly
from jsonschema_subset import validate
from serve_support import Running
from solidseas import Root, Roots, model, pdm
from solidseas.pdm.check import check_project
from solidseas.serve import ServeConfig, Server, mcp
from support import FIXTURES

pytestmark = pytest.mark.usefixtures("outbound_guard")
XB_A = FIXTURES / "o02_boxA.x_b"  # SOLIDWORKS' own Parasolid export, a public fixture
CT = 1_700_000_000
PDM_TOOLS = {"pdm_status", "file_history", "file_version", "recent_checkins", "check_project"}


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def bump(path: Path, seconds: float = 2.0) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


def assembly(refs: list[str]) -> bytes:
    t = TreeXml()
    t.top("m1")
    for i, stored in enumerate(refs, start=2):
        t.file(str(i), stored, swCreationTime=str(CT))
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    return resolving_assembly(t)


@pytest.fixture(scope="module")
def lib(tmp_path_factory) -> Path:
    """``outer/CAD``, a library: two jobs with history, a project to check and a folder
    outside it (``outer/plain``) that is in no library."""
    outer = tmp_path_factory.mktemp("pdm") / "outer"
    cad = outer / "CAD"
    job = cad / "Jobs" / "1042"
    write(job / "bracket.sldprt", "bracket one")
    write(job / "plate.step", "plate one")
    shutil.copyfile(XB_A, job / "model.x_b")
    write(cad / "Jobs" / "1043" / "bracket.sldprt", "bracket one")
    write(cad / "Jobs" / "1043" / "old.step", "soon gone")
    write(cad / "Jobs" / "2001" / "p.SLDPRT", part_with_creation_time(CT))
    write(cad / "Jobs" / "2002" / "b.SLDPRT", part_with_creation_time(CT))
    write(cad / "Jobs" / "2002" / "sub" / "x.step", "in a project's subfolder")
    write(
        cad / "Jobs" / "2001" / "asm.SLDASM",
        assembly(["Q:\\Old\\2001\\p.SLDPRT", "Q:\\Old\\2002\\b.SLDPRT", "Q:\\Old\\none.SLDPRT"]),
    )
    (cad / "Library").mkdir()
    write(outer / "plain" / "loose.sldprt", "no library here")
    vault = pdm.init(cad)
    vault.checkin([job], "first cut", revision="A")
    write(job / "bracket.sldprt", "bracket two")
    bump(job / "bracket.sldprt")
    vault.checkin([job / "bracket.sldprt"], "holes moved", revision="B", who="Pat")
    vault.checkin([cad / "Jobs" / "1043"], "the other job")
    (cad / "Jobs" / "1043" / "old.step").unlink()
    vault.scan(cad / "Jobs" / "2001")
    write(job / "added.step", "added later")
    return cad


@pytest.fixture(scope="module")
def srv(lib):
    roots = {
        "cad": lib,
        "job": lib / "Jobs" / "1042",
        "deep": lib / "Jobs" / "2002" / "sub",
        "outer": lib.parent,
        "plain": lib.parent / "plain",
    }
    running = Running(roots, pdm=True)
    yield running
    running.close()


def ok(r) -> dict:
    assert r.status == 200, r.body[:400]
    env = r.json()
    assert validate(env, model.envelope_schema(env["kind"]), strict=True) == [], env["kind"]
    return env


def error(r, status: int, code: str) -> dict:
    assert r.status == status, r.body[:400]
    err = r.json()["error"]
    assert err["code"] == code and err["reader_message"] is None
    return err


def no_host_paths(srv, body: bytes, lib: Path) -> None:
    text = body.decode()
    for folder in (lib, lib.parent):
        assert str(folder) not in text and json.dumps(str(folder))[1:-1] not in text


# --------------------------------------------------------------------------- the routes
def test_status_lists_changes_relative_to_the_root(srv, lib):
    env = ok(srv.get("pdm/status", root="cad"))
    data = env["data"]
    assert env["kind"] == "pdm_status" and env["source"] == {"root": "cad", "path": ""}
    assert data["library"] == "" and data["scope"] == ""
    states = {f["path"]: f["state"] for f in data["files"]}
    assert states["Jobs/1042/added.step"] == "new"
    assert states["Jobs/1043/old.step"] == "gone"
    assert "Jobs/1042/bracket.sldprt" not in states  # unchanged files are counted, not listed
    assert data["counts"]["unchanged"] >= 3
    every = ok(srv.get("pdm/status", root="cad", path="Jobs/1042", unchanged="1"))["data"]
    assert every["scope"] == "Jobs/1042"
    assert {f["path"] for f in every["files"]} == {
        "Jobs/1042/added.step",
        "Jobs/1042/bracket.sldprt",
        "Jobs/1042/model.x_b",
        "Jobs/1042/plate.step",
    }
    one = ok(srv.get("pdm/status", root="cad", path="Jobs/1043/old.step"))["data"]  # a gone file
    assert [(f["path"], f["state"]) for f in one["files"]] == [("Jobs/1043/old.step", "gone")]
    no_host_paths(srv, srv.responses[-1].body, lib)


def test_a_root_below_the_library_sees_only_its_own_files(srv, lib):
    data = ok(srv.get("pdm/status", root="job", unchanged="true"))["data"]
    assert data["library"] is None  # it lies above the root
    assert {f["path"] for f in data["files"]} == {"added.step", "bracket.sldprt", "model.x_b", "plate.step"}
    checkins = ok(srv.get("pdm/checkins", root="job", scans="1"))["data"]["checkins"]
    assert [c["note"] for c in checkins] == ["holes moved", "first cut"]  # not the other job's
    assert {f["path"] for f in checkins[1]["files"]} == {"bracket.sldprt", "model.x_b", "plate.step"}
    no_host_paths(srv, srv.responses[-1].body, lib)


def test_a_library_inside_the_root_is_named_by_its_folder(srv, lib):
    data = ok(srv.get("pdm/status", root="outer", path="CAD/Jobs/1042"))["data"]
    assert data["library"] == "CAD" and data["scope"] == "CAD/Jobs/1042"
    assert [f["path"] for f in data["files"]] == ["CAD/Jobs/1042/added.step"]
    log = ok(srv.get("pdm/log", root="outer", path="CAD/Jobs/1042/bracket.sldprt"))["data"]
    assert log["path"] == "CAD/Jobs/1042/bracket.sldprt" and log["library"] == "CAD"


def test_log_lists_versions_with_their_checkin_notes(srv, lib):
    env = ok(srv.get("pdm/log", root="cad", path="Jobs/1042/bracket.sldprt"))
    data = env["data"]
    assert data["name"] == "bracket.sldprt" and data["git"] is None
    vault = [v for v in data["versions"] if v["source"] == "vault"]
    assert [v["number"] for v in vault] == [2, 1]
    assert [c["note"] for c in vault[0]["checkins"]] == ["holes moved"]
    assert vault[0]["checkins"][0]["revision"] == "B" and vault[0]["checkins"][0]["who"] == "Pat"
    assert [c["note"] for c in vault[1]["checkins"]] == ["first cut"]
    gone = ok(srv.get("pdm/log", root="cad", path="Jobs/1043/old.step"))["data"]  # gone, history kept
    assert gone["working"]["state"] == "missing" and [v["number"] for v in gone["versions"]] == [1]
    no_host_paths(srv, srv.responses[-1].body, lib)


def test_version_gives_one_versions_facts(srv, lib):
    data = ok(srv.get("pdm/version", root="cad", path="Jobs/1042/model.x_b", version="v1"))["data"]
    assert data["path"] == "Jobs/1042/model.x_b" and data["name"] == "model.x_b"
    assert data["source"] == "vault" and data["version"]["number"] == 1
    assert data["geometry"]["configurations"]
    err = error(
        srv.get("pdm/version", root="cad", path="Jobs/1042/model.x_b", version="v9"), 404, "version_not_found"
    )
    assert err["detail"]["parameter"] == "version"


def test_checkins_are_newest_first_and_paged(srv):
    first = ok(srv.get("pdm/checkins", root="cad", limit="1"))["data"]
    assert [c["note"] for c in first["checkins"]] == ["the other job"]
    assert first["scans"] is False and first["next_cursor"]
    second = ok(srv.get("pdm/checkins", root="cad", limit="1", cursor=first["next_cursor"]))["data"]
    assert [c["note"] for c in second["checkins"]] == ["holes moved"]
    rest = ok(srv.get("pdm/checkins", root="cad", limit="5", cursor=second["next_cursor"]))["data"]
    assert [c["note"] for c in rest["checkins"]] == ["first cut"] and rest["next_cursor"] is None
    with_scans = ok(srv.get("pdm/checkins", root="cad", scans="1"))["data"]["checkins"]
    assert with_scans[0]["auto"] is True and with_scans[0]["note"] is None
    only = ok(srv.get("pdm/checkins", root="cad", path="Jobs/1043"))["data"]["checkins"]
    assert [c["note"] for c in only] == ["the other job"] and only[0]["files_total"] == 2
    other = srv.get("pdm/checkins", root="cad", scans="1", cursor=first["next_cursor"])
    assert error(other, 400, "invalid_argument")["detail"]["parameter"] == "cursor"  # another query's


def test_check_reports_what_leaves_the_project(srv, lib):
    env = ok(srv.get("pdm/check", root="cad", path="Jobs/2001"))
    data = env["data"]
    assert data["project"] == {"path": "Jobs/2001", "name": "2001", "section": "Jobs", "archived": False}
    expected = check_project(lib / "Jobs" / "2001", library=lib / "Library")
    assert data["documents"] == expected.documents and data["counts"] == expected.counts()
    assert data["self_contained"] is expected.self_contained is False
    got = {(f["document"], f["file_name"]): f for f in data["findings"]}
    for f in expected.findings:
        row = got[("Jobs/2001/asm.SLDASM", f.file_name)]
        assert row["result"] == f.result and row["place"] == f.place
    p, b = got[("Jobs/2001/asm.SLDASM", "p.SLDPRT")], got[("Jobs/2001/asm.SLDASM", "b.SLDPRT")]
    assert p["result"] == "ok" and p["found"] == {"root": "cad", "path": "Jobs/2001/p.SLDPRT"}
    assert (
        b["result"] == "outside"
        and b["problem"]
        and b["found"] == {"root": "cad", "path": "Jobs/2002/b.SLDPRT"}
    )
    assert data["problems"] == len(expected.problems())
    inside = ok(srv.get("pdm/check", root="outer", path="CAD/Jobs/2001"))["data"]
    assert inside["project"]["path"] == "CAD/Jobs/2001"
    err = error(srv.get("pdm/check", root="cad", path="Jobs"), 400, "invalid_argument")
    assert err["detail"]["rule"] == "not_a_project"
    no_host_paths(srv, srv.responses[-2].body, lib)


def test_check_has_the_shape_of_pdm_check_json_and_plans_without_copying(srv, lib):
    """The route and ``pdm check --json`` build each project's answer with one function:
    the same keys, counts and findings, the route's paths relative to the root. With
    ``plan`` the route lists the copies, as ``--plan`` does, and makes none."""
    data = ok(srv.get("pdm/check", root="cad", path="Jobs/2001"))["data"]
    assert data["plan"] is None
    cli = pdm.open_vault(lib).check(lib / "Jobs" / "2001", plan=True)["projects"][0]
    assert set(data) == set(cli) - {"fix"} | {"library", "copy_toolbox"}
    assert data["counts"] == cli["counts"] and data["problems"] == cli["problems"]
    assert data["unreadable"] == cli["unreadable"] == []
    problems = [f for f in data["findings"] if f["problem"]]
    assert [set(f) for f in problems] == [set(f) for f in cli["findings"]]
    assert [(f["file_name"], f["result"], f["rule"]) for f in problems] == [
        (f["file_name"], f["result"], f["rule"]) for f in cli["findings"]
    ]
    planned = srv.get("pdm/check", root="cad", path="Jobs/2001", plan="true")
    plan = ok(planned)["data"]["plan"]
    assert plan["copies"] == [
        {
            "source": {"root": "cad", "path": "Jobs/2002/b.SLDPRT"},
            "destination": {"root": "cad", "path": "Jobs/2001/b.SLDPRT"},
            "referenced_by": ["Jobs/2001/asm.SLDASM"],
            "place": "other_project",
            "item": None,
            "round": 1,
        }
    ]
    assert [c["source"] for c in cli["plan"]["copies"]] == [str(lib / "Jobs" / "2002" / "b.SLDPRT")]
    assert plan["conflicts"] == plan["present"] == plan["unplaced"] == [] and plan["rounds"] == 1
    assert not (lib / "Jobs" / "2001" / "b.SLDPRT").exists()
    no_host_paths(srv, planned.body, lib)


def test_refusals(srv, lib):
    assert (
        error(srv.get("pdm/status", root="plain"), 404, "not_a_library")["detail"]["rule"] == "not_a_library"
    )
    error(srv.get("pdm/log", root="plain", path="loose.sldprt"), 404, "not_a_library")
    error(srv.get("pdm/status", root="nope"), 404, "root_not_found")
    assert error(srv.get("pdm/status", root="cad", path="../x"), 403, "path_refused")["detail"]["rule"]
    assert error(srv.get("pdm/log", root="cad"), 400, "invalid_argument")["detail"]["parameter"] == "path"
    err = error(srv.get("pdm/log", root="cad", path="Jobs/1043/notes.txt"), 400, "invalid_argument")
    assert err["detail"]["rule"] == "not_tracked"
    error(srv.get("pdm/status", root="cad", token=None), 401, "unauthorized")
    error(srv.get("pdm/status", root="cad", note="x"), 400, "unknown_parameter")
    err = error(srv.get("pdm/check", root="deep"), 403, "path_refused")  # the root lies inside the project
    assert err["detail"]["rule"] == "project_outside_root"
    assert srv.request("/v1/pdm/status?root=cad", method="POST").status == 405


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no links here")
def test_a_link_is_never_followed(srv, lib, tmp_path):
    link = lib / "Jobs" / "1042" / "linked.sldprt"
    try:
        os.symlink(tmp_path / "elsewhere.sldprt", link)
    except OSError:
        pytest.skip("no right to make links")
    try:
        assert srv.get("pdm/log", root="cad", path="Jobs/1042/linked.sldprt").status in (403, 404)
    finally:
        link.unlink()


def test_answers_carry_an_etag_and_answer_304(srv):
    first = srv.get("pdm/log", root="cad", path="Jobs/1042/bracket.sldprt")
    tag = first.headers["etag"]
    again = srv.request("/v1/pdm/log?root=cad&path=Jobs/1042/bracket.sldprt", headers={"If-None-Match": tag})
    assert again.status == 304 and again.body == b""


def test_the_routes_are_off_without_pdm(lib):
    running = Running({"cad": lib}, workers=1)
    try:
        for route, params in (
            ("pdm/status", {}),
            ("pdm/log", {"path": "Jobs/1042/bracket.sldprt"}),
            ("pdm/version", {"path": "Jobs/1042/bracket.sldprt", "version": "v1"}),
            ("pdm/checkins", {}),
            ("pdm/check", {"path": "Jobs/2001"}),
        ):
            error(running.get(route, root="cad", **params), 403, "feature_disabled")
        assert not running.server.dispatched  # nothing was read
    finally:
        running.close()


def test_nothing_is_written(lib, srv):
    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            str(p): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in lib.parent.rglob("*")
            if p.is_file() and not p.is_symlink()
        }

    before = snapshot()
    ok(srv.get("pdm/status", root="cad"))
    ok(srv.get("pdm/check", root="cad", path="Jobs/2001"))
    ok(srv.get("pdm/checkins", root="cad"))
    assert snapshot() == before


# --------------------------------------------------------------------------- the MCP tools
@pytest.fixture(scope="module")
def connector(lib):
    roots = Roots([Root("cad", str(lib))])
    server = Server(ServeConfig(roots=roots, tokens={}, workers=1, pdm=True), listen=False)
    server.start()
    assert server.wait_ready(120)
    yield mcp.FileConnector(server)
    server.shutdown(close_pool=True)


def test_the_tools_are_offered_only_with_pdm(connector, lib):
    names = {d["name"] for d in connector.definitions()}
    assert PDM_TOOLS <= names
    assert "file_history" in connector.instructions()
    plain = Server(ServeConfig(roots=Roots([Root("cad", str(lib))]), tokens={}, workers=1), listen=False)
    try:
        assert not PDM_TOOLS & {d["name"] for d in mcp.FileConnector(plain).definitions()}
    finally:
        plain.shutdown(close_pool=True)


@pytest.mark.parametrize(
    ("tool", "route", "args"),
    [
        ("pdm_status", "pdm/status", {"path": "Jobs/1042"}),
        ("file_history", "pdm/log", {"path": "Jobs/1042/bracket.sldprt"}),
        ("file_version", "pdm/version", {"path": "Jobs/1042/model.x_b", "version": "latest"}),
        ("recent_checkins", "pdm/checkins", {"limit": 2}),
        ("check_project", "pdm/check", {"path": "Jobs/2001"}),
    ],
)
def test_each_tool_answers_what_its_route_answers(connector, srv, tool, route, args):
    result = connector.call(tool, {"root": "cad", **args})
    assert result["isError"] is False, result["content"][0]["text"]
    env = result["structuredContent"]
    rest = ok(srv.get(route, root="cad", **{k: str(v) for k, v in args.items()}))
    assert env["kind"] == rest["kind"] and env["source"] == rest["source"]
    if tool == "recent_checkins":  # the cursor names its query's own hash
        env["data"].pop("next_cursor"), rest["data"].pop("next_cursor")
    assert env["data"] == rest["data"]


def test_a_tool_refuses_a_folder_in_no_library(lib):
    roots = Roots([Root("plain", str(lib.parent / "plain"))])
    server = Server(ServeConfig(roots=roots, tokens={}, workers=1, pdm=True), listen=False)
    server.start()
    try:
        assert server.wait_ready(120)
        result = mcp.FileConnector(server).call("pdm_status", {"root": "plain"})
        assert result["isError"] is True and result["structuredContent"]["error"]["code"] == "not_a_library"
    finally:
        server.shutdown(close_pool=True)
