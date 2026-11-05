"""``solidseas mcp``: the REST service's reads for any MCP app (``docs/MCP.md``, "Reading your
CAD files from any MCP app").

Every tool runs in process against the fixtures, through the service's own ``Server``
built without a port, and its ``data`` is compared with what the REST route answers for
the same request on the same root. Then the refusals (a path outside the root, a link,
the machine policy), the tool definitions, the protocol (ping and cancellation while a
call works, unknown methods and tools, bad arguments) and one run over a real pipe to
``python -m solidseas mcp`` that ends when standard input closes.
"""

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from serve_support import PNG, Running
from solidseas import Root, Roots, cli, mcpwire, open_document, policy
from solidseas.serve import ROUTES, ServeConfig, Server, mcp
from support import ASSEMBLY, NATIVE, PARTS, fixture_path, within

pytestmark = pytest.mark.usefixtures("outbound_guard")
SRC = Path(__file__).resolve().parents[1] / "src"
WINDOWS = sys.platform == "win32"
CORE_TOOLS = {
    "roots",
    "list_folder",
    "document_info",
    "properties",
    "configurations",
    "components",
    "references",
    "bill_of_materials",
    "path_report",
    "preview",
}
CATALOG_TOOLS = {"search", "where_used", "duplicates", "missing_references", "recent_changes"}


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("mcp") / "jobs"
    base.mkdir()
    for name in NATIVE:
        shutil.copy2(fixture_path(name), base / name)
    (base / "sub").mkdir()
    shutil.copy2(fixture_path(PARTS[3]), base / "sub" / PARTS[3])
    outside = base.parent / "outside"
    outside.mkdir()
    shutil.copy2(fixture_path(PARTS[1]), outside / PARTS[1])
    try:
        os.symlink(outside, base / "linked", target_is_directory=True)
    except OSError:  # Windows without the right to make links: the link test skips
        pass
    return base


class Connector:
    """The tools over a Server that listens on no port, and a counter for request ids."""

    def __init__(self, root: Path, **config) -> None:
        cfg = ServeConfig(roots=Roots([Root("jobs", str(root))]), tokens={}, workers=2, **config)
        self.server = Server(cfg, listen=False)
        self.server.start()
        assert self.server.wait_ready(120)
        self.connector = mcp.FileConnector(self.server)
        self.endpoint = self.connector.endpoint()
        self.ids = iter(range(1, 1_000_000))
        self.texts: list[str] = []

    def rpc(self, method: str, params: dict | None = None) -> dict:
        message = {"jsonrpc": "2.0", "id": next(self.ids), "method": method}
        if params is not None:
            message["params"] = params
        reply = self.endpoint.handle(message)
        self.texts.append(json.dumps(reply))
        return reply

    def call(self, name: str, **args) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": args})["result"]

    def close(self) -> None:
        self.server.shutdown(close_pool=True)


@pytest.fixture(scope="module")
def conn(root):
    c = Connector(root)
    yield c
    c.close()


@pytest.fixture(scope="module")
def rest(root):
    running = Running({"jobs": root})
    yield running
    running.close()


def _ok(result: dict) -> dict:
    assert result["isError"] is False, result["content"][0]["text"]
    env = result["structuredContent"]
    assert json.loads(result["content"][0]["text"]) == env  # the same envelope, as compact text
    return env


def _error(result: dict) -> dict:
    assert result["isError"] is True
    env = result["structuredContent"]
    assert env["ok"] is False and env["error"]["reader_message"] is None
    return env["error"]


# --------------------------------------------------------------------------- tools and data
def test_tools_list_their_routes_bounds_and_hints(conn):
    tools = {t["name"]: t for t in conn.rpc("tools/list")["result"]["tools"]}
    assert set(tools) == CORE_TOOLS
    for tool in mcp.TOOLS:
        route = ROUTES[tool.route]
        assert set(tool.arguments) <= set(route.params), tool.name
        if tool.name not in tools:
            continue
        t = tools[tool.name]
        assert t["annotations"]["readOnlyHint"] is True and t["annotations"]["openWorldHint"] is False
        schema = t["inputSchema"]
        assert schema["additionalProperties"] is False and set(schema["properties"]) == set(tool.arguments)
        assert set(schema.get("required", ())) == {n for n in tool.arguments if route.params[n].required}
        assert t["description"] and all(p["description"] for p in schema["properties"].values())
    comp = tools["components"]["inputSchema"]["properties"]
    assert comp["max_depth"] == {**comp["max_depth"], "type": "integer", "minimum": 1, "maximum": 32}
    assert comp["max_nodes"]["maximum"] == 10_000 and comp["flat"]["type"] == "boolean"
    listing = tools["list_folder"]["inputSchema"]["properties"]
    assert listing["include"]["items"]["enum"] == ["properties", "configurations", "preview", "preview_data"]
    assert listing["limit"]["minimum"] == 1 and listing["limit"]["maximum"] == 500
    assert tools["bill_of_materials"]["inputSchema"]["properties"]["type"]["enum"] == [
        "top",
        "parts",
        "indented",
    ]
    assert "jobs" in tools["document_info"]["inputSchema"]["properties"]["root"]["description"]


