"""SolidSeas as an MCP server (``solidseas_app.assistant.mcp_server``): the protocol, the
tools, the person's confirmation, the machine policy and the stdio transport, against the
part held in memory (``automatic_support``). Nothing here reaches SOLIDWORKS or a network;
``tests/test_swapi_live.py`` drives the server against SolidSeas' own SOLIDWORKS, opt-in."""

from __future__ import annotations

import dataclasses
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from automatic_support import DEPTH, DOCUMENT, FILLET, FINISH, WindowLive, block
from solidseas import __version__, policy
from solidseas.ai.factory import AISettings
from solidseas_app.assistant import mcp_server
from solidseas_app.assistant.mcp_server import (
    AUTOMATIC_OFF,
    LOCAL_ONLY,
    PROTOCOL_VERSIONS,
    READ_FIRST,
    McpServer,
)
from solidseas_app.assistant.run import differences
from solidseas_app.assistant.session import LiveDocument, LiveSession, SessionList

ROOT = Path(__file__).resolve().parents[1]


def request(method: str, params: dict | None = None, rid: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        message["params"] = params
    return message


def call(server: McpServer, name: str, arguments: dict | None = None, rid: int = 1) -> dict:
    reply = server.handle(request("tools/call", {"name": name, "arguments": arguments or {}}, rid))
    assert "result" in reply, reply
    return reply["result"]


def data(result: dict) -> dict:
    assert result["isError"] is False, result
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def refused(result: dict) -> str:
    assert result["isError"] is True and "structuredContent" not in result
    return result["content"][0]["text"]


_servers: list[McpServer] = []


@pytest.fixture(autouse=True)
def servers_closed():
    """Each test's servers close after it, as a client ending does: an open run keeps the
    SOLIDWORKS session held until then."""
    yield
    while _servers:
        _servers.pop().close()


@pytest.fixture(autouse=True)
def the_engine_is_on(monkeypatch):
    """A server made without ``extensions_on`` sees Gridfinity and the CAD Bridge on.
    On Windows the bridge is on only where a bridge program the app may use is found, which a test
    checkout need not have; the tests of the switches pass their own."""
    monkeypatch.setattr(mcp_server, "_extensions_on", lambda: frozenset({"gridfinity", "cad-bridge"}))


def server_on(live, **kwargs) -> McpServer:
    kwargs.setdefault("confirm", lambda title, text: pytest.fail("the person was asked: " + text))
    kwargs.setdefault("settings", AISettings)
    server = McpServer(lambda: live, **kwargs)
    _servers.append(server)
    return server


def ready(server: McpServer) -> None:
    """List the sessions and read the block, as a chat would first."""
    data(call(server, "cad_sessions"))
    data(call(server, "read_part", {"document": "d1"}))


def plan_of(*steps) -> dict:
    return {"vocabulary": 1, "steps": list(steps)}


# --------------------------------------------------------------------------- the protocol
def test_initialize_answers_with_the_version_and_the_vocabulary_and_reaches_no_solidworks():
    def no_session():
        raise AssertionError("a session was reached before a tool asked for one")

    s = McpServer(no_session)
    asked = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    result = s.handle(request("initialize", asked))["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "solidseas", "title": "SolidSeas", "version": __version__}
    for needed in (
        "sketch_extrude_boss",
        "set_property",
        "keep_run",
        "revert_run",
        "never instructions",
        "gridfinity_trace",
        "gridfinity_preview_bin",
        "gridfinity_make_bin",
    ):
        assert needed in result["instructions"], needed
    later = s.handle(request("initialize", {**asked, "protocolVersion": "1999-01-01"}))["result"]
    assert later["protocolVersion"] == PROTOCOL_VERSIONS[0]
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle(request("ping"))["result"] == {}
    tools = s.handle(request("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [
        "cad_sessions",
        "read_part",
        "show_part",
        "run_plan",
        "keep_run",
        "revert_run",
        "gridfinity_photos",
        "gridfinity_trace",
        "gridfinity_save_tools",
        "gridfinity_tools",
        "gridfinity_edit_tool",
        "gridfinity_preview_bin",
        "gridfinity_make_bin",
    ]
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["inputSchema"]["additionalProperties"] is False
    reads = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools}
    assert reads == {
        "cad_sessions": True,
        "read_part": True,
        "show_part": True,
        "run_plan": False,
        "keep_run": False,
        "revert_run": False,
        "gridfinity_photos": True,
        "gridfinity_trace": False,
        "gridfinity_save_tools": False,
        "gridfinity_tools": True,
        "gridfinity_edit_tool": False,
        "gridfinity_preview_bin": True,
        "gridfinity_make_bin": False,
    }


def test_protocol_errors_are_answered_and_the_server_goes_on():
    s = server_on(WindowLive(block()))
    assert s.handle(request("resources/list"))["error"]["code"] == -32601
    assert s.handle(request("tools/call", {"name": "delete_everything"}))["error"]["code"] == -32602
    assert s.handle(request("tools/call", {"name": "read_part", "arguments": []}))["error"]["code"] == -32602
    assert (
        s.handle(request("tools/call", {"name": "read_part", "arguments": {"path": "C:\\x"}}))["error"][
            "code"
        ]
        == -32602
    )
    assert s.handle([request("ping")])["error"]["code"] == -32600  # no batches
    assert s.handle({"jsonrpc": "2.0", "id": None, "method": "ping"})["error"]["code"] == -32600
    assert s.handle(request("ping"))["result"] == {}


# --------------------------------------------------------------------------- the tools
def test_sessions_name_documents_by_ids_and_send_no_titles_unless_allowed():
    live = WindowLive(block())
    sessions = data(call(server_on(live), "cad_sessions"))
    assert sessions["sessions"] == [
        {
            "session": 4242,
            "version": "2024 SP1.0",
            "documents": [{"document": "d1", "kind": "part", "active": False}],
        }
    ]
    assert "block" not in json.dumps(sessions) and "work" not in json.dumps(sessions)
    named = data(call(server_on(live, send_names=True), "cad_sessions"))
    assert named["sessions"][0]["documents"][0]["title"] == "block.SLDPRT" and "titles" not in named


def test_no_solidworks_running_says_why():
    class Nothing(WindowLive):
        def list(self):
            return SessionList((), "No SOLIDWORKS is running.")

    sessions = data(call(server_on(Nothing(block())), "cad_sessions"))
    assert sessions["sessions"] == [] and sessions["why_none"] == "No SOLIDWORKS is running."


def test_read_part_gives_the_summary_with_handles_and_nothing_private():
    live = WindowLive(block())
    s = server_on(live)
    data(call(s, "cad_sessions"))
    part = data(call(s, "read_part", {"document": "d1"}))
    summary = part["summary"]
    assert [p["handle"] for p in summary["planes"]] == ["P1", "P2", "P3"]
    assert [e["handle"] for e in summary["edges"]][:4] == ["E1", "E2", "E3", "E4"]
    assert summary["bounding_box_mm"] == {"min": [0.0, 0.0, 0.0], "max": [20.0, 10.0, 8.0]}
    text = json.dumps(part)
    for private in ("block", "6061", "Front Plane", "Description", "work", "UFAx"):
        assert private not in text, private
    assert "no document" in refused(call(s, "read_part", {"document": "d9"}))


def test_only_parts_are_read():
    drawing = LiveDocument("C:\\work\\block.SLDDRW", "block.SLDDRW", "drawing")

    class WithDrawing(WindowLive):
        def list(self):
            return SessionList((LiveSession(4242, "2024 SP1.0", (drawing,)),))

    s = server_on(WithDrawing(block()))
    data(call(s, "cad_sessions"))
    assert "parts only" in refused(call(s, "read_part", {"document": "d1"}))


def test_a_plan_that_adds_is_carried_out_checked_and_kept():
    live = WindowLive(block())
    s = server_on(live)
    ready(s)
    run = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))
    assert run["status"] == "done" and run["steps"] == [
        {"index": 1, "op": "fillet", "status": "done", "problems": []}
    ]
    assert "keep_run" in run["next"] and "Nothing is saved" in run["next"]
    assert [f["type"] for f in run["summary"]["features"]] == ["ProfileFeature", "Extrusion", "Fillet"]
    text = json.dumps(run)
    assert "checkpoint" not in text and "journal" not in text and os.sep + "runs" not in text
    [operation] = [c for c in live.calls if c[0] == "operation"]
    assert operation[3] == "SolidSeas step 1: fillet" and operation[4] is True
    kept = data(call(s, "keep_run", {"run": run["run"]}))
    assert kept["status"] == "kept"
    assert data(call(s, "keep_run", {"run": run["run"]}))["status"] == "closed"
    assert "no such run" in refused(call(s, "keep_run", {"run": "nope"}))


