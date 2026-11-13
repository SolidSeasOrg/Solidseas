"""What the REST service answers (``docs/API.md`` section 8): the routes and the kinds
they share with the registry, schemas, ETags and 304, paged listings, roots whose
index is building or unavailable, files added after the start, cloud placeholders,
resolution, and the CLI command that runs it."""

import http.client
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from fakefs import ARCHIVE, FakeEntry, fake_tree
from jsonschema_subset import validate
from serve_support import TOKEN, Running, wait_for
from solidseas import AddressUnavailableError, Root, Roots, cli, model, open_document, pdm
from solidseas.resolve import resolve_references
from solidseas.serve import ROUTES, ServeConfig, Server
from solidseas.serve import server as server_mod
from support import NATIVE, PARTS, fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
WINDOWS = sys.platform == "win32"
O02 = fixture_path("o02_boxA.SLDPRT")
O08 = fixture_path("o08_asm_2x_boxA.SLDASM")
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("serve") / "jobs"
    base.mkdir()
    for name in NATIVE:
        shutil.copy2(fixture_path(name), base / name)
    (base / "sub").mkdir()
    shutil.copy2(fixture_path(PARTS[3]), base / "sub" / PARTS[3])
    return base


@pytest.fixture(scope="module")
def srv(root):
    running = Running({"jobs": root})
    yield running
    running.close()


# --------------------------------------------------------------------------- routes and kinds
def test_the_routes_are_the_registrys():
    # model_summary answers /v1/document for a model file in document_summary's place
    # (tests/test_formats_surfaces.py); each route's own kind is the primary one.
    from_registry = {
        spec.rest_route: name
        for name, spec in model.KINDS.items()
        if spec.rest_route and spec.alternate_of is None
    }
    served = {path: r.kind for path, r in ROUTES.items() if r.kind is not None}
    assert served == from_registry and len(served) >= 10
    assert ROUTES["/v1/preview"].kind is None  # the one route that answers with an image
    assert all(p.startswith("/v1/") for p in ROUTES)