def test_initialize_names_the_roots_by_id_and_never_their_paths(conn, root):
    result = conn.rpc("initialize", {"protocolVersion": "2099-01-01"})["result"]
    assert result["protocolVersion"] == mcpwire.PROTOCOL_VERSIONS[0]
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert "jobs (project)" in result["instructions"] and str(root) not in result["instructions"]
    assert (
        conn.rpc("initialize", {"protocolVersion": "2024-11-05"})["result"]["protocolVersion"] == "2024-11-05"
    )


@pytest.mark.parametrize(
    ("tool", "route", "extra"),
    [
        ("document_info", "document", {}),
        ("properties", "properties", {}),
        ("properties", "properties", {"view": "file"}),
        ("configurations", "configurations", {}),
        ("components", "components", {}),
        ("components", "components", {"flat": True, "max_depth": 2}),
        ("references", "references", {}),
        ("references", "references", {"resolve": True}),
        ("path_report", "path-report", {}),
    ],
)
def test_each_document_answers_what_the_rest_route_answers(conn, rest, tool, route, extra):
    for name in NATIVE:
        env = _ok(conn.call(tool, root="jobs", path=name, **extra))
        query = {k: ("1" if v is True else str(v)) for k, v in extra.items()}
        r = rest.get(route, root="jobs", path=name, **query)
        assert r.status == 200 and env == r.json(), (tool, name)


def test_a_bom_and_a_listing_are_the_rest_routes(conn, rest):
    for bom_type in ("top", "parts", "indented"):
        env = _ok(conn.call("bill_of_materials", root="jobs", path=ASSEMBLY, type=bom_type, columns="A,B"))
        want = rest.get("bom", root="jobs", path=ASSEMBLY, type=bom_type, columns="A,B").json()
        assert env == want
    env = _ok(conn.call("list_folder", root="jobs", recursive=True, include=["properties", "configurations"]))
    want = rest.get("list", root="jobs", recursive="1", include="properties,configurations").json()
    assert env == want and len(env["data"]["entries"]) >= len(NATIVE) + 1


def test_a_page_says_it_was_cut_and_the_cursor_gets_the_rest(conn):
    first = conn.call("list_folder", root="jobs", limit=2)
    data = _ok(first)["data"]
    assert data["truncated"] is True and data["next_cursor"]
    note = first["content"][1]["text"]
    assert "stopped at the limit of entries" in note and data["next_cursor"] in note
    seen = [e["path"] for e in data["entries"]]
    while data["next_cursor"]:
        data = _ok(conn.call("list_folder", root="jobs", limit=2, cursor=data["next_cursor"]))["data"]
        seen += [e["path"] for e in data["entries"]]
    whole = conn.call("list_folder", root="jobs", limit=500)
    assert seen == [e["path"] for e in _ok(whole)["data"]["entries"]] and len(whole["content"]) == 1


def test_roots_and_preview(conn, rest):
    env = _ok(conn.call("roots"))
    assert env == rest.get("roots").json() and env["data"]["roots"][0]["id"] == "jobs"
    pictures = 0
    for name in NATIVE:
        with open_document(fixture_path(name)) as doc:
            stored = doc.preview()
        result = conn.call("preview", root="jobs", path=name)
        if stored is None:
            assert _error(result)["code"] == "no_preview"
            continue
        assert result["isError"] is False
        image = result["content"][1]
        assert image["type"] == "image" and image["mimeType"] == "image/png"
        png = base64.b64decode(image["data"])
        assert png.startswith(PNG)
        if stored.mime == "image/png":
            assert png == rest.get("preview", root="jobs", path=name).body
            pictures += 1
        meta = result["structuredContent"]
        assert meta["source"] == {"root": "jobs", "path": name} and meta["width"] > 0
    assert pictures >= 1


# --------------------------------------------------------------------------- refusals
@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("../outside/" + PARTS[1], "dot_component"),
        ("/etc/" + PARTS[1], "absolute"),
        ("sub\\" + PARTS[3], "backslash"),
        ("C:" + PARTS[1], "colon"),
    ],
)
def test_a_path_outside_the_root_is_refused(conn, path, rule):
    err = _error(conn.call("document_info", root="jobs", path=path))
    assert err["code"] == "path_refused" and err["detail"]["rule"] == rule


