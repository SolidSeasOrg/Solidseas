"""The catalog on the command line and over REST (``docs/API.md`` 3.18, 7.1 and 8.6):
every command's ``--json`` output validates against its kind's schema, and Python,
the CLI and the service give the same data.

The commands run in this process (``cli.main``), so their workers start with spawn
as the installed command's do; the catalogs go to the session's temporary cache
folder, and the documents are copies in ``tmp_path``.
"""

import json
import os
import sys
import time

import pytest

from jsonschema_subset import validate
from serve_support import Running, copy_documents, wait_for
from solidseas import Root, Roots, catalog, cli, model

pytestmark = pytest.mark.usefixtures("outbound_guard")


def run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == "", err
    return code, json.loads(out)


def check(env: dict, kind: str) -> dict:
    assert env["kind"] == kind and env["ok"] is (kind != "error"), env
    assert validate(env, model.envelope_schema(kind), strict=True) == []
    return env["data"] if kind != "error" else env["error"]


@pytest.fixture(scope="module")
def indexed(tmp_path_factory):
    root = tmp_path_factory.mktemp("cli") / "proj"
    copy_documents(root)
    return root


def test_the_commands(capsys, indexed, tmp_path, monkeypatch):
    code, env = run(capsys, "index", str(indexed))
    data = check(env, "catalog_scan")
    assert code == 0 and data["counts"]["read_ok"] == 19 and env["source"] is None
    code, env = run(capsys, "where-used", str(indexed / "o02_boxA.SLDPRT"))
    used = check(env, "where_used")
    assert code == 0 and used["counts"]["users"] == 5
    with catalog.open(indexed, mode="r") as cat:
        assert used == cat.where_used("project", "o02_boxA.SLDPRT")
    code, env = run(capsys, "where-used", str(indexed / "o02_boxA.SLDPRT"), "--direct")
    assert {u["depth"] for u in check(env, "where_used")["users"]} == {1}
    monkeypatch.chdir(indexed)
    code, env = run(capsys, "search", "boxA", "type:part", "--limit", "3")
    found = check(env, "catalog_search")
    assert code == 0 and len(found["results"]) == 3 and found["next_cursor"]
    code, env = run(capsys, "search", "type:part", "--limit", "3", "--cursor", found["next_cursor"])
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "cursor"}  # another query's cursor
    for text in ("desc:Oracle test box", "Oracle test box"):  # one argument with spaces: one value or phrase
        code, env = run(capsys, "search", text, "--sort", "name")
        assert [r["path"] for r in check(env, "catalog_search")["results"]] == [
            "o04_boxA_props.SLDPRT",
            "o05_boxA_props_mat.SLDPRT",
            "o06_boxA_props_mat_cfg.SLDPRT",
        ], text
    code, env = run(capsys, "duplicates", "--names")
    assert code == 0 and check(env, "duplicates")["counts"]["groups"] == 0
    code, env = run(capsys, "missing")
    assert code == 0 and check(env, "missing_references")["counts"]["documents"] == 0
    code, env = run(capsys, "changes", "--since", "1d")
    assert code == 0 and len(check(env, "catalog_changes")["events"]) == 19
    code, env = run(capsys, "catalog")
    status = check(env, "catalog")
    assert code == 0 and status["roots"][0]["path"] == str(indexed) and status["state"] == "ready"
    code, env = run(capsys, "catalogs")
    assert code == 0 and status["name"] in [c["name"] for c in check(env, "catalog_list")["catalogs"]]
    code, env = run(capsys, "index", str(indexed))
    assert code == 0 and check(env, "catalog_scan")["counts"]["unchanged"] == 19
    code, env = run(capsys, "clear-index", str(indexed))
    cleared = check(env, "catalog_cleared")
    assert code == 0 and cleared["catalogs"] == [status["name"]] and cleared["files"]
    code, env = run(capsys, "where-used", str(indexed / "o02_boxA.SLDPRT"))
    assert code == 1 and check(env, "error")["code"] == "not_in_catalog"