def test_a_plan_for_a_part_changed_since_it_was_read_is_refused():
    live = WindowLive(block())
    s = server_on(live)
    ready(s)
    live.state = dataclasses.replace(live.state, volume=live.state.volume * 1.5)  # the person edited it
    text = refused(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))
    assert "changed since read_part (volume)" in text and "nothing ran" in text
    assert not [c for c in live.calls if c[0] == "operation"]
    again = refused(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))
    assert "Read the part with read_part first" in again  # its old read was dropped
    data(call(s, "read_part", {"document": "d1"}))  # read again: the plan's handles are checked anew
    assert data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))["status"] == "done"


def test_a_plan_that_overwrites_waits_for_the_person_on_this_pc():
    asked: list[tuple[str, str]] = []
    live = WindowLive(block())
    s = server_on(live, confirm=lambda title, text: asked.append((title, text)) or False)
    ready(s)
    declined = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(DEPTH)}))
    assert declined["status"] == "declined" and not [c for c in live.calls if c[0] == "operation"]
    title, text = asked[0]
    assert title == "SolidSeas: a plan from Claude" and "block.SLDPRT" in text
    assert "1. set_dimension: dimension D3 (from the model); value 9 mm (from the model)" in text
    assert "a value you did not say" in text
    s.confirm = lambda title, text: True
    done = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(DEPTH, FINISH)}))
    assert done["status"] == "done" and live.state.custom_properties["Finish"] == "black"
    # The run's journal keeps the person's Yes; the plan came from the chat, so no prompt was
    # sent from SolidSeas (SolidSeas-k89g). A No starts no run, and so leaves no journal.
    with open(os.path.join(s._runs[done["run"]].start.folder, "journal.jsonl"), encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    events = [line["event"] for line in lines]
    assert events[:3] == ["run_started", "plan", "confirmation"] and "prompt_sent" not in events
    confirmation = lines[2]
    assert confirmation["waited"] is True and confirmation["answer"] == "yes"
    assert len(confirmation["reasons"]) == 2  # the model's 9 mm, and the property it writes


def test_the_saved_always_confirm_setting_makes_every_plan_ask():
    asked = []
    s = server_on(
        WindowLive(block()),
        confirm=lambda title, text: asked.append(text) or False,
        settings=lambda: AISettings(always_confirm=True),
    )
    ready(s)
    assert data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))["status"] == "declined"
    assert "Always confirm the plan before a run is on." in asked[0]


