"""The Model Context Protocol's stdio transport, with the standard library alone: JSON-RPC
2.0 messages, one per line, read from standard input and written to standard output.

:class:`StdioEndpoint` speaks the protocol for a server that has tools: ``initialize``
(the newest of :data:`PROTOCOL_VERSIONS` when a client asks for one it does not know),
``notifications/initialized``, ``ping``, ``tools/list``, ``tools/call`` and
``notifications/cancelled``. The server itself is two callables: one that lists its
tools and one that answers a call. Nothing here knows what the tools do.

* A tool call runs on a thread of its own (a daemon thread, so one that never returns
  never keeps the process alive), at most ``max_calls`` at once; meanwhile the reader
  goes on reading, so a ping or a cancellation is answered while a slow call works.
* A cancelled call's reply is never sent, as the protocol asks. The call itself runs
  to its end: :meth:`StdioEndpoint.cancelled` lets a tool look.
* Out: ASCII JSON, compact. In: UTF-8, one message at most :data:`MAX_LINE` bytes.
  A line that is not one JSON-RPC 2.0 object is answered with its error and the
  reader goes on.
* A fault of the server's own is said to the client as an internal error naming the
  exception's type, and on standard error as its type and where it was raised
  (module, function and line), never a traceback with file names.

``solidseas mcp`` (:mod:`solidseas.serve.mcp`) is built on it.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from typing import Any, BinaryIO

# Protocol versions this endpoint speaks, newest first; a client asking for another is
# answered with the newest.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINE = 8 << 20  # bytes in one message read
MAX_CALLS = 4  # tool calls running at once; more wait for one to finish

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)


class InvalidParams(ValueError):
    """A request whose parameters are not what the method takes: a JSON-RPC error, not a
    tool's result."""