def test_errors_and_partial_runs(capsys, tmp_path):
    code, env = run(capsys, "index")
    assert code == 2 and check(env, "error")["code"] == "invalid_argument"
    code, env = run(capsys, "index", str(tmp_path / "nope"))
    assert code == 1 and check(env, "error")["code"] == "not_found"
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "garbage.SLDPRT").write_bytes(b"not a document at all" * 10)
    code, env = run(capsys, "index", str(folder), "--db", str(tmp_path / "broken.sqlite"))
    data = check(env, "catalog_scan")
    assert code == 4 and data["errors"][0]["error"]["code"] == "unknown_format"
    code, env = run(capsys, "search", "anything", "--db", str(tmp_path / "broken.sqlite"))
    assert code == 0 and check(env, "catalog_search")["results"] == []
    code, env = run(capsys, "changes", "--since", "bogus", "--db", str(tmp_path / "broken.sqlite"))
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "since"}
    code, env = run(capsys, "clear-index", "--db", str(tmp_path / "broken.sqlite"))
    assert code == 0 and check(env, "catalog_cleared")["catalogs"] == ["broken"]  # its name, not a path
    other = tmp_path / "other.sqlite"
    other.write_bytes(b"SQLite format 3\x00" + bytes(84) + b"x" * 100)
    code, env = run(capsys, "catalog", "--db", str(other))
    assert code == 3 and check(env, "error")["code"] == "catalog_incompatible"


@pytest.mark.skipif(os.name == "nt", reason="Windows tells a share by its drive letter or UNC path")
def test_in_project_needs_a_way_to_tell_a_share(capsys, tmp_path, monkeypatch):
    """Where the mount table cannot be read (macOS, or Linux without /proc), a share
    cannot be told from a local disk, so --in-project is refused and --db asked for; on
    Linux a network file system's mount is refused by the library itself."""
    from solidseas import netfs

    folder = tmp_path / "proj"
    copy_documents(folder)
    monkeypatch.setattr(netfs, "readable", lambda: False)
    code, env = run(capsys, "index", str(folder), "--in-project")
    assert code == 2 and check(env, "error")["detail"]["parameter"] == "in_project"
    monkeypatch.setattr(netfs, "readable", lambda: True)
    monkeypatch.setattr(netfs, "mount_table", lambda: [("/", "ext4"), (str(tmp_path), "nfs4")])
    monkeypatch.setattr(netfs.sys, "platform", "linux")
    code, env = run(capsys, "index", str(folder), "--in-project")
    error = check(env, "error")
    assert code != 0 and error["code"] == "path_refused" and error["detail"]["rule"] == "network_location"
    assert not (folder / ".solidseas").exists()