def test_revert_takes_the_run_off_and_says_so():
    live = WindowLive(block())
    baseline = live.state
    s = server_on(live)
    ready(s)
    run = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))
    reverted = data(call(s, "revert_run", {"run": run["run"]}))
    assert reverted["status"] == "reverted" and reverted["message"] == "The part is as it was before the run."
    assert differences(baseline, live.state) == []
    assert [f["type"] for f in reverted["summary"]["features"]] == ["ProfileFeature", "Extrusion"]
    assert "already kept or reverted" in refused(call(s, "revert_run", {"run": run["run"]}))


def test_a_new_plan_keeps_the_run_before_it():
    s = server_on(WindowLive(block()))
    ready(s)
    first = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))
    data(call(s, "read_part", {"document": "d1"}))
    second = data(
        call(
            s,
            "run_plan",
            {
                "document": "d1",
                "plan": plan_of(
                    {"op": "chamfer", "args": {"edges": ["E1"], "distance": {"value": 0.5, "unit": "mm"}}}
                ),
            },
        )
    )
    assert second["kept_before"] == [first["run"]]


def test_plans_are_checked_before_anything_happens():
    live = WindowLive(block())
    s = server_on(live)
    data(call(s, "cad_sessions"))
    assert refused(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)})) == READ_FIRST
    data(call(s, "read_part", {"document": "d1"}))
    bad = {"op": "fillet", "args": {"edges": ["E99"], "radius": {"value": 1, "unit": "mm"}}}
    assert "does not name exactly one entity" in refused(
        call(s, "run_plan", {"document": "d1", "plan": plan_of(bad)})
    )
    nan = {"op": "fillet", "args": {"edges": ["E1"], "radius": {"value": float("nan"), "unit": "mm"}}}
    assert refused(call(s, "run_plan", {"document": "d1", "plan": plan_of(nan)}))
    assert "no plan" in refused(call(s, "run_plan", {"document": "d1", "plan": plan_of()})).lower()
    assert not [c for c in live.calls if c[0] in ("operation", "checkpoint")]