def error_message(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def tool_result(
    texts: Sequence[str],
    *,
    structured: dict[str, Any] | None = None,
    images: Sequence[bytes] = (),
    error: bool = False,
) -> dict[str, Any]:
    """A ``tools/call`` result: each text, then each PNG as an image, ``structuredContent``
    when given and ``isError``."""
    content: list[dict[str, Any]] = [{"type": "text", "text": t} for t in texts]
    for png in images:
        content.append(
            {"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"}
        )
    result: dict[str, Any] = {"content": content, "isError": error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def where(exc: BaseException) -> str:
    """Where an exception was raised, as module:function:line, without file names."""
    chain = [
        f"{f.f_globals.get('__name__', '?')}:{f.f_code.co_name}:{lineno}"
        for f, lineno in traceback.walk_tb(exc.__traceback__)
    ]
    return " > ".join(chain[-20:]) or "-"


def _say(text: str) -> None:
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):  # no standard error to write to
        pass


class StdioEndpoint:
    """One MCP server's side of the conversation. ``tools()`` returns the tool
    definitions to list; ``call(name, arguments, request_id)`` answers a call with a
    result (:func:`tool_result`) or raises :class:`InvalidParams` (an unknown tool,
    arguments that are not what it takes). ``instructions()`` is sent with ``initialize``."""

    def __init__(
        self,
        *,
        name: str,
        title: str,
        version: str,
        instructions: Callable[[], str],
        tools: Callable[[], list[dict[str, Any]]],
        call: Callable[[str, dict[str, Any], Any], dict[str, Any]],
        max_calls: int = MAX_CALLS,
    ) -> None:
        self.info = {"name": name, "title": title, "version": version}
        self._instructions = instructions
        self._tools = tools
        self._call = call
        self.protocol = PROTOCOL_VERSIONS[0]
        self._lock = threading.Lock()
        self._cancelled: set[Any] = set()
        self._running: set[Any] = set()
        self._calls = threading.BoundedSemaphore(max_calls)
        self._threads: list[threading.Thread] = []
        self._idle = threading.Condition(self._lock)
        self._write_lock = threading.Lock()
        self._gone = threading.Event()  # nothing more is written: the client went, or close()

    def close(self) -> None:
        """Write nothing more, even for a call that ends later (a reply in the middle of
        being written is finished first)."""
        with self._write_lock:
            self._gone.set()

    # ------------------------------------------------------------------ the transport
    def serve(self, reader: BinaryIO, writer: BinaryIO) -> None:
        """Answer messages from ``reader`` on ``writer`` until ``reader`` ends."""
        lock, gone = self._write_lock, self._gone

        def send(message: dict[str, Any]) -> None:
            line = json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            with lock:
                if gone.is_set():
                    return
                try:
                    writer.write(line.encode("ascii") + b"\n")
                    writer.flush()
                except (OSError, ValueError):  # the client stopped reading
                    gone.set()

        while True:
            line = reader.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                send(error_message(None, INVALID_REQUEST, f"a message is at most {MAX_LINE >> 20} MB"))
                while line and not line.endswith(b"\n"):  # the rest of the long line
                    line = reader.readline(MAX_LINE + 1)
                continue
            if not line.strip():
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                send(error_message(None, PARSE_ERROR, "a message is one JSON object on one line, in UTF-8"))
                continue
            if isinstance(message, dict) and message.get("method") == "tools/call" and "id" in message:
                self._start_call(message, send)
                continue
            reply = self.handle(message)
            if reply is not None:
                send(reply)

    def _start_call(self, message: dict[str, Any], send: Callable[[dict[str, Any]], None]) -> None:
        rid = message.get("id")

        def run() -> None:
            try:
                with self._calls:
                    reply = self.handle(message)
                if reply is not None and not self.cancelled(rid):
                    send(reply)
            finally:  # done only once its reply is written, so a clean exit never cuts one off
                with self._lock:
                    self._running.discard(rid)
                    self._cancelled.discard(rid)
                    self._idle.notify_all()

        with self._lock:
            self._running.add(rid)
            self._threads = [t for t in self._threads if t.is_alive()]
            thread = threading.Thread(target=run, name="mcp-tool-call", daemon=True)
            self._threads.append(thread)
        thread.start()

    def wait_calls(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for the tool calls still running; whether all ended."""
        end = time.monotonic() + timeout
        with self._lock:
            while self._running:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._idle.wait(left)
        return True

    def cancelled(self, rid: Any) -> bool:
        """Whether the client cancelled the request ``rid``."""
        with self._lock:
            return rid in self._cancelled

    # ------------------------------------------------------------------ one message
    def handle(self, message: Any) -> dict[str, Any] | None:
        """One JSON-RPC message: the reply, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            rid = message.get("id") if isinstance(message, dict) else None
            return error_message(rid if _is_id(rid) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        method, params = message.get("method"), message.get("params")
        if "id" not in message:  # a notification: nothing is answered
            if method == "notifications/cancelled" and isinstance(params, dict):
                rid = params.get("requestId")
                with self._lock:
                    if rid in self._running:
                        self._cancelled.add(rid)
            return None
        rid = message["id"]
        if not _is_id(rid):
            return error_message(None, INVALID_REQUEST, "a request's id is a string or a whole number")
        if not isinstance(method, str):
            return error_message(rid, INVALID_REQUEST, "a request names its method")
        if params is not None and not isinstance(params, dict):
            return error_message(rid, INVALID_PARAMS, "params must be an object")
        params = params or {}
        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self._tools()}
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments")
                if not isinstance(name, str):
                    raise InvalidParams("a tool call names its tool")
                if args is None:
                    args = {}
                if not isinstance(args, dict):
                    raise InvalidParams("a tool's arguments are an object")
                result = self._call(name, args, rid)
            else:
                return error_message(rid, METHOD_NOT_FOUND, f"this server has no method {method[:64]!r}")
        except InvalidParams as exc:
            return error_message(rid, INVALID_PARAMS, str(exc))
        except Exception as exc:  # a fault of the server's own: said, and the server goes on
            _say(f"mcp: internal error type={type(exc).__name__} at {where(exc)}")
            return error_message(rid, INTERNAL_ERROR, f"internal error ({type(exc).__name__})")
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        self.protocol = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": self.protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": dict(self.info),
            "instructions": self._instructions(),
        }


def _is_id(rid: Any) -> bool:
    return isinstance(rid, (str, int)) and not isinstance(rid, bool)


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "MAX_LINE",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PROTOCOL_VERSIONS",
    "InvalidParams",
    "StdioEndpoint",
    "error_message",
    "tool_result",
    "where",
]
