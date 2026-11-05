"""SolidCraft as an extension (``solidseas_app.extensions.solidcraft``), and the MCP helper it
runs on (:class:`solidseas.helpers.McpHelper`), against a stand-in MCP server
(``tests/mcp_fake.py``). ``SOLIDSEAS_SOLIDCRAFT_CLI`` naming a real ``solidcraft-cli`` adds a
check against it."""

import json
import os
import sys
from pathlib import Path

import pytest

from solidseas.helpers import HelperError, HelperRequestError, McpHelper
from solidseas_app.assistant.mcp_server import McpServer
from solidseas_app.extensions import solidcraft as S

FAKE = Path(__file__).resolve().parent / "mcp_fake.py"


def fake(*extra: str) -> McpHelper:
    return McpHelper([sys.executable, str(FAKE), *extra], label="the stand-in")


def test_an_mcp_server_starts_lists_its_tools_page_by_page_and_answers():
    with fake() as h:
        assert h.ready["protocol"] == "2025-03-26" and h.ready["server"]["name"] == "fake-mcp"
        assert [t["name"] for t in h.tools()] == ["echo", "broken", "crash_reports"]
        got = h.call("echo", {"a": 1})
        said = json.loads(got["content"][0]["text"])
        assert said["args"] == {"a": 1} and said["initialized"], "initialize is followed by its notification"
        assert got["content"][1]["type"] == "image"
        assert h.call("broken")["isError"] is True
        with pytest.raises(HelperRequestError) as caught:
            h.request("no/such", {})
        assert caught.value.code == "-32601"


def test_an_mcp_server_of_another_revision_is_refused():
    with pytest.raises(HelperError) as caught:
        fake("--version", "1999-01-01")
    assert caught.value.code == "protocol_mismatch"


def test_a_program_that_is_not_an_mcp_server_does_not_start():
    with pytest.raises(HelperError) as caught:
        McpHelper([sys.executable, "-c", "import sys; sys.stdin.read()"], ready_timeout=2)
    assert caught.value.code == "start_failed"


def test_paths_outside_the_folder_are_refused(tmp_path):
    folder = tmp_path / "SolidCraft"
    folder.mkdir()
    (tmp_path / "elsewhere").mkdir()
    S.check_paths({"path": str(folder / "part.step"), "params": {"text": "../not a path"}}, str(folder))
    link = folder / "out"
    try:
        link.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    except OSError:  # no right to make links here
        link = None
    bad = [
        {"path": "part.step"},
        {"path": str(tmp_path / "elsewhere" / "x.step")},
        {"path": str(folder / ".." / "elsewhere" / "x.step")},
        {"path": "\\\\server\\share\\x.step"},
        {"params": {"file": str(tmp_path / "x.ttf")}},
        {"commands": [{"command": "doc.open", "params": {"path": "/etc/passwd"}}]},
    ]
    if link is not None:
        bad.append({"path": str(link / "x.step")})
    for args in bad:
        with pytest.raises(S.Refused):
            S.check_paths(args, str(folder))


def test_a_share_in_any_spelling_is_refused_before_anything_looks_at_it(tmp_path, monkeypatch):
    """A path from the chat that is not in the folder is refused by its text alone: Windows
    reads ``/\\host``, ``\\/host`` and ``\\??\\UNC\\host`` as a share too, and ``realpath`` would
    open it, sending the person's credentials to that host."""
    folder = tmp_path / "SolidCraft"
    folder.mkdir()
    touched = []

    def trap(real):
        def call(path, *a, **k):
            if "evilhost" in os.fspath(path):
                touched.append(os.fspath(path))
                raise AssertionError(f"looked at {path!r}")
            return real(path, *a, **k)

        return call

    for name in ("realpath", "exists", "lexists", "isdir", "islink"):
        monkeypatch.setattr(S.os.path, name, trap(getattr(os.path, name)))
    for name in ("stat", "lstat"):
        monkeypatch.setattr(S.os, name, trap(getattr(os, name)))
    spellings = [
        "\\\\evilhost\\share\\x.step",
        "//evilhost/share/x.step",
        "/\\evilhost\\share\\x.step",
        "\\/evilhost/share/x.step",
        "\\??\\UNC\\evilhost\\share\\x.step",
        "\\\\?\\UNC\\evilhost\\share\\x.step",
        "/evilhost/share/x.step",
    ]
    for value in spellings:
        with pytest.raises(S.Refused):
            S.check_paths({"commands": [{"params": {"out": value}}]}, str(folder))
    assert touched == []
    S.check_paths({"path": str(folder / "part.step")}, str(folder))  # the folder's own still passes