def test_a_refused_start_is_said_and_nothing_changes():
    live = WindowLive(block())
    live.info["active"] = False
    s = server_on(live)
    ready(s)
    assert "not the active document" in refused(
        call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)})
    )
    assert not [c for c in live.calls if c[0] in ("operation", "checkpoint")]


def test_the_policy_is_read_at_every_call(policy_reader):
    s = server_on(WindowLive(block()))
    ready(s)
    policy_reader(policy.Policy(local_only=True))
    for name, args in (
        ("cad_sessions", {}),
        ("read_part", {"document": "d1"}),
        ("run_plan", {"document": "d1", "plan": plan_of(FILLET)}),
    ):
        assert refused(call(s, name, args)) == LOCAL_ONLY
    policy_reader(policy.Policy(automatic_disabled=True))
    assert data(call(s, "read_part", {"document": "d1"}))
    assert refused(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)})) == AUTOMATIC_OFF


def test_a_plan_cancelled_while_the_person_is_asked_never_starts():
    live = WindowLive(block())
    s = server_on(live)

    def cancel_then_yes(title, text):
        s.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}})
        return True

    s.confirm = cancel_then_yes
    ready(s)
    result = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(DEPTH)}, rid=7))
    assert result["status"] == "cancelled" and not [c for c in live.calls if c[0] == "operation"]


def test_closing_keeps_what_was_done_and_lets_solidworks_go():
    live = WindowLive(block())
    closed = []
    live.close = lambda: closed.append(True)
    s = server_on(live)
    ready(s)
    run_id = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)}))["run"]
    s.close()
    assert s._runs[run_id].ended and not s._runs[run_id].start.writer.held and closed == [True]


# --------------------------------------------------------------------------- the transport
def test_serve_reads_json_lines_and_writes_ascii_json_lines():
    live = WindowLive(dataclasses.replace(block()))
    s = server_on(live)
    lines = [
        request("initialize", {"protocolVersion": "2025-06-18"}, 1),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request("tools/call", {"name": "cad_sessions", "arguments": {}}, 2),
        "this is not JSON",
        request("ping", rid="three"),
    ]
    raw = b"".join((json.dumps(m) if isinstance(m, dict) else m).encode() + b"\n" for m in lines)
    out = io.BytesIO()
    s.serve(io.BytesIO(raw + b"\n"), out)
    replies = [json.loads(line) for line in out.getvalue().decode("ascii").splitlines()]
    by_id = {r.get("id"): r for r in replies}
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert by_id[2]["result"]["structuredContent"]["sessions"][0]["documents"][0]["document"] == "d1"
    assert by_id["three"]["result"] == {}
    assert by_id[None]["error"]["code"] == -32700
    assert len(replies) == 4  # the notification is not answered


def test_a_cancelled_call_is_not_answered():
    s = server_on(WindowLive(block()))
    gate = threading.Event()

    class Slow(WindowLive):
        def list(self):
            gate.wait(10)
            return super().list()

    s._sessions = Slow(block())
    lines = [
        request("tools/call", {"name": "cad_sessions", "arguments": {}}, 5),
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 5}},
    ]
    raw = b"".join(json.dumps(m).encode() + b"\n" for m in lines)

    class Reader(io.BytesIO):
        def readline(self, size=-1):
            line = super().readline(size)
            if not line:
                gate.set()  # the call goes on only once the cancellation was read
            return line

    out = io.BytesIO()
    s.serve(Reader(raw), out)
    assert out.getvalue() == b""


