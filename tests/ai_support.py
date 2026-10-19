"""Helpers for the AI connector's tests: a fake provider server and a fake CONNECT proxy on
127.0.0.1, a synthetic part snapshot carrying marker strings that must never reach a
prompt, a stand-in registry for the machine policy, and plan builders.

Nothing here reaches a network or the real Windows Credential Manager, and no real
provider is ever called.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from solidseas.ai.context import (
    Dimension,
    Edge,
    Face,
    Feature,
    PartSnapshot,
    Quantity,
    RefAxis,
    RefPlane,
)

KEY = "sk-test-" + "Kq7xW2" * 6  # a made-up key, shaped like a real one


# --------------------------------------------------------------------------- the fake server
@dataclass
class Reply:
    status: int = 200
    body: Any = b"{}"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Stall:
    """Accept the request and send nothing until the test ends (or ``seconds`` pass)."""

    seconds: float = 30.0


@dataclass
class Drip:
    """Send headers promising ``length`` bytes, then one byte every ``every`` seconds."""

    length: int = 1000
    every: float = 0.2


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class FakeServer:
    """An HTTP server on 127.0.0.1 that answers from a script and records every request."""

    def __init__(self) -> None:
        self.script: list[Any] = []
        self.default: Any = Reply(404, {"error": {"message": "nothing scripted"}})
        self.seen: list[Seen] = []
        self.stop = threading.Event()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                owner.seen.append(
                    Seen(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                )
                item = owner.script.pop(0) if owner.script else owner.default
                if callable(item):
                    item = item(owner.seen[-1])
                if isinstance(item, Stall):
                    owner.stop.wait(item.seconds)
                    self.close_connection = True
                    return
                if isinstance(item, Drip):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(item.length))
                    self.end_headers()
                    for _ in range(item.length):
                        if owner.stop.wait(item.every):
                            return
                        try:
                            self.wfile.write(b" ")
                            self.wfile.flush()
                        except OSError:
                            return
                    return
                data = item.body
                if not isinstance(data, bytes):
                    data = json.dumps(data).encode()
                self.send_response(item.status)
                for k, v in item.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _serve

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()


class FakeProxy:
    """A CONNECT proxy on 127.0.0.1 that records what it is asked, then answers with
    ``status`` and closes (so a TLS handshake through it fails)."""

    def __init__(self, status: str = "407 Proxy Authentication Required") -> None:
        self.status = status
        self.requests: list[str] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                conn.settimeout(5)
                try:
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    self.requests.append(data.decode("latin-1"))
                    conn.sendall(f"HTTP/1.1 {self.status}\r\nContent-Length: 0\r\n\r\n".encode())
                    time.sleep(0.05)
                except OSError:
                    pass

    def close(self) -> None:
        self.sock.close()


# --------------------------------------------------------------------------- provider reply shapes
def anthropic_reply(
    text: str, *, input_tokens: int = 1200, output_tokens: int = 300, stop: str = "end_turn"
) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "stop_reason": stop,
    }


def openai_reply(
    text: str, *, input_tokens: int = 1200, output_tokens: int = 300, finish: str = "stop"
) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


def gemini_reply(
    text: str, *, input_tokens: int = 1200, output_tokens: int = 300, finish: str = "STOP"
) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": input_tokens, "candidatesTokenCount": output_tokens},
    }


def ollama_reply(
    text: str, *, input_tokens: int = 1200, output_tokens: int = 300, done: str = "stop"
) -> dict:
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": input_tokens,
        "eval_count": output_tokens,
        "done_reason": done,
    }


# --------------------------------------------------------------------------- the part
# Strings that sit in the snapshot's never-sent fields. No prompt may hold any of them.
NEVER_SENT = {
    "path": r"D:\Jobs\Example\MARKERPATH-lid.SLDPRT",
    "title": "MARKERTITLE-lid",
    "custom_value": "MARKERPROPVALUE-0042",
    "customer_value": "MARKERCUSTOMERVALUE",
    "configuration_value": "MARKERCFGVALUE-anodize",
    "author": "MARKERAUTHOR",
    "company": "MARKERCOMPANY",
    "material": "MARKERMATERIAL",
    "equation": "MARKEREQUATION",
    "annotation": "MARKERANNOTATION",
    "sketch_text": "MARKERSKETCHTEXT",
    "parameter_path": r"\\server\share\MARKERPARAMPATH.SLDPRT",
}
# Names a person typed: sent only when "Send my feature and property names" is ticked.
TYPED_NAMES = {
    "feature": "MARKERFEATURE Lid boss",
    "sketch": "MARKERSKETCH Lid outline",
    "plane": "MARKERPLANE Front",
    "dimension": "MARKERDIM@MARKERSKETCH",
    "configuration": "MARKERCONFIG",
    "property_name": "MARKERPROPNAME",
}

W, D, H = 0.040, 0.030, 0.010  # the box, in metres


def box_snapshot(*, duplicate_ref: bool = False, solid: bool = True, extra_edges: int = 0) -> PartSnapshot:
    """A 40 x 30 x 10 mm box with a hole, in the shape the bridge reports, carrying the
    marker strings above in every field that must never reach a prompt."""
    planes = (
        RefPlane("pr:plane:front", TYPED_NAMES["plane"], (0, 0, 0), (0, 0, 1), sketch_x=(1, 0, 0)),
        RefPlane("pr:plane:top", "Top Plane", (0, 0, 0), (0, 1, 0), sketch_x=(1, 0, 0)),
        RefPlane("pr:plane:right", "Right Plane", (0, 0, 0), (1, 0, 0), sketch_x=(0, 0, -1)),
    )
    axes = (RefAxis("pr:axis:hole", "Axis1", (0.020, 0.015, 0), (0, 0, 1)),)
    features = (
        Feature(
            "pr:feat:sketch1",
            TYPED_NAMES["sketch"],
            "ProfileFeature",
            parents=("pr:plane:front",),
            sketch_text=(NEVER_SENT["sketch_text"],),
        ),
        Feature(
            "pr:feat:boss",
            TYPED_NAMES["feature"],
            "Extrusion",
            parameters={
                "depth": Quantity(H),
                "end_condition": "blind",
                "draft": Quantity(0.0, "angle"),
                "source": NEVER_SENT["parameter_path"],
                "flip": False,
            },
            parents=("pr:feat:sketch1",),
        ),
        Feature("pr:feat:hole-sketch", "Sketch2", "ProfileFeature", parents=("pr:face:top",)),
        Feature("pr:feat:hole", "Cut-Extrude1", "Cut", parameters={"end_condition": "through_all"}),
        Feature("pr:feat:fillet", "Fillet1", "Fillet", parameters={"radius": Quantity(0.001)}),
    )
    dimensions = (
        Dimension("pr:dim:width", TYPED_NAMES["dimension"], "pr:feat:sketch1", "linear", W),
        Dimension("pr:dim:depth", "D2@Sketch1", "pr:feat:sketch1", "linear", D),
        Dimension("pr:dim:height", "D1@Boss-Extrude1", "pr:feat:boss", "linear", H),
        Dimension("pr:dim:angle", "D3@Sketch1", "pr:feat:sketch1", "angular", 1.5707963267948966),
        Dimension("pr:dim:hole", "D1@Sketch2", "pr:feat:hole-sketch", "diameter", 0.004),
    )
    faces = (
        Face("pr:face:top", "plane", W * D, (0, 0, 1), (0.02, 0.015, H), sketch_x=(1, 0, 0)),
        Face("pr:face:bottom", "plane", W * D, (0, 0, -1), (0.02, 0.015, 0)),
        Face("pr:face:front", "plane", W * H, (0, -1, 0), (0.02, 0, 0.005)),
        Face("pr:face:back", "plane", W * H, (0, 1, 0), (0.02, D, 0.005)),
        Face("pr:face:left", "plane", D * H, (-1, 0, 0), (0, 0.015, 0.005)),
        Face("pr:face:right", "plane", D * H, (1, 0, 0), (W, 0.015, 0.005)),
        Face("pr:face:hole", "cylinder", 0.0001257, None, (0.02, 0.015, 0), axis=(0, 0, 1), radius=0.002),
    )
    corners = [(0, 0), (W, 0), (W, D), (0, D)]
    edges = []
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        edges.append(
            Edge(
                f"pr:edge:top{i}",
                "line",
                (x1, y1, H),
                (x2, y2, H),
                length=abs(x2 - x1) + abs(y2 - y1),
                faces=("pr:face:top", f"pr:face:side{i}"),
            )
        )
        edges.append(
            Edge(
                f"pr:edge:bottom{i}",
                "line",
                (x1, y1, 0),
                (x2, y2, 0),
                length=abs(x2 - x1) + abs(y2 - y1),
                faces=("pr:face:bottom",),
            )
        )
        edges.append(Edge(f"pr:edge:vertical{i}", "line", (x1, y1, 0), (x1, y1, H), length=H))
    edges.append(
        Edge(
            "pr:edge:hole",
            "circle",
            center=(0.02, 0.015, H),
            radius=0.002,
            length=0.012566,
            faces=("pr:face:top", "pr:face:hole"),
        )
    )
    for i in range(extra_edges):
        edges.append(Edge(f"pr:edge:extra{i}", "line", (0, 0, 0), (0.001 * i, 0, 0), length=0.001 * i))
    if duplicate_ref:
        edges.append(Edge("pr:edge:top0", "line", (0, 0, H), (W, 0, H), length=W))
    return PartSnapshot(
        length_unit="mm",
        features=features,
        dimensions=dimensions,
        edges=tuple(edges),
        faces=faces,
        planes=planes,
        axes=axes,
        solid_bodies=1 if solid else 0,
        volume=W * D * H - 3.14159e-6 * 4 * H if solid else None,
        box_min=(0, 0, 0) if solid else None,
        box_max=(W, D, H) if solid else None,
        path=NEVER_SENT["path"],
        title=NEVER_SENT["title"],
        configurations=(TYPED_NAMES["configuration"],),
        active_configuration=TYPED_NAMES["configuration"],
        custom_properties={
            TYPED_NAMES["property_name"]: NEVER_SENT["custom_value"],
            "Customer": NEVER_SENT["customer_value"],
        },
        configuration_properties={
            TYPED_NAMES["configuration"]: {"Finish": NEVER_SENT["configuration_value"]}
        },
        summary_info={"author": NEVER_SENT["author"], "company": NEVER_SENT["company"]},
        material=NEVER_SENT["material"],
        equations=(NEVER_SENT["equation"] + " = 1",),
        annotations=(NEVER_SENT["annotation"],),
    )


def handle_of(summary, ref: str) -> str:
    """The handle the summary gave the entity with persist reference ``ref``."""
    for h in summary.handles.handles():
        t = summary.handles.resolve(h)
        if t is not None and t.ref == ref:
            return h
    raise KeyError(ref)


# --------------------------------------------------------------------------- plans
def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def plan_json(*steps: dict, notes: str = "", vocabulary: Any = 1) -> str:
    return json.dumps({"vocabulary": vocabulary, "steps": list(steps), "notes": notes})


def step(op: str, **args: Any) -> dict:
    return {"op": op, "args": args}


def square(side: float = 10.0, x0: float = 0.0, y0: float = 0.0) -> dict:
    pts = [[x0, y0], [x0 + side, y0], [x0 + side, y0 + side], [x0, y0 + side]]
    return {
        "unit": "mm",
        "segments": [{"type": "line", "start": pts[i], "end": pts[(i + 1) % 4]} for i in range(4)],
    }


# --------------------------------------------------------------------------- the registry
REG_SZ, REG_DWORD, REG_MULTI_SZ = 1, 4, 7


class FakeRegistry:
    """The policy key in memory, with winreg's semantics. ``open_error`` or a value that is
    an exception makes that read raise it."""

    def __init__(
        self, values: dict[str, Any] | None = None, *, open_error: BaseException | None = None
    ) -> None:
        self.values = values
        self.open_error = open_error
        self.closed = 0

    def open(self) -> Any:
        if self.open_error is not None:
            raise self.open_error
        if self.values is None:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return "key"

    def query(self, key: Any, name: str) -> tuple[Any, int]:
        assert self.values is not None
        if name not in self.values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        value = self.values[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self, key: Any) -> None:
        self.closed += 1


# --------------------------------------------------------------------------- a live document, faked
_pids = iter(range(3_000_000_000, 4_000_000_000))


class FakeTarget:
    """What start_run asks the bridge, answered from fields, with every call recorded. Each
    one has a SOLIDWORKS process id of its own, so tests never share a session mutex."""

    def __init__(self, *, kind="part", problem=None, unresolved=(), checkpoint=b"SOLIDWORKS copy", pid=None):
        self.sw_pid = pid if pid is not None else next(_pids)
        self.kind = kind
        self.problem = problem
        self._unresolved = set(unresolved)
        self.checkpoint = checkpoint
        self.calls: list = []

    def document_kind(self):
        self.calls.append("kind")
        return self.kind

    def document_problem(self):
        self.calls.append("problem")
        return self.problem

    def unresolved(self, refs):
        self.calls.append(("unresolved", tuple(refs)))
        return [r for r in refs if r in self._unresolved]

    def write_checkpoint(self, path):
        self.calls.append(("checkpoint", path))
        if isinstance(self.checkpoint, BaseException):
            raise self.checkpoint
        if self.checkpoint is not None:
            with open(path, "wb") as fh:
                fh.write(self.checkpoint)


def summary_of(snapshot=None, **kw):
    from solidseas.ai.context import build_model_summary

    return build_model_summary(snapshot or box_snapshot(), **kw)


def parse(text: str, *, goal: str = "", summary=None, limits=None):
    from solidseas.ai.prompts import parse_plan

    return parse_plan(text, summary or summary_of(), goal=goal, limits=limits)


def said_plan():
    """A one-step plan that starts by itself: the width set to a value the goal said."""
    summary = summary_of()
    width = handle_of(summary, "pr:dim:width")
    return parse(
        plan_json(step("set_dimension", dimension=width, value=mm(45))),
        goal="make it 45 mm wide",
        summary=summary,
    )