def _client(tmp_path, started=None):
    started = [] if started is None else started

    def start(folder):
        h = fake("mcp", "--allow-path", folder)
        started.append(h)
        return h

    return S.SolidCraft(start=start, folder=str(tmp_path)), started


def test_its_tools_are_named_as_solidcraft_s_and_passed_on(tmp_path):
    client, started = _client(tmp_path)
    try:
        names = [t["name"] for t in client.tools()]
        assert names == ["solidcraft_echo", "solidcraft_broken"], "crash_reports is left out"
        assert client.tools()[0]["description"] == "SolidCraft: Say it back"
        got = client.call("solidcraft_echo", {"path": str(tmp_path / "a.step")})
        said = json.loads(got["content"][0]["text"])
        assert said["args"] == {"path": str(tmp_path / "a.step")}
        assert said["argv"] == ["mcp", "--allow-path", str(tmp_path)]
        assert got["isError"] is False and got["content"][1]["type"] == "image"
        assert client.call("solidcraft_broken", {})["isError"] is True
        for name, args in (("solidcraft_crash_reports", {}), ("solidcraft_echo", {"path": "/etc/x"})):
            with pytest.raises(S.Refused):
                client.call(name, args)
        started[0].kill("test")
        client.call("solidcraft_echo", {})
        assert len(started) == 2, "a server that ended is started again"
    finally:
        client.close()


def test_the_chat_server_lists_and_passes_on_solidcraft_s_tools_only_while_it_is_on(tmp_path):
    client, _started = _client(tmp_path)
    on = McpServer(
        lambda: None, extensions_on=lambda: frozenset({"solidcraft"}), solidcraft_factory=lambda: client
    )
    off = McpServer(lambda: None, extensions_on=lambda: frozenset(), solidcraft_factory=pytest.fail)
    try:
        listed = {
            t["name"]
            for t in on.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        }
        assert {"solidcraft_echo", "solidcraft_broken"} <= listed
        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "solidcraft_echo", "arguments": {}},
        }
        got = on.handle(call)["result"]
        assert got["isError"] is False and got["content"][1]["type"] == "image"
        assert "solidcraft_*" in on.instructions() and str(tmp_path) in on.instructions()
        assert not any(t["name"].startswith("solidcraft_") for t in off.tools())
        assert off.handle(call)["result"]["isError"] is True
        unknown = dict(call, params={"name": "solidcraft_nope", "arguments": {}})
        assert on.handle(unknown)["error"]["code"] == -32602
    finally:
        on.close()
        off.close()


def test_solidcraft_that_will_not_start_leaves_the_other_tools_listed(tmp_path):
    def broken():
        raise RuntimeError("its package changed")

    server = McpServer(
        lambda: None, extensions_on=lambda: frozenset({"solidcraft", "gridfinity"}), solidcraft_factory=broken
    )
    try:
        assert server.tools() and not any(t["name"].startswith("solidcraft_") for t in server.tools())
        assert "its package changed" in server._solidcraft_why
    finally:
        server.close()


REAL = os.environ.get("SOLIDSEAS_SOLIDCRAFT_CLI")


@pytest.mark.skipif(not REAL, reason="SOLIDSEAS_SOLIDCRAFT_CLI names no solidcraft-cli")
def test_the_real_solidcraft_models_measures_and_keeps_to_its_folder(tmp_path):
    client = S.SolidCraft(
        start=lambda folder: McpHelper([REAL, "mcp", "--allow-path", folder]), folder=str(tmp_path)
    )
    try:
        assert "solidcraft_batch" in client.names() and "solidcraft_crash_reports" not in client.names()
        steps = [
            {"command": "sketch.create", "params": {"plane": "XY"}},
            {"command": "sketch.rectangle.two_point", "params": {"p0": [0, 0], "p1": [40, 30]}},
            {"command": "solid.extrude", "params": {"distance": 20}},
        ]
        assert not client.call("solidcraft_batch", {"commands": steps, "verbose": False})["isError"]
        measured = json.loads(client.call("solidcraft_measure", {})["content"][0]["text"])
        assert measured["bodies"][0]["volume_mm3"] == pytest.approx(24000.0)
        shot = client.call("solidcraft_screenshot", {"width": 320, "height": 240})
        assert any(c["type"] == "image" for c in shot["content"])
        out = tmp_path / "box.step"
        assert not client.call("solidcraft_export", {"path": str(out)})["isError"] and out.is_file()
    finally:
        client.close()