def test_a_hostile_line_never_ends_the_server():
    # Before, a line nested too deep for the JSON parser and a cancellation whose id was a
    # list each raised out of the reading loop, and every cancellation was kept for good.
    s = server_on(WindowLive(block()))
    lines = [b"[" * 200_000]
    lines.append(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": [1]}})
    )
    lines += [
        json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": f"n{i}"}})
        for i in range(mcp_server.MAX_CANCELLED + 50)
    ]
    lines.append(json.dumps(request("ping", {}, 9)))
    out = io.BytesIO()
    s.serve(io.BytesIO(b"".join((m if isinstance(m, bytes) else m.encode()) + b"\n" for m in lines)), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == mcp_server.PARSE_ERROR
    assert replies[-1] == {"jsonrpc": "2.0", "id": 9, "result": {}}
    assert len(s._cancelled) == mcp_server.MAX_CANCELLED


def test_calls_past_the_limit_are_refused_at_once():
    s = server_on(WindowLive(block()))
    gate = threading.Event()

    class Slow(WindowLive):
        def list(self):
            gate.wait(30)
            return super().list()

    s._sessions = Slow(block())
    most = mcp_server.MAX_CALLS + mcp_server.MAX_WAITING
    lines = [request("tools/call", {"name": "cad_sessions", "arguments": {}}, i) for i in range(most + 5)]
    raw = b"".join(json.dumps(m).encode() + b"\n" for m in lines)

    class Reader(io.BytesIO):
        def readline(self, size=-1):
            line = super().readline(size)
            if not line:
                gate.set()  # the calls go on only once every line was read
            return line

    out = io.BytesIO()
    s.serve(Reader(raw), out)  # returns once the calls have answered
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    busy = [r["id"] for r in replies if r.get("error", {}).get("code") == mcp_server.SERVER_BUSY]
    assert busy == list(range(most, most + 5))
    assert len([r for r in replies if "result" in r]) == most


def test_the_program_flag_starts_the_server(monkeypatch):
    import runpy

    started = []
    monkeypatch.setattr(mcp_server, "main", lambda argv=None: started.append(argv) or 5)
    monkeypatch.setattr(sys, "argv", ["SolidSeasViewer.exe", "--mcp", "--send-names"])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(ROOT / "src" / "solidseas_app" / "__main__.py"), run_name="__main__")
    assert done.value.code == 5 and started == [["--send-names"]]


def test_unknown_options_are_refused(capsys):
    assert mcp_server.main(["--mcp", "--listen", "0.0.0.0"]) == 2
    assert "unknown" in capsys.readouterr().err