def test_a_link_out_of_the_root_is_refused(conn, root):
    if not (root / "linked").is_symlink():
        pytest.skip("this account cannot make symbolic links")
    err = _error(conn.call("document_info", root="jobs", path="linked/" + PARTS[1]))
    assert err["code"] == "link_refused" and err["detail"]["rule"] == "link_in_path"
    err = _error(conn.call("list_folder", root="jobs", path="linked"))
    assert err["code"] == "link_refused"


def test_no_answer_holds_a_path_of_this_machine(conn, root):
    every = "\n".join(conn.texts)
    assert conn.texts and str(root) not in every and str(root.parent) not in every
    assert str(root).replace("\\", "\\\\") not in every


def test_the_machine_policy_refuses_every_tool_when_only_a_local_model_may_read(conn, policy_reader):
    calls = [
        (name, {"root": "jobs", "path": ASSEMBLY}) for name in sorted(CORE_TOOLS - {"roots", "list_folder"})
    ]
    calls += [("roots", {}), ("list_folder", {"root": "jobs"})]
    for reader in (policy.Policy(local_only=True), lambda: 1 / 0, lambda: "not a policy"):
        policy_reader(reader)
        for name, args in calls:
            result = conn.call(name, **args)
            assert result["isError"] is True and result["content"][0]["text"] == mcp.LOCAL_ONLY, name
    policy_reader(policy.NO_POLICY)
    assert conn.call("roots")["isError"] is False


def test_the_machine_policy_keeps_pictures_back(conn, policy_reader):
    policy_reader(policy.Policy(images_disabled=True))
    result = conn.call("preview", root="jobs", path=PARTS[1])
    assert result["isError"] is True and result["content"][0]["text"] == mcp.NO_IMAGES
    result = conn.call("list_folder", root="jobs", include=["preview_data"])
    assert result["isError"] is True and result["content"][0]["text"] == mcp.NO_IMAGES
    _ok(conn.call("list_folder", root="jobs", include=["preview"]))
    _ok(conn.call("document_info", root="jobs", path=PARTS[1]))


# --------------------------------------------------------------------------- arguments and protocol
@pytest.mark.parametrize(
    ("tool", "args", "code", "parameter"),
    [
        ("document_info", {"root": "jobs"}, "invalid_argument", "path"),
        ("document_info", {"root": "jobs", "path": PARTS[1], "bogus": 1}, "unknown_parameter", "bogus"),
        ("components", {"root": "jobs", "path": ASSEMBLY, "max_depth": 0}, "invalid_argument", "max_depth"),
        ("components", {"root": "jobs", "path": ASSEMBLY, "max_depth": 2.0}, "invalid_argument", "max_depth"),
        ("components", {"root": "jobs", "path": ASSEMBLY, "flat": "yes"}, "invalid_argument", "flat"),
        ("properties", {"root": "jobs", "path": PARTS[1], "view": "Effective"}, "invalid_argument", "view"),
        ("list_folder", {"root": "jobs", "include": "properties"}, "invalid_argument", "include"),
        ("list_folder", {"root": "jobs", "include": ["thumbnails"]}, "invalid_argument", "include"),
        ("list_folder", {"root": "jobs", "limit": 501}, "invalid_argument", "limit"),
        ("document_info", {"root": "Jobs!", "path": PARTS[1]}, "invalid_argument", "root"),
        ("document_info", {"root": "jobs", "path": ""}, "invalid_argument", "path"),
        ("document_info", {"root": "jobs", "path": "\ud800.SLDPRT"}, "invalid_argument", "path"),
    ],
)
def test_bad_arguments_get_the_routes_own_refusal(conn, tool, args, code, parameter):
    err = _error(conn.call(tool, **args))
    assert err["code"] == code and err["detail"]["parameter"] == parameter


def test_an_unknown_root_or_file(conn):
    err = _error(conn.call("document_info", root="nope", path=PARTS[1]))
    assert err["code"] == "root_not_found"
    result = conn.call("document_info", root="jobs", path="missing.SLDPRT")
    assert _error(result)["code"] == "not_found"
    assert result["structuredContent"]["source"] == {"root": "jobs", "path": "missing.SLDPRT"}


def test_unknown_tools_methods_and_messages_are_protocol_errors(conn):
    for params, code in (
        ({"name": "write_file", "arguments": {}}, mcpwire.INVALID_PARAMS),
        ({"name": "search", "arguments": {"q": "box"}}, mcpwire.INVALID_PARAMS),  # no --catalog
        ({"name": "roots", "arguments": [1]}, mcpwire.INVALID_PARAMS),
        ({"arguments": {}}, mcpwire.INVALID_PARAMS),
    ):
        assert conn.rpc("tools/call", params)["error"]["code"] == code
    assert conn.rpc("resources/list")["error"]["code"] == mcpwire.METHOD_NOT_FOUND
    assert conn.rpc("ping")["result"] == {}
    assert conn.endpoint.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert conn.endpoint.handle([1, 2])["error"]["code"] == mcpwire.INVALID_REQUEST
    assert conn.endpoint.handle({"jsonrpc": "2.0", "id": 1.5, "method": "ping"})["error"]["code"] == (
        mcpwire.INVALID_REQUEST
    )