def test_index_formats_tells_the_catalog_what_to_index(capsys, tmp_path):
    from solidseas_app.viewer import samples

    folder = tmp_path / "mixed"
    copy_documents(folder)
    samples.write_samples(str(folder / "samples"))
    n = len(samples.EXPECTED)
    db = str(tmp_path / "mixed.sqlite")
    code, env = run(capsys, "index", str(folder), "--db", db)
    assert code == 0 and check(env, "catalog_scan")["counts"]["seen"] == 19  # SOLIDWORKS by default
    code, env = run(capsys, "index", str(folder), "--db", db, "--formats", "all")
    assert code == 0 and check(env, "catalog_scan")["counts"]["added"] == n
    code, env = run(capsys, "index", str(folder), "--db", db)  # the setting is kept
    assert code == 0 and check(env, "catalog_scan")["counts"]["unchanged"] == 19 + n
    code, env = run(capsys, "where-used", str(folder / "samples" / "box.stl"), "--db", db)
    used = check(env, "where_used")
    assert code == 0 and used["target"]["format"] == "stl" and used["users"] == []
    code, env = run(capsys, "search", "format:parasolid", "--sort", "name", "--db", db)
    found = [(r["path"], r["format"]) for r in check(env, "catalog_search")["results"]]
    assert found == [("samples/bracket.x_b", "parasolid"), ("samples/bracket.x_t", "parasolid")]
    code, env = run(capsys, "catalog", "--db", db)
    status = check(env, "catalog")
    assert "stl" in status["formats"] and status["counts"]["formats"]["stl"] == 1
    assert cli.main(["catalog", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "  indexes 3mf, acis, alibre, " in out and "; read 1 3mf, 1 acis, 2 alibre, " in out
    assert "19 solidworks, 2 step, 1 stl" in out
    code, env = run(capsys, "index", str(folder), "--db", db, "--formats", "iges")
    assert code == 2 and check(env, "error")["detail"] == {"parameter": "formats"}


@pytest.mark.skipif(
    os.name != "nt" and not sys.platform.startswith("linux"),
    reason="--in-project is refused where a share cannot be told",
)
def test_an_in_project_catalog_is_known_by_one_name(capsys, tmp_path):
    folder = tmp_path / "Proj X"
    copy_documents(folder)
    code, env = run(capsys, "index", str(folder), "--in-project")
    name = check(env, "catalog_scan")["catalog"]
    assert code == 0 and (folder / ".solidseas" / "catalog.sqlite").is_file()
    code, env = run(capsys, "catalog", str(folder), "--in-project")
    assert code == 0 and check(env, "catalog")["name"] == name
    (folder / "sub").mkdir()
    code, env = run(capsys, "clear-index", str(folder / "sub"), "--in-project")  # found from below
    cleared = check(env, "catalog_cleared")
    assert code == 0 and cleared["catalogs"] == [name] and cleared["files"]
    assert not (folder / ".solidseas").exists()


def test_a_where_used_answer_over_its_cap_keeps_the_nearest_users():
    from solidseas.serve.server import _fit_users

    def user(i: int) -> dict:
        return {
            "root": "fx",
            "path": f"a{i:04d}.SLDASM",
            "name": f"a{i:04d}.SLDASM",
            "doc_type": "assembly",
            "format": "solidworks",
            "depth": 1 + i // 100,
            "relation": "component",
            "via": [],
            "uses": [
                {
                    "user_configuration": "Default",
                    "configuration": "Default",
                    "via_configurations": [],
                    "instances": 1,
                    "unsuppressed": 1,
                    "in_bom": 1,
                }
            ],
            "views": [],
            "resolution": None,
            "warnings": [],
        }

    users = [user(i) for i in range(300)]
    data = {
        "target": {
            "root": "fx",
            "path": "p.SLDPRT",
            "name": "p.SLDPRT",
            "doc_type": "part",
            "format": "solidworks",
            "state": "ok",
            "configurations": ["Default"],
            "sha256": None,
        },
        "configuration": None,
        "indirect": True,
        "as_of": None,
        "complete": True,
        "users": list(users),
        "possible": [],
        "name_matches": [],
        "counts": {
            "users": 300,
            "direct": 100,
            "indirect": 200,
            "drawings": 0,
            "possible": 0,
            "name_matches": 0,
        },
        "truncated": False,
        "warnings": [],
    }
    source = {"root": "fx", "path": "p.SLDPRT"}
    _fit_users(data, source, 1 << 20)
    assert len(data["users"]) == 300 and not data["truncated"]  # it fits: untouched
    _fit_users(data, source, 20_000)
    body = model.dumps(model.envelope("where_used", data, source=source))
    assert len(body) <= 20_000 and data["truncated"] and 0 < len(data["users"]) < 300
    assert data["users"] == users[: len(data["users"])] and data["counts"]["users"] == 300
    assert validate(json.loads(body), model.envelope_schema("where_used"), strict=True) == []


def test_the_service_answers_from_its_catalog(capsys, tmp_path):
    root = tmp_path / "served"
    copy_documents(root)
    running = Running({"fx": root}, catalog=True)
    try:
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        r = running.get("catalog")
        status = check(json.loads(r.body), "catalog")
        assert r.status == 200 and status["roots"][0]["path"] is None and status["counts"]["documents"] == 19
        assert status["name"].startswith("folder-") and status["location"] == "cache"
        r = running.get("where-used", root="fx", path="o02_boxA.SLDPRT")
        rest = json.loads(r.body)
        used = check(rest, "where_used")
        assert r.status == 200 and rest["source"] == {"root": "fx", "path": "o02_boxA.SLDPRT"}
        etag = r.headers["etag"]
        assert (
            running.request(
                "/v1/where-used?root=fx&path=o02_boxA.SLDPRT", headers={"If-None-Match": etag}
            ).status
            == 304
        )
        r = running.get("search", q="boxA type:part", limit=5)
        found = check(json.loads(r.body), "catalog_search")
        assert r.status == 200 and len(found["results"]) == 5
        # the same data as Python's on the same catalog
        with catalog.open(Roots([Root("fx", str(root))]), mode="r") as cat:
            assert used == cat.where_used("fx", "o02_boxA.SLDPRT")
            assert found == cat.search("boxA type:part", limit=5)
        for params, status_code, code in (
            ({"root": "nope", "path": "o02_boxA.SLDPRT"}, 404, "root_not_found"),
            ({"root": "fx", "path": "../o02_boxA.SLDPRT"}, 403, "path_refused"),
            ({"root": "fx", "path": "gone.SLDPRT"}, 404, "not_in_catalog"),
            (
                {"root": "fx", "path": "o02_boxA.SLDPRT", "configuration": "Zq7"},
                404,
                "configuration_not_found",
            ),
            ({"root": "fx", "path": "o02_boxA.SLDPRT", "extra": "1"}, 400, "unknown_parameter"),
        ):
            r = running.get("where-used", **params)
            assert (r.status, json.loads(r.body)["error"]["code"]) == (status_code, code), params
        assert running.get("search", q="x", limit=501).status == 400
        assert running.get("catalog", token=None).status == 401
        assert any("catalog=scanned" in line for line in running.log.lines)
        assert not any(str(root) in line for line in running.log.lines)
        assert running.server.catalog_scans.maxlen  # a long-running service keeps only the last few
        # an answer over the route's cap keeps the nearest users that fit
        full = running.get("where-used", root="fx", path="o02_boxA.SLDPRT")
        running.server.config.response_caps["catalog"] = len(full.body) - 300
        cut = json.loads(running.get("where-used", root="fx", path="o02_boxA.SLDPRT").body)["data"]
        assert cut["truncated"] and len(cut["users"]) < len(used["users"]) and cut["counts"] == used["counts"]
    finally:
        running.close()


def test_the_service_catalog_indexes_the_formats_the_service_reads(tmp_path):
    from solidseas_app.viewer import samples

    root = tmp_path / "mixed"
    copy_documents(root)
    samples.write_samples(str(root / "samples"))
    running = Running({"fx": root}, catalog=True)  # SOLIDWORKS documents only, by default
    try:
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        status = check(json.loads(running.get("catalog").body), "catalog")
        assert status["formats"] == ["solidworks"] and status["counts"]["documents"] == 19
        r = running.get("where-used", root="fx", path="samples/box.stl")
        assert r.status == 403 and json.loads(r.body)["error"]["detail"]["rule"] == "not_a_document"
    finally:
        running.close()
    running = Running({"fx": root}, catalog=True, formats="all")
    try:
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        status = check(json.loads(running.get("catalog").body), "catalog")
        assert status["counts"]["documents"] == 19 + len(samples.EXPECTED)
        r = running.get("where-used", root="fx", path="samples/box.stl")
        used = check(json.loads(r.body), "where_used")
        assert r.status == 200 and used["target"]["format"] == "stl"
        r = running.get("where-used", root="fx", path="samples/sheet.igs")  # read by nothing, not indexed
        assert r.status == 403 and json.loads(r.body)["error"]["code"] == "path_refused"
    finally:
        running.close()


def test_the_catalog_routes_are_off_without_the_option_and_busy_until_ready(tmp_path, monkeypatch):
    root = tmp_path / "off"
    copy_documents(root)
    running = Running({"fx": root})
    try:
        r = running.get("catalog")
        assert r.status == 403 and json.loads(r.body)["error"]["code"] == "feature_disabled"
    finally:
        running.close()
    from solidseas.catalog import scan as scan_mod

    real = scan_mod.Scanner.run
    gate = []

    def slow(self):
        while not gate:
            time.sleep(0.02)
        return real(self)

    monkeypatch.setattr(scan_mod.Scanner, "run", slow)
    running = Running({"fx": root}, catalog=True)
    try:
        r = running.get("where-used", root="fx", path="o02_boxA.SLDPRT")
        body = json.loads(r.body)
        assert r.status == 503 and body["error"]["code"] == "busy" and r.headers["retry-after"] == "2"
        assert body["error"]["message"] == model.RULE_MESSAGES[("busy", "catalog_scanning")]
        gate.append(1)
        assert wait_for(lambda: running.server._catalog_path is not None, 120)
        assert running.get("where-used", root="fx", path="o02_boxA.SLDPRT").status == 200
    finally:
        gate.append(1)
        running.close()