def test_the_server_speaks_over_a_real_pipe(tmp_path):
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        SOLIDSEAS_CACHE_DIR=str(tmp_path),
        SOLIDSEAS_SWBRIDGE=str(tmp_path / "no-bridge.exe"),  # no SOLIDWORKS is reached: no tool is called
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "solidseas_app", "--mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(tmp_path),
    )
    try:
        messages = [
            request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
                1,
            ),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request("tools/list", rid=2),
        ]
        out, err = proc.communicate(b"".join(json.dumps(m).encode() + b"\n" for m in messages), timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err.decode(errors="replace")
    replies = [json.loads(line) for line in out.decode("ascii").splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["serverInfo"]["version"] == __version__
    assert len(replies[1]["result"]["tools"]) == 13
    assert b"MCP server on standard input and output" in err


def test_the_document_used_in_tests_is_a_part():
    assert DOCUMENT.kind == "part"


def test_gridfinity_is_listed_and_answered_only_while_its_extension_is_on():
    from solidseas_app.assistant.mcp_server import GRIDFINITY_OFF
    from solidseas_app.gridfinity import connector

    on = McpServer(lambda: None, extensions_on=lambda: frozenset({"gridfinity", "cad-bridge"}))
    off = McpServer(lambda: None, extensions_on=lambda: frozenset({"cad-bridge"}))
    _servers.extend((on, off))
    names_on = {t["name"] for t in on.handle(request("tools/list"))["result"]["tools"]}
    names_off = {t["name"] for t in off.handle(request("tools/list"))["result"]["tools"]}
    assert connector.TOOL_NAMES <= names_on and not connector.TOOL_NAMES & names_off
    assert names_off == names_on - connector.TOOL_NAMES, "the SOLIDWORKS tools stay"
    asked = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    said = off.handle(request("initialize", asked))["result"]["instructions"]
    assert GRIDFINITY_OFF in said and connector.INSTRUCTIONS not in said
    tool = sorted(connector.TOOL_NAMES)[0]
    assert refused(call(off, tool)) == GRIDFINITY_OFF


def test_the_solidworks_tools_are_listed_only_while_the_engine_is_on():
    from solidseas_app.assistant.mcp_server import ENGINE_OFF, SOLIDWORKS_TOOLS

    on = McpServer(lambda: None, extensions_on=lambda: frozenset({"cad-bridge"}))
    off = McpServer(lambda: None, extensions_on=lambda: frozenset({"gridfinity"}))
    _servers.extend((on, off))
    assert SOLIDWORKS_TOOLS == {
        "cad_sessions",
        "read_part",
        "show_part",
        "run_plan",
        "keep_run",
        "revert_run",
    }
    names_off = {t["name"] for t in off.handle(request("tools/list"))["result"]["tools"]}
    assert not SOLIDWORKS_TOOLS & names_off and names_off
    assert {t["name"] for t in on.handle(request("tools/list"))["result"]["tools"]} == SOLIDWORKS_TOOLS
    asked = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    assert off.handle(request("initialize", asked))["result"]["instructions"].startswith(ENGINE_OFF)
    assert refused(call(off, "cad_sessions")) == ENGINE_OFF


def test_the_former_tool_name_and_extension_id_still_work():
    """``solidworks_sessions`` became ``cad_sessions`` and the extension ``solidworks``
    became ``cad-bridge``: a chat or a caller from before still gets the same answers, while
    only the new name is listed."""
    old = server_on(WindowLive(block()), extensions_on=lambda: frozenset({"solidworks"}))
    listed = {t["name"] for t in old.handle(request("tools/list"))["result"]["tools"]}
    assert "cad_sessions" in listed and "solidworks_sessions" not in listed
    assert old.extensions_on == {"cad-bridge"}
    assert data(call(old, "solidworks_sessions")) == data(call(old, "cad_sessions"))
    off = McpServer(lambda: None, extensions_on=lambda: frozenset({"gridfinity"}))
    _servers.append(off)
    from solidseas_app.assistant.mcp_server import ENGINE_OFF

    assert refused(call(off, "solidworks_sessions")) == ENGINE_OFF


def test_show_part_returns_a_picture_of_the_part_as_last_saved(policy_reader):
    from dataclasses import replace

    from ai_support import box_snapshot
    from solidseas_app.assistant import picture
    from support import fixture_path

    snap = replace(box_snapshot(), path=str(fixture_path("o02_boxA.SLDPRT")))
    live = WindowLive(block())
    live.snapshot = lambda session, document: snap  # the part, saved as the fixture
    s = server_on(live)
    ready(s)
    got = call(s, "show_part", {"document": "d1"})
    assert not got["isError"]
    kinds = [c["type"] for c in got["content"]]
    assert kinds == ["text", "image"] and got["structuredContent"]["caption"] == picture.CAPTION
    policy_reader(policy.Policy(images_disabled=True))
    refused = call(s, "show_part", {"document": "d1"})
    assert refused["isError"] and picture.ADMIN_OFF in refused["content"][0]["text"]


def test_a_picture_that_cannot_be_made_never_names_the_file(tmp_path):
    from dataclasses import replace

    from ai_support import box_snapshot

    gone = tmp_path / "Projects of someone" / "secret bracket.SLDPRT"
    live = WindowLive(block())
    live.snapshot = lambda session, document: replace(box_snapshot(), path=str(gone))
    s = server_on(live)
    ready(s)
    got = call(s, "show_part", {"document": "d1"})
    assert got["isError"]
    said = json.dumps(got)
    assert "No picture of d1 could be made" in said
    assert "someone" not in said and "secret" not in said and str(tmp_path) not in said


def test_a_failed_file_call_is_said_to_the_chat_without_its_path(tmp_path):
    from solidseas_app.assistant.mcp_server import _without_path

    exc = FileNotFoundError(2, "No such file or directory", str(tmp_path / "private" / "a.SLDPRT"))
    assert _without_path(exc) == "A file or system call failed: No such file or directory."
    assert str(tmp_path) not in _without_path(PermissionError(13, "Permission denied", str(tmp_path)))
    assert _without_path(OSError()) == "A file or system call failed: OSError."


def test_a_run_says_each_step_as_progress_when_the_client_asks():
    s = server_on(WindowLive(block()))
    ready(s)
    data(call(s, "read_part", {"document": "d1"}))
    sent = []
    message = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "run_plan",
            "arguments": {"document": "d1", "plan": plan_of(FILLET)},
            "_meta": {"progressToken": "p-1"},
        },
    }
    s._answer(message, sent.append)
    notes = [m for m in sent if m.get("method") == "notifications/progress"]
    assert notes and sent[-1]["id"] == 9, "the progress comes before the reply"
    first = notes[0]["params"]
    assert first["progressToken"] == "p-1" and first["progress"] == 1 and first["total"] == 1
    assert first["message"].startswith("step 1 of 1: ")
    # without a token, no progress
    data(call(s, "read_part", {"document": "d1"}))
    quiet = []
    plain = {k: v for k, v in message["params"].items() if k != "_meta"}
    s._answer({**message, "id": 10, "params": plain}, quiet.append)
    assert [m.get("id") for m in quiet] == [10]