def test_every_json_answer_matches_its_schema(srv, tmp_path):
    calls = [
        ("health", {}),
        ("identity", {"client": "tests", "nonce": "n" * 43}),
        ("version", {}),
        ("roots", {}),
        ("list", {"root": "jobs", "include": "properties,configurations,preview", "recursive": "1"}),
        ("document", {"root": "jobs", "path": "o04_boxA_props.SLDPRT"}),
        ("properties", {"root": "jobs", "path": "o06_boxA_props_mat_cfg.SLDPRT", "view": "configuration"}),
        ("configurations", {"root": "jobs", "path": "o06_boxA_props_mat_cfg.SLDPRT"}),
        ("components", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM", "flat": "1"}),
        ("references", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM", "resolve": "1"}),
        ("bom", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM", "type": "indented", "columns": "A,B"}),
        ("path-report", {"root": "jobs", "path": "o08_asm_2x_boxA.SLDASM"}),
        ("document", {"root": "jobs", "path": "missing.SLDPRT"}),
    ]
    kinds = []
    for route, params in calls:
        r = srv.get(route, **params)
        env = r.json()
        kinds.append(env["kind"])
        assert validate(env, model.envelope_schema(env["kind"]), strict=True) == [], (route, env["kind"])
        assert r.headers["content-type"] == "application/json; charset=utf-8"
    # the catalog's routes, from a service that keeps one (tests/test_catalog_surfaces.py has the rest)
    cataloged = Running({"jobs": srv.server.config.roots["jobs"].path}, catalog=True)
    try:
        assert wait_for(lambda: cataloged.server._catalog_path is not None, 120)
        for route, params in (
            ("catalog", {}),
            ("where-used", {"root": "jobs", "path": "o02_boxA.SLDPRT"}),
            ("search", {"q": "boxA"}),
            ("duplicates", {"names": "1"}),
            ("missing", {}),
            ("changes", {"since": "1d"}),
        ):
            env = cataloged.get(route, **params).json()
            kinds.append(env["kind"])
            assert validate(env, model.envelope_schema(env["kind"]), strict=True) == [], (route, env["kind"])
    finally:
        cataloged.close()
    # the PDM's routes, over a library around a copy of the root (tests/test_serve_pdm.py has the rest)
    library = tmp_path / "library"
    project = library / "Jobs" / "1042"
    shutil.copytree(srv.server.config.roots["jobs"].path, project)
    pdm.init(library).checkin([project], "first")
    with_pdm = Running({"jobs": library}, pdm=True)
    try:
        for route, params in (
            ("pdm/status", {"root": "jobs"}),
            ("pdm/log", {"root": "jobs", "path": "Jobs/1042/o02_boxA.SLDPRT"}),
            ("pdm/version", {"root": "jobs", "path": "Jobs/1042/o02_boxA.SLDPRT", "version": "latest"}),
            ("pdm/checkins", {"root": "jobs"}),
            ("pdm/check", {"root": "jobs", "path": "Jobs/1042"}),
            ("pdm/status", {"root": "jobs", "path": "Jobs/none"}),
        ):
            env = with_pdm.get(route, **params).json()
            kinds.append(env["kind"])
            assert validate(env, model.envelope_schema(env["kind"]), strict=True) == [], (route, env["kind"])
    finally:
        with_pdm.close()
    served = {name for name, spec in model.KINDS.items() if spec.rest_route and spec.alternate_of is None}
    assert set(kinds) == served | {"error"} and len(served) >= 10


def test_health_version_and_roots(srv):
    assert srv.get("health", token=None).json()["data"] == {"status": "ok"}
    assert srv.get("version").json()["data"] == model.build_version()
    (state,) = srv.get("roots").json()["data"]["roots"]
    assert state == {
        "id": "jobs",
        "role": "project",
        "recursive": True,
        "state": "ready",
        "index_partial": False,
        "documents": len(NATIVE) + 1,
    }
    assert str(srv.server.config.roots["jobs"].path) not in srv.get("roots").body.decode()  # never a path


# --------------------------------------------------------------------------- ETags
def test_a_document_answers_304_until_it_changes(srv, root):
    path = root / "o02_boxA.SLDPRT"
    first = srv.get("document", root="jobs", path=path.name)
    etag = first.headers["etag"]
    again = srv.request(f"/v1/document?root=jobs&path={path.name}", headers={"If-None-Match": etag})
    assert again.status == 304 and again.body == b"" and again.headers["etag"] == etag
    assert (
        srv.request(
            f"/v1/document?root=jobs&path={path.name}", headers={"If-None-Match": f'W/{etag}, "other"'}
        ).status
        == 304
    )
    other_query = srv.request(
        f"/v1/document?root=jobs&path={path.name}&nested=x", headers={"If-None-Match": etag}
    )
    assert other_query.status != 304  # the query is part of the tag
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    try:
        changed = srv.request(f"/v1/document?root=jobs&path={path.name}", headers={"If-None-Match": etag})
        assert changed.status == 200 and changed.headers["etag"] != etag
    finally:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_a_listing_answers_304_until_its_folder_changes(srv, root):
    first = srv.get("list", root="jobs")
    etag = first.headers["etag"]
    assert srv.request("/v1/list?root=jobs", headers={"If-None-Match": etag}).status == 304
    shutil.copy2(O02, root / "added_later.SLDPRT")
    try:
        changed = srv.request("/v1/list?root=jobs", headers={"If-None-Match": etag})
        assert changed.status == 200
        assert "added_later.SLDPRT" in {e["path"] for e in changed.json()["data"]["entries"]}
    finally:
        (root / "added_later.SLDPRT").unlink()


def test_a_listing_page_with_a_transient_failure_has_no_etag(tmp_path):
    """The listing's tag covers its directory entries, not how reading each file went, so a
    page holding an entry that may read differently later must not be revalidated into a 304."""
    from solidseas.workers import WorkerPool

    (tmp_path / "flaky").mkdir()
    (tmp_path / "clean").mkdir()
    shutil.copy2(O02, tmp_path / "flaky" / "crash.SLDPRT")  # its worker dies, as a crash would
    shutil.copy2(O02, tmp_path / "flaky" / "fine.SLDPRT")
    shutil.copy2(O02, tmp_path / "clean" / "fine.SLDPRT")
    pool = WorkerPool(1, reader_message=False, jobs={"listing_entry": "worker_jobs:listing_entry"})
    running = Running({"a": tmp_path}, pool=pool)
    try:
        r = running.get("list", root="a", path="flaky")
        entries = {e["path"]: e for e in r.json()["data"]["entries"]}
        assert entries["flaky/crash.SLDPRT"]["error"]["code"] == "worker_crashed"
        assert r.status == 200 and "etag" not in r.headers
        r = running.get("list", root="a", path="clean")
        assert r.status == 200 and r.headers["etag"]  # control: a clean page has its tag
    finally:
        running.close()


@pytest.mark.skipif(not WINDOWS, reason="byte-range locks through msvcrt")
def test_a_page_listed_while_a_file_was_locked_is_read_again(srv, root):
    import msvcrt

    (root / "lockdir").mkdir()
    held = root / "lockdir" / "held.SLDPRT"
    shutil.copy2(O02, held)
    shutil.copy2(O02, root / "lockdir" / "free.SLDPRT")
    try:
        size = held.stat().st_size
        with open(held, "rb") as holder:
            msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, size)
            try:
                locked = srv.get("list", root="jobs", path="lockdir")
            finally:
                holder.seek(0)
                msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, size)
        error = {e["path"]: e for e in locked.json()["data"]["entries"]}["lockdir/held.SLDPRT"]["error"]
        assert (error["code"], error["retryable"]) == ("locked", True)
        assert "etag" not in locked.headers  # nothing a client could send back for a 304
        after = srv.get("list", root="jobs", path="lockdir")
        assert after.json()["data"]["counts"]["ok"] == 2 and after.headers["etag"]
        tag = after.headers["etag"]
        again = srv.request("/v1/list?root=jobs&path=lockdir", headers={"If-None-Match": tag})
        assert again.status == 304  # control: a page read whole revalidates
    finally:
        shutil.rmtree(root / "lockdir")


def test_a_resolved_answer_has_its_own_etag(srv):
    plain = srv.get("references", root="jobs", path="o08_asm_2x_boxA.SLDASM")
    resolved = srv.get("references", root="jobs", path="o08_asm_2x_boxA.SLDASM", resolve="1")
    assert plain.headers["etag"] != resolved.headers["etag"]
    assert plain.json()["data"]["resolution"] is None and resolved.json()["data"]["resolution"]


# --------------------------------------------------------------------------- listings
def test_a_listing_pages_with_a_cursor(srv):
    full = srv.get("list", root="jobs", recursive="1").json()["data"]
    assert full["next_cursor"] is None and len(full["entries"]) == len(NATIVE) + 1
    seen, cursor, pages = [], None, 0
    while True:
        params = {"root": "jobs", "recursive": "1", "limit": "3"}
        if cursor:
            params["cursor"] = cursor
        page = srv.get("list", **params).json()["data"]
        seen += page["entries"]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            assert not page["truncated"]
            break
        assert page["truncated_reason"] == "max_entries" and len(page["entries"]) == 3
    assert pages == -(-len(full["entries"]) // 3) >= 3 and seen == full["entries"]
    first = srv.get("list", root="jobs", recursive="1", limit="3").json()["data"]
    r = srv.get("list", root="jobs", limit="3", cursor=first["next_cursor"])  # another query
    assert r.status == 400 and r.json()["error"]["detail"] == {"parameter": "cursor"}
    import base64

    raw = base64.urlsafe_b64decode(first["next_cursor"] + "=" * (-len(first["next_cursor"]) % 4))
    qhash, _, after = raw.decode().partition("\n")
    forged = base64.urlsafe_b64encode(f"{'0' * len(qhash)}\n{after}".encode()).rstrip(b"=").decode()
    assert srv.get("list", root="jobs", recursive="1", limit="3", cursor=forged).status == 400
    assert srv.get("list", root="jobs", recursive="1", limit="3", cursor="!!").status == 400
    # the resume point is only compared with the walk's own names, never joined into a path
    elsewhere = base64.urlsafe_b64encode(f"{qhash}\n../../outside".encode()).rstrip(b"=").decode()
    page = srv.get("list", root="jobs", recursive="1", limit="3", cursor=elsewhere)
    assert page.status == 200 and all(e in full["entries"] for e in page.json()["data"]["entries"])


def test_a_subfolder_lists_with_root_relative_paths(srv):
    data = srv.get("list", root="jobs", path="sub", include="properties").json()["data"]
    assert (data["root"], data["folder"]) == ("jobs", "sub")
    assert [e["path"] for e in data["entries"]] == [f"sub/{PARTS[3]}"]
    assert data["entries"][0]["properties"]
    r = srv.get("document", root="jobs", path=f"sub/{PARTS[3]}")
    assert r.status == 200 and r.json()["source"] == {"root": "jobs", "path": f"sub/{PARTS[3]}"}
    r = srv.get("list", root="jobs", path="o02_boxA.SLDPRT")  # a file is no folder, and says so
    assert r.status == 400 and r.json()["error"]["code"] == "invalid_argument"
    assert r.json()["error"]["detail"] == {"parameter": "path", "rule": "not_a_folder"}
    assert r.json()["error"]["message"] == "The path names a file, not a folder."
    r = srv.get("list", root="jobs", path="sub/missing")
    assert r.status == 404 and r.json()["error"]["message"] == "The file or folder does not exist."  # control


def test_an_unknown_route_says_it_is_the_route(srv):
    r = srv.request("/v1/nope")
    err = r.json()["error"]
    assert r.status == 404 and (err["code"], err["detail"]) == ("not_found", {"rule": "route"})
    assert err["exception"] == "ServiceError"
    assert err["message"] == "The service has no route at that address."
    assert srv.request("/v1/nope", token=None).status == 401  # still after the token check


@pytest.mark.parametrize(
    ("query", "source"),
    [
        ("root=jobs&path=a.SLDASM&flat=2", {"root": "jobs", "path": "a.SLDASM"}),
        ("root=jobs&path=a.SLDASM&nested=x", {"root": "jobs", "path": "a.SLDASM"}),  # no nested here
        ("root=jobs", {"root": "jobs", "path": None}),
        ("root=jobs&path=a.SLDPRT&bogus=1", {"root": "jobs", "path": "a.SLDPRT"}),
        ("root=Bad%20Id&path=a.SLDPRT", {"root": None, "path": "a.SLDPRT"}),
        ("root=jobs&root=other&path=a.SLDPRT", {"root": None, "path": "a.SLDPRT"}),
        ("flat=1", None),
    ],
    ids=["bad_value", "nested_elsewhere", "no_path", "unknown_name", "bad_root", "root_twice", "neither"],
)
def test_a_parameter_error_names_the_root_and_path_asked_for(srv, query, source):
    r = srv.request(f"/v1/components?{query}")
    assert r.status == 400 and r.json()["source"] == source
    r = srv.request("/v1/document?root=jobs&path=a.SLDPRT&nested=Part1&bogus=1")  # a route with nested
    assert r.json()["source"] == {"root": "jobs", "path": "a.SLDPRT", "nested": "Part1"}


def test_files_added_after_the_start_are_found(srv, root):
    (root / "later").mkdir()
    shutil.copy2(O02, root / "later" / "new.SLDPRT")
    shutil.copy2(O02, root / "new_top.SLDPRT")
    try:
        for path in ("later/new.SLDPRT", "new_top.SLDPRT", "LATER/NEW.sldprt"):
            r = srv.get("document", root="jobs", path=path)
            assert r.status == 200, (path, r.body[:200])
        assert r.json()["source"]["path"] == "later/new.SLDPRT"
        assert srv.get("list", root="jobs", path="later").json()["data"]["counts"]["ok"] == 1
    finally:
        shutil.rmtree(root / "later")
        (root / "new_top.SLDPRT").unlink()
    assert srv.get("document", root="jobs", path="new_top.SLDPRT").status == 404  # gone again


# --------------------------------------------------------------------------- clients
NODE_FETCH = """
const base = `http://127.0.0.1:${process.env.SOLIDSEAS_PORT}/v1`;
const headers = {Authorization: `Bearer ${process.env.SOLIDSEAS_TOKEN}`};
const url = `${base}/components?root=jobs&path=o08_asm_2x_boxA.SLDASM`;
const r = await fetch(url, {headers, signal: AbortSignal.timeout(20000)});
const body = await r.json();
const again = await fetch(url, {
  headers: {...headers, "If-None-Match": r.headers.get("etag")},
  signal: AbortSignal.timeout(20000),
});
console.log(JSON.stringify({status: r.status, kind: body.kind, children: body.data.children.length,
                            revalidated: again.status}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not on PATH")
def test_a_node_fetch_is_served(srv):
    """The store calls the service from Node's own fetch, which sends Sec-Fetch-Mode but
    no Origin or Sec-Fetch-Site: the browser checks must let it through."""
    env = {**os.environ, "SOLIDSEAS_PORT": str(srv.port), "SOLIDSEAS_TOKEN": TOKEN}
    done = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_FETCH],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(done.stdout) == {"status": 200, "kind": "components", "children": 2, "revalidated": 304}


# --------------------------------------------------------------------------- roots that are not ready
def test_a_root_whose_index_is_building_answers_503(tmp_path, monkeypatch):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    release = threading.Event()
    real = server_mod.Gateway

    class SlowGateway(real):
        def build_index(self, *args, **kwargs):
            release.wait(30)
            return super().build_index(*args, **kwargs)

    monkeypatch.setattr(server_mod, "Gateway", SlowGateway)
    from serve_support import LogCapture  # noqa: F401 - Running attaches it
    from solidseas.serve import ServeConfig, Server

    server = Server(
        ServeConfig(roots=Roots([Root("a", str(tmp_path))]), tokens={"t": TOKEN}, port=0, workers=1)
    )
    server.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import http.client

        def get(path):
            c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
            c.request("GET", path, headers={"Authorization": f"Bearer {TOKEN}"})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), json.loads(r.read())

        status, headers, env = get("/v1/document?root=a&path=a.SLDPRT")
        assert status == 503 and env["error"]["code"] == "busy" and headers["Retry-After"] == "2"
        assert get("/v1/roots")[2]["data"]["roots"][0]["state"] == "building"
        release.set()
        assert server.wait_ready(30)
        assert get("/v1/document?root=a&path=a.SLDPRT")[0] == 200
    finally:
        release.set()
        server.shutdown()


def test_a_root_that_is_gone_answers_503_root_unavailable(tmp_path):
    present = tmp_path / "present"
    present.mkdir()
    shutil.copy2(O02, present / "a.SLDPRT")
    shutil.copy2(O08, present / "o08_asm_2x_boxA.SLDASM")
    gone = tmp_path / "gone"
    running = Running({"present": present, "gone": gone}, workers=1)
    try:
        states = {s["id"]: s["state"] for s in running.get("roots").json()["data"]["roots"]}
        assert states == {"present": "ready", "gone": "unavailable"}
        r = running.get("document", root="gone", path="a.SLDPRT")
        assert r.status == 503 and r.json()["error"]["code"] == "root_unavailable"
        assert r.headers["retry-after"] == "30"
        assert running.get("document", root="present", path="a.SLDPRT").status == 200
        # resolution searches without the missing root, and says so rather than leaving it out
        r = running.get("references", root="present", path="o08_asm_2x_boxA.SLDASM", resolve="1")
        assert r.status == 200
        data = r.json()["data"]
        searched = [(s["id"], s["index_partial"], s["truncated_reason"]) for s in data["resolution"]["roots"]]
        assert searched == [("present", False, None), ("gone", True, "unavailable")]
        assert data["resolution"]["index_partial"] is True
        (f,) = data["files"]
        assert "root_unavailable" in {w["code"] for w in f["resolution"]["warnings"]}
        # each resolution walks the roots again, so a root that came back is searched
        gone.mkdir()
        shutil.copy2(O02, gone / "o02_boxA.SLDPRT")
        data = running.get("references", root="present", path="o08_asm_2x_boxA.SLDASM", resolve="1").json()
        roots = data["data"]["resolution"]["roots"]
        assert [(s["id"], s["truncated_reason"]) for s in roots] == [("present", None), ("gone", None)]
    finally:
        running.close()


def test_a_cloud_placeholder_is_never_opened(tmp_path, monkeypatch):
    tree = {"": [FakeEntry("cloud.SLDPRT", ARCHIVE | 0x400000, size=50_000)]}
    fake_tree(monkeypatch, tmp_path, tree)
    running = Running({"c": tmp_path}, workers=1)
    try:
        r = running.get("document", root="c", path="cloud.SLDPRT")
        assert r.status == 409 and r.json()["error"]["code"] == "placeholder_file"
        tree[""].append(FakeEntry("late.SLDPRT", ARCHIVE | 0x40000, size=10))  # one the index never saw
        r = running.get("document", root="c", path="late.SLDPRT")
        assert r.status == 409 and r.json()["error"]["code"] == "placeholder_file"
        assert list(running.server.dispatched) == []  # no worker was asked to open either
        entries = running.get("list", root="c").json()["data"]["entries"]
        assert {e["path"]: e["status"] for e in entries} == {
            "cloud.SLDPRT": "placeholder",
            "late.SLDPRT": "placeholder",
        }
    finally:
        running.close()


def test_a_root_served_without_subfolders_stays_flat(tmp_path):
    shutil.copy2(O02, tmp_path / "top.SLDPRT")
    (tmp_path / "sub").mkdir()
    shutil.copy2(O02, tmp_path / "sub" / "below.SLDPRT")
    running = Running(Roots([Root("flat", str(tmp_path), recursive=False)]), workers=1)
    try:
        listed = running.get("list", root="flat")
        assert listed.status == 200
        assert {e["path"] for e in listed.json()["data"]["entries"]} == {"top.SLDPRT", "sub"}
        r = running.get("list", root="flat", recursive="1")
        assert r.status == 400 and r.json()["error"]["detail"] == {"parameter": "recursive"}
        assert running.get("list", root="flat", path="sub").status == 404
        assert running.get("document", root="flat", path="sub/below.SLDPRT").status == 404
        assert running.get("document", root="flat", path="top.SLDPRT").status == 200  # control
    finally:
        running.close()


# --------------------------------------------------------------------------- resolution
@pytest.mark.skipif(not WINDOWS, reason="a stored path is a path on this machine only on Windows")
def test_the_service_never_looks_outside_its_roots(tmp_path):
    """A stored path naming a real file outside every root: Python finds it there with outside
    lookups allowed (the control), the service reports it missing (C2)."""
    from builders import TreeXml, part_with_creation_time, resolving_assembly

    ct = 1_700_000_000
    stored = tmp_path / "Orig" / "p.SLDPRT"
    stored.parent.mkdir()
    stored.write_bytes(part_with_creation_time(ct))
    project = tmp_path / "Moved"
    project.mkdir()
    t = TreeXml()
    t.top("m1")
    t.file("2", str(stored), swCreationTime=str(ct))
    t.model("m2", "2")
    t.ref("m1", "c2", 1, "m2")
    (project / "asm.SLDASM").write_bytes(resolving_assembly(t, folder_at_save=str(stored.parent) + "\\"))
    roots = Roots([Root("project", str(project))])
    with open_document(project / "asm.SLDASM") as doc:
        (found,) = resolve_references(doc, roots, allow_outside_roots=True).results.values()
    assert found.status == "resolved" and found.match.root is None  # control: it is there to be found
    running = Running(roots, workers=1)
    try:
        data = running.get("references", root="project", path="asm.SLDASM", resolve="1").json()["data"]
    finally:
        running.close()
    (f,) = data["files"]
    assert f["resolution"]["status"] == "missing" and f["resolution"]["match"] is None
    assert data["resolution"]["outside_roots"] is False


def test_resolution_finds_moved_files_inside_the_roots_only(tmp_path):
    project, library = tmp_path / "project", tmp_path / "library"
    project.mkdir()
    library.mkdir()
    shutil.copy2(O08, project / "o08_asm_2x_boxA.SLDASM")
    shutil.copy2(O02, library / "o02_boxA.SLDPRT")
    roots = Roots([Root("project", str(project)), Root("std", str(library), role="library")])
    running = Running(roots, workers=1)
    try:
        r = running.get("references", root="project", path="o08_asm_2x_boxA.SLDASM", resolve="1")
        data = r.json()["data"]
        (f,) = data["files"]
        assert f["resolution"]["status"] == "moved"
        assert f["resolution"]["match"] == {"root": "std", "path": "o02_boxA.SLDPRT"}
        assert data["resolution"]["outside_roots"] is False
        with open_document(project / "o08_asm_2x_boxA.SLDASM") as doc:
            res = resolve_references(doc, roots, allow_outside_roots=False)
            assert data == model.build_references(doc, resolution=res)
    finally:
        running.close()


def test_resolution_sees_a_project_moved_after_the_start(tmp_path):
    """The service indexes its roots when it starts, but a resolution must see the tree as it
    is now: a project copied to a new folder while the service runs is resolved exactly as
    Python resolves it at that moment, and a client's old ETag no longer answers 304."""
    jobs = tmp_path / "jobs"
    (jobs / "Example").mkdir(parents=True)
    shutil.copy2(O08, jobs / "Example" / O08.name)
    shutil.copy2(O02, jobs / "Example" / O02.name)
    roots = Roots([Root("jobs", str(jobs))])
    running = Running(roots, workers=1)
    asm = jobs / "Moved" / "asm" / O08.name
    url = f"/v1/references?root=jobs&path=Moved/asm/{O08.name}&resolve=1"

    def python_answer():
        with open_document(asm) as doc:
            res = resolve_references(doc, roots, allow_outside_roots=False, skip_unavailable_roots=True)
            return model.build_references(doc, resolution=res)

    try:
        asm.parent.mkdir(parents=True)
        shutil.copy2(O08, asm)  # the assembly first: its part is found where it was
        first = running.request(url)
        data = first.json()["data"]
        assert data == python_answer()
        (f,) = data["files"]
        assert f["resolution"]["match"] == {"root": "jobs", "path": f"Example/{O02.name}"}
        (jobs / "Moved" / "parts").mkdir()
        shutil.copy2(O02, jobs / "Moved" / "parts" / O02.name)  # then a copy of the part
        # the first answer's tag came from that answer, which is no longer the answer
        second = running.request(url, headers={"If-None-Match": first.headers["etag"]})
        assert second.status == 200 and second.headers["etag"] != first.headers["etag"]
        data = second.json()["data"]
        assert data == python_answer()
        (f,) = data["files"]  # two copies with the same identity: nothing may pick one
        assert f["resolution"]["status"] == "ambiguous"
        assert {(c["root"], c["path"]) for c in f["resolution"]["candidates"]} == {
            ("jobs", f"Example/{O02.name}"),
            ("jobs", f"Moved/parts/{O02.name}"),
        }
        same = running.request(url, headers={"If-None-Match": second.headers["etag"]})
        assert same.status == 304 and same.body == b""  # control: an unchanged answer revalidates
    finally:
        running.close()


# --------------------------------------------------------------------------- the CLI command
def test_the_cli_serves_until_it_is_stopped(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    token_file = tmp_path / "state" / "tokens"
    token_file.parent.mkdir()
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    log = tmp_path / "stderr.txt"
    log_fh = open(log, "wb")  # a file, not a pipe: a pipe nobody reads would fill and stop the service
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "solidseas",
            "serve",
            "--root",
            f"jobs={tmp_path}",
            "--port",
            "0",
            "--token-file",
            str(token_file),
            "--workers",
            "1",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=log_fh,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
    )
    try:
        started = json.loads(proc.stdout.readline())
        assert validate(started, model.envelope_schema("serve_started"), strict=True) == []
        data = started["data"]
        assert data["host"] == "127.0.0.1" and data["roots"] == ["jobs"] and data["token_file_created"]
        lines = token_file.read_text().splitlines()
        token = next(line.split(":", 1)[1] for line in lines if line and not line.startswith("#"))
        import http.client

        def get(path):
            c = http.client.HTTPConnection("127.0.0.1", data["port"], timeout=30)
            c.request("GET", path, headers={"Authorization": f"Bearer {token}"})
            r = c.getresponse()
            return r.status, r.read()

        assert wait_for(lambda: get("/v1/document?root=jobs&path=a.SLDPRT")[0] == 200, 30)
        proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        proc.wait(15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log_fh.close()
    err = log.read_text(encoding="utf-8", errors="replace")
    assert proc.returncode == 0 and "route=/v1/document" in err and "stopped" in err
    assert token not in err and str(tmp_path) not in err


NO_STREAMS = (
    "import sys\n"
    "sys.stdout = sys.stderr = None  # as under pythonw.exe, or a task started without a console\n"
    "from solidseas.cli import main\n"
    "raise SystemExit(main(sys.argv[1:]))\n"
)


def test_the_cli_runs_without_standard_streams(tmp_path):
    """``pythonw.exe -m solidseas serve`` (a Windows task with no console window) starts
    with no standard output or error. Every command keeps its exit code, and the service
    serves: its ready line and its log go nowhere rather than ending the process."""
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    env = {**os.environ, "PYTHONPATH": str(SRC)}

    def run(*argv: str) -> int:
        return subprocess.run([sys.executable, "-c", NO_STREAMS, *argv], env=env, timeout=120).returncode

    assert run("version") == 0
    assert run("info", str(tmp_path / "a.SLDPRT")) == 0
    assert run("info", str(tmp_path / "missing.SLDPRT")) == 1
    assert run("serve", "--root", f"jobs={tmp_path}", "--bind", "0.0.0.0") == 3  # refused before it listens

    token_file = tmp_path / "state" / "tokens"
    token_file.parent.mkdir()
    with socket.socket() as probe:  # a port free a moment ago: there is no ready line to read one from
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    argv = ["serve", "--root", f"jobs={tmp_path}", "--port", str(port), "--token-file", str(token_file)]
    proc = subprocess.Popen(
        [sys.executable, "-c", NO_STREAMS, *argv, "--workers", "1"],
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
    )

    def read_token() -> str | None:
        # The file shows up before the service has finished writing it, and on Windows
        # it cannot be opened until the service closes it, so wait for a token in it.
        try:
            lines = token_file.read_text().splitlines()
        except OSError:
            return None
        return next((x.split(":", 1)[1] for x in lines if x[:1] not in ("", "#")), None)

    try:
        assert wait_for(lambda: read_token() is not None or proc.poll() is not None, 30)
        assert proc.poll() is None, f"the service ended with {proc.returncode}"
        token = read_token()

        def status() -> int | None:
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                auth = {"Authorization": f"Bearer {token}"}
                c.request("GET", "/v1/document?root=jobs&path=a.SLDPRT", headers=auth)
                return c.getresponse().status
            except OSError:
                return None

        assert wait_for(lambda: status() == 200 or proc.poll() is not None, 60)
        assert proc.poll() is None and status() == 200
        proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        assert proc.wait(15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_a_port_in_use_is_address_unavailable(tmp_path, capsys, monkeypatch):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    running = Running({"a": tmp_path}, workers=1)
    try:
        config = ServeConfig(roots=Roots([Root("a", str(tmp_path))]), tokens={"t": TOKEN}, port=running.port)
        with pytest.raises(AddressUnavailableError) as caught:
            Server(config)
        assert caught.value.code == "address_unavailable"

        def never(server):  # a bind that wrongly succeeded must not serve for ever
            server.shutdown()
            raise AssertionError("the second service started")

        monkeypatch.setattr("solidseas.serve.run_until_signalled", never)
        log = logging.getLogger("solidseas.serve")  # leave the service's logger as it was
        monkeypatch.setattr(log, "handlers", list(log.handlers))
        monkeypatch.setattr(log, "propagate", log.propagate)
        token_file = tmp_path / "state" / "tokens"
        token_file.parent.mkdir()
        argv = ["serve", "--root", f"a={tmp_path}", "--port", str(running.port), "--workers", "1"]
        code = cli.main([*argv, "--token-file", str(token_file), "--json"])
        out, err = capsys.readouterr()
        env = json.loads(out)
        assert code == 1 and err == "" and env["error"]["code"] == "address_unavailable"
        assert running.get("version").status == 200  # the first service is unharmed
    finally:
        running.close()


@pytest.mark.parametrize(
    "argv", [["--port", "65536"], ["--port", "-1"], ["--port", "08765"], ["--workers", "0"]]
)
def test_serve_usage_errors_exit_2(capsys, argv):
    code = cli.main(["serve", "--root", "a=.", *argv, "--json"])
    out, err = capsys.readouterr()
    assert code == 2 and err == "" and json.loads(out)["error"]["code"] == "invalid_argument"


def test_serve_needs_a_root_that_exists(capsys, tmp_path):
    code = cli.main(["serve", "--token-file", str(tmp_path / "t"), "--json"])
    assert code == 2 and json.loads(capsys.readouterr().out)["error"]["detail"] == {"parameter": "root"}
    code = cli.main(
        ["serve", "--root", f"a={tmp_path / 'nope'}", "--token-file", str(tmp_path / "t"), "--json"]
    )
    assert code == 1 and json.loads(capsys.readouterr().out)["error"]["code"] == "not_found"
    assert not (tmp_path / "t").exists()