def test_ping_and_cancel_are_read_while_a_call_works():
    release = threading.Event()
    started = threading.Event()

    def call(name, args, rid):
        started.set()
        release.wait(30)
        return mcpwire.tool_result(["done"])

    endpoint = mcpwire.StdioEndpoint(
        name="t", title="t", version="0", instructions=lambda: "", tools=lambda: [], call=call
    )
    lines = [
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "slow"}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "slow"}},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}},
        {"jsonrpc": "2.0", "id": 9, "method": "ping"},
    ]
    reader = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in lines) + b"not json\n")
    out = io.BytesIO()
    endpoint.serve(reader, out)  # returns at the end of input, with the calls still waiting
    assert started.wait(10)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert {"jsonrpc": "2.0", "id": 9, "result": {}} in replies  # answered while both calls wait
    assert any(r.get("error", {}).get("code") == mcpwire.PARSE_ERROR for r in replies)
    release.set()
    assert endpoint.wait_calls(within(10))
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    ids = [r.get("id") for r in replies]
    assert 8 in ids and 7 not in ids  # a cancelled call's reply is never sent


# --------------------------------------------------------------------------- the catalog and the command
def test_the_catalog_tools_answer_with_catalog(root, rest):
    c = Connector(root, catalog=True)
    try:
        names = {t["name"] for t in c.rpc("tools/list")["result"]["tools"]}
        assert names == CORE_TOOLS | CATALOG_TOOLS
        assert "catalog" in c.rpc("initialize", {})["result"]["instructions"]
        from serve_support import wait_for

        assert wait_for(lambda: c.server._catalog_path is not None, 120)
        hits = _ok(c.call("search", q="boxA"))
        assert hits["kind"] == "catalog_search" and hits["data"]["results"]
        used = _ok(c.call("where_used", root="jobs", path=PARTS[1]))
        assert used["kind"] == "where_used" and used["source"] == {"root": "jobs", "path": PARTS[1]}
        assert _ok(c.call("duplicates", names=True))["kind"] == "duplicates"
        assert _ok(c.call("missing_references", limit=5))["kind"] == "missing_references"
        assert _ok(c.call("recent_changes", since="1d"))["kind"] == "catalog_changes"
        assert _error(c.call("where_used", root="jobs", path="nope.SLDPRT"))["code"] == "not_in_catalog"
    finally:
        c.close()


def test_the_command_checks_its_roots_before_it_serves(capsys, tmp_path):
    assert cli.main(["mcp"]) == 2
    assert mcp.main(["--root", f"jobs={tmp_path / 'gone'}", "--json"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "needs at least one --root" in err and "not found" in err  # stdout is the protocol's


def test_a_real_pipe_from_initialize_to_a_clean_exit(tmp_path):
    shutil.copy2(fixture_path(PARTS[1]), tmp_path / PARTS[1])
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    log = open(tmp_path / "stderr.txt", "wb")  # a file: a pipe nobody reads could fill
    proc = subprocess.Popen(
        [sys.executable, "-m", "solidseas", "mcp", "--root", f"jobs={tmp_path}", "--workers", "1"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        env=env,
    )
    try:

        def ask(rid, method, params=None):
            message = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
            proc.stdin.write(json.dumps(message).encode() + b"\n")
            proc.stdin.flush()
            reply = json.loads(proc.stdout.readline())
            assert reply["id"] == rid
            return reply["result"]

        assert ask(1, "initialize", {"protocolVersion": "2025-06-18"})["protocolVersion"] == "2025-06-18"
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        assert {t["name"] for t in ask(2, "tools/list")["tools"]} == CORE_TOOLS
        result = ask(
            3, "tools/call", {"name": "document_info", "arguments": {"root": "jobs", "path": PARTS[1]}}
        )
        env = _ok(result)
        assert env["kind"] == "document_summary" and env["source"] == {"root": "jobs", "path": PARTS[1]}
        assert str(tmp_path) not in json.dumps(result)
        proc.stdin.close()
        assert proc.wait(within(30)) == 0
        assert proc.stdout.read() == b""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
    text = (tmp_path / "stderr.txt").read_text(encoding="utf-8", errors="replace")
    assert "mcp stopped" in text and "Traceback" not in text