# --------------------------------------------------------------------------- pictures after each step
class CopyingLive(WindowLive):
    """The stand-in part, whose copy after a step is the box fixture, a real SOLIDWORKS file,
    so the picture is drawn as it is from a real copy."""

    def write_checkpoint(self, session, document, path):
        import shutil

        from support import fixture_path

        self.calls.append(("checkpoint", path))
        shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), path)
        return {"path": path}


def test_run_plan_returns_a_picture_after_each_step_only_when_asked():
    from solidseas_app.assistant import picture

    (schema,) = [t["inputSchema"] for t in mcp_server.TOOLS if t["name"] == "run_plan"]
    assert schema["properties"]["pictures"]["type"] == "boolean" and "pictures" not in schema["required"]
    live = CopyingLive(block())
    s = server_on(live, confirm=lambda title, text: True)  # the person says yes to the new depth
    ready(s)
    plain = call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET)})
    assert [c["type"] for c in plain["content"]] == ["text"] and "pictures" not in data(plain)
    data(call(s, "keep_run", {"run": data(plain)["run"]}))
    live.calls.clear()
    ready(s)
    got = call(s, "run_plan", {"document": "d1", "plan": plan_of(DEPTH), "pictures": True})
    run = data(got)
    assert run["status"] == "done" and run["steps"][0]["picture"] == picture.step_caption(1)
    assert "1 picture(s) follow" in run["pictures"]
    text, image = got["content"]
    assert text["type"] == "text" and image["type"] == "image" and image["mimeType"] == "image/png"
    import base64

    png = base64.b64decode(image["data"])
    assert png.startswith(b"\x89PNG") and "_images" not in run
    copies = [c[1] for c in live.calls if c[0] == "checkpoint"]
    assert len(copies) == 2 and copies[1].endswith(f"checkpoint-{run['run']}-step-1.sldprt")
    assert "checkpoint" not in json.dumps(run) and os.sep + "runs" not in json.dumps(run)


def test_run_plan_says_why_a_picture_is_missing_without_naming_the_run_folder(monkeypatch):
    from solidseas_app.assistant import picture

    def fail(path, caption, *, side=picture.SIDE):
        raise OSError(f"{path} could not be read")

    monkeypatch.setattr(picture, "drawn", fail)
    s = server_on(WindowLive(block()))
    ready(s)
    run = data(call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET), "pictures": True}))
    assert run["status"] == "done"  # a picture is a second look; the run goes on without it
    assert run["steps"][0]["picture"].startswith("none: the run's folder")
    assert run["pictures"].startswith("No picture was made")
    assert os.sep + "runs" + os.sep not in json.dumps(run)


def test_run_plan_sends_no_picture_where_an_administrator_forbids_them(policy_reader):
    from solidseas_app.assistant import picture

    live = WindowLive(block())
    s = server_on(live)
    ready(s)
    policy_reader(policy.Policy(images_disabled=True))
    got = call(s, "run_plan", {"document": "d1", "plan": plan_of(FILLET), "pictures": True})
    run = data(got)
    assert run["status"] == "done" and run["pictures"] == picture.ADMIN_OFF
    assert [c["type"] for c in got["content"]] == ["text"] and "picture" not in run["steps"][0]
    assert [c[0] for c in live.calls].count("checkpoint") == 1  # the safety copy only


def test_pictures_is_true_or_false():
    s = server_on(WindowLive(block()))
    ready(s)
    reply = s.handle(
        request(
            "tools/call",
            {"name": "run_plan", "arguments": {"document": "d1", "plan": plan_of(FILLET), "pictures": "yes"}},
        )
    )
    assert reply["error"]["code"] == -32602 and "pictures" in reply["error"]["message"]
