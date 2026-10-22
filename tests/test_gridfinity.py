"""The Gridfinity connector (``solidseas_app.gridfinity``): Tracefinity reached on this PC's
loopback only, directly or through an SSH tunnel (``fake_ssh.py`` stands in for ssh), the
photos folder, tracing, the tool library, the layout and the bin's files, against a
Tracefinity held in memory on 127.0.0.1 (:class:`FakeTracefinity`), and the tools as the MCP
server serves them. Nothing here reaches a network."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import socket
import struct
import subprocess
import sys
import textwrap
import threading
import time
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from solidseas import policy
from solidseas.ai.errors import CancelledError
from solidseas.ai.http import Cancel
from solidseas_app.assistant.mcp_server import LOCAL_ONLY, McpServer
from solidseas_app.gridfinity import connector as gridfinity
from solidseas_app.gridfinity import labels, layout, tunnel
from solidseas_app.gridfinity.connector import SCOOP_ID, BadArguments, Gridfinity, Refused, safe_file_name
from solidseas_app.gridfinity.png import Canvas
from solidseas_app.gridfinity.tracefinity import URL_ENV, Tracefinity, TracefinityError, segment
from solidseas_app.gridfinity.tunnel import SshTunnel, TunnelError, listening

# The base interpreter, so that the stand-in is one process as ssh is: a venv's python.exe on
# Windows starts the real interpreter as a child, which would outlive the one SolidSeas ends.
FAKE_SSH = [getattr(sys, "_base_executable", sys.executable), str(Path(__file__).with_name("fake_ssh.py"))]


def closed(port: int, within: float = 5.0) -> bool:
    """Nothing listens on ``port`` any more, within ``within`` seconds."""
    deadline = time.monotonic() + within
    while listening(port) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not listening(port)


@pytest.fixture(autouse=True)
def no_settings(monkeypatch):
    """The tests choose their own Tracefinity: none from this PC's settings."""
    for name in (URL_ENV, tunnel.SSH_ENV, tunnel.KEY_ENV, gridfinity.PHOTOS_ENV, gridfinity.BINS_ENV):
        monkeypatch.delenv(name, raising=False)


SCALE = 0.25  # mm a pixel of the fake's corrected photos
CORNERS = [
    {"x": 100.0, "y": 80.0},
    {"x": 940.0, "y": 90.0},
    {"x": 930.0, "y": 1270.0},
    {"x": 95.0, "y": 1260.0},
]
PHOTO = b"\xff\xd8\xff\xe0 not really a JPEG"


def rect_px(x0: float, y0: float, w: float, h: float) -> list[dict]:
    return [{"x": x, "y": y} for x, y in ((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h))]


def disc_px(cx: float, cy: float, r: float, n: int = 48) -> list[dict]:
    return [
        {"x": cx + r * math.cos(2 * math.pi * k / n), "y": cy + r * math.sin(2 * math.pi * k / n)}
        for k in range(n)
    ]


# A 176 x 36 mm bar standing upright on the paper and a 22 mm disc to its left.
BAR = {"points": rect_px(400, 200, 144, 704)}
DISC = {"points": disc_px(250, 700, 44)}


class FakeTracefinity:
    """The routes of Tracefinity 0.10 the connector uses, held in memory. ``requests`` holds
    each (method, path, body, headers); ``error`` makes every request answer (status, body)."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes, dict]] = []
        self.polygons: list[dict] = [BAR, DISC]
        self.corners: list[dict] | None = CORNERS
        self.warnings: list[str] = []
        self.error: tuple[int, dict] | None = None
        self.hold = threading.Event()  # set: a trace answers at once
        self.hold.set()
        self.split = 1
        self.sessions: dict[str, dict] = {}
        self.tools: dict[str, dict] = {}
        self.bins: dict[str, dict] = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, kind, payload = fake.route(self.command, self.path, body, dict(self.headers))
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = _answer

            def log_message(self, *args) -> None:
                pass

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                pass  # a client that stopped waiting (the cancel tests) hung up first

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.hold.set()
        self.server.shutdown()
        self.server.server_close()

    def calls(self, method: str, pattern: str) -> list[dict]:
        return [
            json.loads(b or b"null")
            for m, p, b, _ in self.requests
            if m == method and re.fullmatch(pattern, p)
        ]

    def route(self, method: str, path: str, body: bytes, headers: dict) -> tuple[int, str, bytes]:
        self.requests.append((method, path, body, headers))
        if self.error is not None:
            return self.error[0], "application/json", json.dumps(self.error[1]).encode()
        found = self._route(method, path, body)
        if found is None:
            return 404, "application/json", b'{"detail": "Not Found"}'
        if isinstance(found, bytes):
            return 200, "application/octet-stream", found
        return 200, "application/json", json.dumps(found).encode()

    def _route(self, method: str, path: str, body: bytes):
        parts = path.strip("/").split("/")
        if method == "GET" and path == "/api/version":
            return {"version": "0.10.0"}
        if method == "POST" and path == "/api/upload":
            sid = str(uuid.uuid4())
            self.sessions[sid] = {"id": sid, "polygons": [], "scale_factor": None}
            return {"session_id": sid, "image_url": "/storage/x", "detected_corners": self.corners}
        if parts[:2] == ["api", "sessions"] and len(parts) >= 3:
            session = self.sessions.get(parts[2])
            if session is None:
                return None
            if method == "GET" and len(parts) == 3:
                return session
            if method == "POST" and parts[3:] == ["corners"]:
                session["scale_factor"] = SCALE
                return {"corrected_image_url": "/storage/y", "scale_factor": SCALE, "warnings": self.warnings}
            if method == "POST" and parts[3:] == ["trace"]:
                self.hold.wait(10)
                session["polygons"] = [
                    {
                        "id": str(uuid.uuid4()),
                        "label": f"tool {i + 1}",
                        "finger_holes": [],
                        "interior_rings": [],
                        **p,
                    }
                    for i, p in enumerate(self.polygons)
                ]
                return {"polygons": session["polygons"], "mask_url": None}
            if method == "POST" and parts[3:] == ["save-tools"]:
                wanted = set(json.loads(body)["polygon_ids"])
                ids = []
                for p in session["polygons"]:
                    if p["id"] in wanted:
                        mm = [(q["x"] * SCALE, q["y"] * SCALE) for q in p["points"]]
                        cx = (min(x for x, _ in mm) + max(x for x, _ in mm)) / 2
                        cy = (min(y for _, y in mm) + max(y for _, y in mm)) / 2
                        tool_id = str(uuid.uuid4())
                        self.tools[tool_id] = {
                            "id": tool_id,
                            "name": p["label"],
                            "points": [{"x": x - cx, "y": y - cy} for x, y in mm],
                            "finger_holes": [],
                            "interior_rings": [],
                            "created_at": f"2026-10-12T19:{len(self.tools):02d}:00",
                        }
                        ids.append(tool_id)
                return {"tool_ids": ids}
            return None
        if parts[:2] == ["api", "tools"]:
            if method == "GET" and len(parts) == 2:
                return {"tools": [{**t, "point_count": len(t["points"])} for t in self.tools.values()]}
            tool = self.tools.get(parts[2]) if len(parts) == 3 else None
            if tool is None:
                return None
            if method == "GET":
                return tool
            if method == "PUT":
                tool.update(json.loads(body))
                return {"status": "ok"}
        if parts[:2] == ["api", "bins"]:
            if method == "POST" and len(parts) == 2:
                bin_id = str(uuid.uuid4())
                made = json.loads(body)
                self.bins[bin_id] = {"id": bin_id, "name": made["name"], "bin_config": made["bin_config"]}
                return self.bins[bin_id]
            made = self.bins.get(parts[2]) if len(parts) >= 3 else None
            if made is None:
                return None
            if method == "PUT":
                made.update(json.loads(body))
                return {"status": "ok"}
            if method == "POST" and parts[3:] == ["generate"]:
                many = self.split > 1
                return {
                    "stl_url": f"/storage/default/outputs/{made['id']}.stl",
                    "stl_urls": [f"/p{k}.stl" for k in range(self.split)] if many else [],
                    "threemf_url": f"/storage/default/outputs/{made['id']}.3mf"
                    if made.get("text_labels")
                    else None,
                    "split_count": self.split,
                    "zip_url": "/z.zip" if many else None,
                    "warning": None,
                }
        if method == "GET" and parts[:3] == ["api", "files", "bins"] and len(parts) == 5:
            if parts[3] in self.bins and parts[4] in ("bin.stl", "bin.3mf", "bin_parts.zip"):
                return f"{parts[4]} of {parts[3]}".encode()
        return None


@pytest.fixture
def fake():
    server = FakeTracefinity()
    yield server
    server.close()


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def connector(fake: FakeTracefinity, home) -> Gridfinity:
    return Gridfinity(
        lambda: Tracefinity(fake.url, tunnel=None),
        photos=str(home / "Pictures" / "Gridfinity"),
        bins=str(home / "Documents" / "Gridfinity bins"),
        home=str(home),
    )


def photo(home, name: str = "tools.jpg", data: bytes = PHOTO) -> str:
    folder = home / "Pictures" / "Gridfinity"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return name


def png_size(data: bytes) -> tuple[int, int]:
    """A PNG's width and height, after checking every chunk's CRC and the pixels' length."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    at, idat, size = 8, b"", None
    while at < len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        tag, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + length]
        assert struct.unpack(">I", data[at + 8 + length : at + 12 + length])[0] == zlib.crc32(tag + body)
        if tag == b"IHDR":
            size = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        at += 12 + length
    assert size is not None
    assert len(zlib.decompress(idat)) == size[1] * (1 + 3 * size[0])
    return size


def traced(g: Gridfinity, home, paper: str = "a4") -> dict:
    data, _ = g.call("gridfinity_trace", {"photo": photo(home), "paper": paper})
    return data


# --------------------------------------------------------------------------- Tracefinity
def test_tracefinity_is_reached_on_this_pc_only(monkeypatch):
    for url in (
        "http://203.0.113.20:3000",
        "https://tracefinity.example",
        "http://[::ffff:203.0.113.1]:3000",
    ):
        with pytest.raises(TracefinityError, match="on this PC only"):
            Tracefinity(url)
    with pytest.raises(TracefinityError, match="not usable"):
        Tracefinity("ftp://127.0.0.1")
    assert Tracefinity("http://localhost:3000").where == "http://localhost:3000"
    monkeypatch.setenv(URL_ENV, "http://198.51.100.7:3000")
    with pytest.raises(TracefinityError, match="on this PC only"):
        Tracefinity()
    monkeypatch.delenv(URL_ENV)
    assert Tracefinity().page("bins", "b1") == "http://127.0.0.1:3077/bins/b1"
    assert Tracefinity().tunnel is None  # no server named: Tracefinity runs on this PC


def test_ids_are_checked_before_they_become_part_of_a_path(fake):
    for bad in ("../tools", "a/b", "", "x" * 65, None, 3, "a b", "%2e%2e"):
        with pytest.raises(TracefinityError, match="is not a tool id"):
            segment(bad, "tool")
    with pytest.raises(TracefinityError):
        Tracefinity(fake.url).tool("../../api/bins")
    assert fake.requests == []


def test_a_tracefinity_that_is_not_running_is_explained():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens once it is closed
    with pytest.raises(TracefinityError, match="not answering .* Docker Desktop"):
        Tracefinity(f"http://127.0.0.1:{port}").version()


def test_a_tracefinity_that_asks_to_sign_in_is_never_signed_in_to(fake):
    fake.error = (401, {"detail": "not authenticated"})
    with pytest.raises(TracefinityError, match="asks to sign in. SolidSeas does not sign in"):
        Tracefinity(fake.url).tools()
    assert all("authorization" not in {k.lower() for k in h} for _, _, _, h in fake.requests)


def test_tracefinitys_reason_for_refusing_is_passed_on_short(fake):
    fake.error = (422, {"detail": [{"msg": "field required"}, {"msg": "x" * 900}]})
    with pytest.raises(TracefinityError, match=r"refused: field required; x+\.\.\. \(status 422\)") as caught:
        Tracefinity(fake.url).version()
    assert len(str(caught.value)) < 400


# --------------------------------------------------------------------------- photos
def test_photos_are_listed_newest_first_and_the_folder_is_made(fake, home):
    g = connector(fake, home)
    first, _ = g.call("gridfinity_photos", {})
    assert first["photos"] == [] and "just made" in first["note"]
    assert first["folder"] == os.path.join("%USERPROFILE%", "Pictures", "Gridfinity")
    folder = home / "Pictures" / "Gridfinity"
    for k, name in enumerate(["old.png", "new.JPG", "notes.txt", "mid.heic"]):
        (folder / name).write_bytes(b"x" * 3000)
        os.utime(folder / name, (1_700_000_000 + k * 100, 1_700_000_000 + k * 100))
    os.utime(folder / "new.JPG", (1_800_000_000, 1_800_000_000))
    (folder / "folder.jpg").mkdir()
    listed, images = g.call("gridfinity_photos", {})
    assert [p["photo"] for p in listed["photos"]] == ["new.JPG", "mid.heic", "old.png"]
    assert listed["photos"][0]["size_kb"] == 3 and images == []
    assert fake.requests == []  # listing never reaches Tracefinity


def test_a_photo_is_named_by_a_plain_file_in_the_folder(fake, home):
    g = connector(fake, home)
    photo(home, "ok.jpg")
    (home / "outside.jpg").write_bytes(PHOTO)
    for bad in ("../outside.jpg", "..\\outside.jpg", "C:outside.jpg", "/etc/passwd", "", 7):
        with pytest.raises(BadArguments, match="file name from gridfinity_photos"):
            g.call("gridfinity_trace", {"photo": bad, "paper": "a4"})
    with pytest.raises(Refused, match="no photo 'missing.jpg'"):
        g.call("gridfinity_trace", {"photo": "missing.jpg", "paper": "a4"})
    (home / "Pictures" / "Gridfinity" / "readme.txt").write_text("x")
    with pytest.raises(Refused, match="not a photo Tracefinity reads"):
        g.call("gridfinity_trace", {"photo": "readme.txt", "paper": "a4"})
    with pytest.raises(BadArguments, match="paper is one of"):
        g.call("gridfinity_trace", {"photo": "ok.jpg", "paper": "b5"})
    assert fake.requests == []


# --------------------------------------------------------------------------- tracing
def test_a_trace_sends_the_photo_under_a_name_of_its_own_and_numbers_left_to_right(fake, home):
    g = connector(fake, home)
    fake.warnings = ["the photo was taken at an angle"]
    data, images = g.call("gridfinity_trace", {"photo": photo(home, "Dad's drawer.jpg"), "paper": "letter"})
    method, path, body, headers = fake.requests[0]
    assert (method, path) == ("POST", "/api/upload")
    assert b'filename="photo.jpg"' in body and b"Content-Type: image/jpeg" in body and PHOTO in body
    assert b"Dad" not in body
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=solidseas-")
    assert fake.calls("POST", r"/api/sessions/[^/]+/corners") == [
        {"corners": CORNERS, "paper_size": "letter"}
    ]
    disc, bar = data["outlines"]
    assert (disc["outline"], bar["outline"]) == (1, 2)  # the disc is further left
    assert disc["length_mm"] == pytest.approx(22, abs=0.2) and disc["width_mm"] == pytest.approx(22, abs=0.2)
    assert (bar["length_mm"], bar["width_mm"], bar["area_mm2"]) == (176.0, 36.0, 6336)
    assert data["photo_warnings"] == ["the photo was taken at an angle"]
    assert data["edit"] == f"{fake.url}/trace/{data['trace']}"
    (drawing,) = images
    width, height = png_size(drawing)
    assert height > width  # the bar stands upright, as on the paper


def test_a_trace_without_the_papers_corners_says_how_to_take_the_photo(fake, home):
    fake.corners = None
    with pytest.raises(Refused, match="did not find the paper's four corners") as caught:
        traced(connector(fake, home), home)
    assert "/trace/" in str(caught.value)
    fake.corners = CORNERS
    fake.polygons = []
    with pytest.raises(Refused, match="No tools were found"):
        traced(connector(fake, home), home)


# --------------------------------------------------------------------------- the library
def test_saving_names_the_tools_and_gives_each_a_scoop_unless_asked_not_to(fake, home):
    g = connector(fake, home)
    trace = traced(g, home)["trace"]
    data, images = g.call(
        "gridfinity_save_tools",
        {
            "trace": trace,
            "tools": [
                {"outline": 2, "name": "  10 mm\twrench  "},
                {"outline": 1, "name": "socket", "finger_scoop": False},
            ],
        },
    )
    assert images == []
    wrench, socket_ = data["tools"]
    assert (wrench["name"], wrench["outline"], wrench["finger_scoop"]) == ("10 mm wrench", 2, True)
    assert (socket_["name"], socket_["finger_scoop"]) == ("socket", False)
    assert (wrench["length_mm"], wrench["width_mm"]) == (176.0, 36.0)
    (hole,) = fake.tools[wrench["tool"]]["finger_holes"]
    assert hole["id"].startswith(SCOOP_ID) and hole["shape"] == "circle"
    # 36 mm wide: too wide for a scoop across it, so one over a long edge, at mid-length
    assert (abs(hole["x"]), hole["y"], hole["radius"]) == (18.0, pytest.approx(0, abs=1e-6), 12.0)
    assert fake.tools[socket_["tool"]]["finger_holes"] == []
    assert fake.tools[socket_["tool"]]["name"] == "socket"
    with pytest.raises(Refused, match="already saved"):
        g.call("gridfinity_save_tools", {"trace": trace, "tools": [{"outline": 1, "name": "again"}]})
    for bad in ([{"outline": 3, "name": "x"}], [{"outline": 1, "name": " "}], [{"outline": 1}], []):
        with pytest.raises(BadArguments):
            g.call("gridfinity_save_tools", {"trace": trace, "tools": bad})


def test_outlines_changed_in_tracefinity_after_the_trace_are_not_saved_by_number(fake, home):
    g = connector(fake, home)
    trace = traced(g, home)["trace"]
    fake.sessions[trace]["polygons"].pop()
    with pytest.raises(Refused, match="changed since it was traced"):
        g.call("gridfinity_save_tools", {"trace": trace, "tools": [{"outline": 1, "name": "x"}]})
    later = connector(fake, home)  # a new server knows the trace only from Tracefinity
    saved, _ = later.call("gridfinity_save_tools", {"trace": trace, "tools": [{"outline": 1, "name": "x"}]})
    assert len(saved["tools"]) == 1


def test_editing_a_tool_renames_it_and_adds_or_takes_off_only_its_own_scoop(fake, home):
    g = connector(fake, home)
    trace = traced(g, home)["trace"]
    (tool,) = g.call("gridfinity_save_tools", {"trace": trace, "tools": [{"outline": 2, "name": "wrench"}]})[
        0
    ]["tools"]
    tool_id = tool["tool"]
    theirs = {"id": "hole-from-the-editor", "x": 5, "y": 50, "radius": 9, "shape": "circle"}
    fake.tools[tool_id]["finger_holes"].append(theirs)
    off, _ = g.call("gridfinity_edit_tool", {"tool": tool_id, "finger_scoop": False, "name": "big wrench"})
    assert off == {"tool": tool_id, "name": "big wrench", "finger_scoop": False, "changed": True}
    assert fake.tools[tool_id]["finger_holes"] == [theirs]
    on, _ = g.call("gridfinity_edit_tool", {"tool": tool_id, "finger_scoop": True})
    assert on["finger_scoop"] is True and len(fake.tools[tool_id]["finger_holes"]) == 2
    again, _ = g.call("gridfinity_edit_tool", {"tool": tool_id, "finger_scoop": True})
    assert again["changed"] is False and len(fake.tools[tool_id]["finger_holes"]) == 2
    with pytest.raises(BadArguments, match="give a new name"):
        g.call("gridfinity_edit_tool", {"tool": tool_id})
    listed, _ = g.call("gridfinity_tools", {})
    assert listed["tools"] == [{"tool": tool_id, "name": "big wrench", "length_mm": 176.0, "width_mm": 36.0}]


# --------------------------------------------------------------------------- bins
def saved_pair(g: Gridfinity, home) -> tuple[str, str]:
    trace = traced(g, home)["trace"]
    tools = g.call(
        "gridfinity_save_tools",
        {"trace": trace, "tools": [{"outline": 1, "name": "socket"}, {"outline": 2, "name": "wrench"}]},
    )[0]["tools"]
    return tools[1]["tool"], tools[0]["tool"]


def rebuilt(library: list[dict], placed: list[dict], rotation: float) -> list[tuple[float, float]]:
    """Tracefinity 0.10's ``sync_placed_tools`` for one outline: the library points turned
    about their mean, which lands on the placed points' mean."""
    lx = sum(p["x"] for p in library) / len(library)
    ly = sum(p["y"] for p in library) / len(library)
    px = sum(p["x"] for p in placed) / len(placed)
    py = sum(p["y"] for p in placed) / len(placed)
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    return [
        (px + (p["x"] - lx) * c - (p["y"] - ly) * s, py + (p["x"] - lx) * s + (p["y"] - ly) * c)
        for p in library
    ]


def test_a_bin_is_laid_out_made_and_saved_without_writing_over_a_file(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    bins = home / "Documents" / "Gridfinity bins"
    bins.mkdir(parents=True)
    (bins / "tray 6x2x3.stl").write_bytes(b"the person's own")
    data, images = g.call(
        "gridfinity_make_bin",
        {"tools": [{"tool": wrench}, {"tool": socket_, "depth_mm": 14}], "depth_mm": 10, "name": "tray"},
    )
    # side by side: with its edge scoop and clearance the wrench needs 50 mm, so two units deep
    assert (data["grid"], data["height_units"], data["pocket_depth_mm"]) == ([6.0, 2.0], 3, 10.0)
    assert data["outside_mm"] == [251.5, 83.5, 21.0]
    assert (
        data["files"] == ["tray 6x2x3 (2).stl"]
        and (bins / "tray 6x2x3.stl").read_bytes() == b"the person's own"
    )
    assert (bins / "tray 6x2x3 (2).stl").read_bytes() == f"bin.stl of {data['bin']}".encode()
    assert data["folder"] == os.path.join("%USERPROFILE%", "Documents", "Gridfinity bins")
    assert data["edit"] == f"{fake.url}/bins/{data['bin']}"
    (made,) = fake.bins.values()
    config = made["bin_config"]
    assert (config["grid_x"], config["grid_y"], config["height_units"], config["cutout_depth"]) == (
        6.0,
        2.0,
        3,
        10.0,
    )
    assert config["partial_bins_values"] == [True] * 12 and config["magnets"] is True
    assert fake.calls("POST", r"/api/bins")[0]["tool_ids"] == []
    placed = made["placed_tools"]
    assert [p["tool_id"] for p in placed] == [wrench, socket_]
    assert [p["depth_override"] for p in placed] == [None, 14.0]
    for p in placed:
        library = fake.tools[p["tool_id"]]
        again = rebuilt(library["points"], p["points"], p["rotation"])
        assert (
            max(abs(a - q["x"]) + abs(b - q["y"]) for (a, b), q in zip(again, p["points"], strict=True))
            < 1e-3
        )
        (hole,) = p["finger_holes"]
        assert hole["id"] == library["finger_holes"][0]["id"]
    inside = layout.BIN_GAP / 2 + layout.inset(True)
    boxes = []
    for p in placed:
        xs, ys = [q["x"] for q in p["points"]], [q["y"] for q in p["points"]]
        boxes.append((min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1))  # with the clearance
        assert inside - 1e-6 <= boxes[-1][0] and boxes[-1][2] <= 6 * 42 - inside + 1e-6
        assert inside - 1e-6 <= boxes[-1][1] and boxes[-1][3] <= 2 * 42 - inside + 1e-6
    a, b = boxes
    assert (
        a[3] + 3 <= b[1] + 1e-6
        or b[3] + 3 <= a[1] + 1e-6
        or a[2] + 3 <= b[0] + 1e-6
        or b[2] + 3 <= a[0] + 1e-6
    )
    (drawing,) = images
    assert png_size(drawing)[0] > png_size(drawing)[1]  # six units across, two deep


def test_a_bin_split_for_the_bed_comes_with_its_parts(fake, home):
    g = connector(fake, home)
    wrench, _ = saved_pair(g, home)
    fake.split = 2
    bins = home / "Documents" / "Gridfinity bins"
    bins.mkdir(parents=True)
    (bins / "wrench 5x2x3 parts.zip").write_bytes(b"an older bin's parts")
    data, _ = g.call("gridfinity_make_bin", {"tools": [{"tool": wrench}], "depth_mm": 8, "bed_mm": 150})
    assert data["split_into"] == 2
    # one name for the bin's files, free for all of them
    assert data["files"] == ["wrench 5x2x3 (2).stl", "wrench 5x2x3 (2) parts.zip"]
    assert not (bins / "wrench 5x2x3.stl").exists()
    assert (bins / "wrench 5x2x3 parts.zip").read_bytes() == b"an older bin's parts"
    assert next(iter(fake.bins.values()))["bin_config"]["bed_size"] == 150.0


def test_a_bin_that_cannot_hold_the_tools_says_what_would(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    with pytest.raises(Refused, match=r"do not fit in a 2 x 2 bin\. The smallest bin they fit is 6 x 2"):
        g.call(
            "gridfinity_make_bin",
            {"tools": [{"tool": wrench}, {"tool": socket_}], "depth_mm": 10, "grid": [2, 2]},
        )
    with pytest.raises(Refused, match="holds pockets up to 7.25 mm deep; 10 mm needs 3 units"):
        g.call("gridfinity_make_bin", {"tools": [{"tool": wrench}], "depth_mm": 10, "height_units": 2})
    for bad in (
        {"depth_mm": 10, "grid": [2.5, 2]},
        {"depth_mm": 1},
        {"depth_mm": 10, "bed_mm": 50},
        {"depth_mm": 10, "magnets": "yes"},
        {"depth_mm": 10, "colour": "red"},
    ):
        with pytest.raises(BadArguments):
            g.call("gridfinity_make_bin", {"tools": [{"tool": wrench}], **bad})
    assert fake.bins == {}


def label_box(tl: dict) -> list[tuple[float, float]]:
    """The corners of the room a label sent to Tracefinity takes, at the widest its fonts draw."""
    cap = tl["font_size"] * labels.CAP_RATIO
    w, h = labels.width(tl["text"], cap), labels.line(cap)
    c, s = math.cos(math.radians(tl["rotation"])), math.sin(math.radians(tl["rotation"]))
    return [
        (tl["x"] + x * c - y * s, tl["y"] + x * s + y * c)
        for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    ]


def inside(point: tuple[float, float], ring: list[dict]) -> bool:
    x, y, hit = point[0], point[1], False
    for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
        if (a["y"] > y) != (b["y"] > y) and x < (b["x"] - a["x"]) * (y - a["y"]) / (b["y"] - a["y"]) + a["x"]:
            hit = not hit
    return hit


def edge_points(corners: list[tuple[float, float]], n: int = 20) -> list[tuple[float, float]]:
    return [
        (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
        for a, b in zip(corners, corners[1:] + corners[:1], strict=True)
        for k in range(n)
    ]


def test_a_lip_label_says_the_tools_name_along_the_back_edge_clear_of_the_pockets(fake, home):
    g = connector(fake, home)
    wrench, _ = saved_pair(g, home)
    data, images = g.call("gridfinity_make_bin", {"tools": [{"tool": wrench}], "depth_mm": 8, "label": {}})
    assert data["label"] == {
        "placement": "lip",
        "style": "deboss",
        "depth_mm": 0.6,
        "text": "wrench",
        "height_mm": 6.0,
    }
    assert data["grid"] == [5.0, 2.0]  # the strip for the label still fits in the bin without one
    (made,) = fake.bins.values()
    (tl,) = made["text_labels"]
    assert (tl["text"], tl["emboss"], tl["depth"], tl["rotation"]) == ("wrench", False, 0.6, 0.0)
    assert tl["font_size"] * labels.CAP_RATIO == pytest.approx(6.0, abs=1e-3)
    # inside the lip, by the margin, and in front of no pocket
    edge = layout.BIN_GAP / 2 + layout.inset(True)
    corners = label_box(tl)
    xs, ys = [x for x, _ in corners], [y for _, y in corners]
    assert edge + labels.MARGIN - 1e-6 <= min(xs) and max(xs) <= 5 * 42 - edge - labels.MARGIN + 1e-6
    assert edge + labels.MARGIN - 1e-6 <= min(ys)
    (p,) = made["placed_tools"]
    front = min([q["y"] for q in p["points"]] + [h["y"] - h["radius"] for h in p["finger_holes"]]) - 1.0
    assert max(ys) + labels.MARGIN <= front + 1e-6
    # Tracefinity makes a 3MF for a bin with a label, the letters a body of their own
    assert data["files"] == ["wrench 5x2x3.stl", "wrench 5x2x3.3mf"]
    assert (home / "Documents" / "Gridfinity bins" / "wrench 5x2x3.3mf").read_bytes().startswith(b"bin.3mf")
    assert png_size(images[0])[0] > png_size(images[0])[1]

    # emboss raises the letters instead; on a stacking bin the chat is told what that costs
    data, _ = g.call(
        "gridfinity_make_bin",
        {
            "tools": [{"tool": wrench}],
            "depth_mm": 8,
            "label": {"text": "Sockets", "style": "emboss", "depth_mm": 1},
        },
    )
    raised = fake.bins[data["bin"]]["text_labels"][0]
    assert (raised["text"], raised["emboss"], raised["depth"]) == ("Sockets", True, 1.0)
    assert "sitting flat" in data["label"]["note"]


def test_a_label_too_long_for_the_bin_is_made_smaller_then_refused(fake, home):
    g = connector(fake, home)
    wrench, _ = saved_pair(g, home)
    room = layout.interior(5, layout.inset(True)) - 2 * labels.MARGIN
    long = "W" * 27
    assert labels.width(long, 6.0) > room >= labels.width(long, 5.0)
    data, _ = g.call(
        "gridfinity_make_bin", {"tools": [{"tool": wrench}], "depth_mm": 8, "label": {"text": long}}
    )
    assert (data["label"]["height_mm"], data["label"]["made_smaller"]) == (5.0, "from 6 mm, to fit")
    (tl,) = fake.bins[data["bin"]]["text_labels"]
    xs = [x for x, _ in label_box(tl)]
    assert max(xs) - min(xs) <= room + 1e-6
    count = len(fake.bins)
    longer = {"tools": [{"tool": wrench}], "depth_mm": 8, "label": {"text": "W" * 40}}
    with pytest.raises(Refused, match=r"too long for a bin 5 units across: at the smallest size, 4 mm tall"):
        g.call("gridfinity_make_bin", {**longer, "grid": [5, 2]})
    assert len(fake.bins) == count
    # with no grid given the bin is made as much wider as the label needs, at the size taking fewest cells
    data, _ = g.call("gridfinity_make_bin", longer)
    assert (data["grid"], data["label"]["height_mm"]) == ([6.0, 2.0], 4.0)
    count += 1
    # a grid with no room for the strip says so
    with pytest.raises(Refused, match=r"strip along its back edge"):
        g.call(
            "gridfinity_make_bin",
            {"tools": [{"tool": wrench}], "depth_mm": 8, "grid": [5, 1.5], "half_grid": True, "label": {}},
        )
    assert len(fake.bins) == count


def test_floor_labels_name_each_tool_in_its_pocket_where_there_is_room(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    data, _ = g.call(
        "gridfinity_make_bin",
        {
            "tools": [{"tool": wrench}, {"tool": socket_}],
            "depth_mm": 10,
            "label": {"placement": "floor", "style": "emboss", "height_mm": 8},
        },
    )
    # the 22 mm socket's scoop covers it, so only the wrench is labelled
    assert data["label"]["pockets"] == [{"number": 1, "text": "wrench", "height_mm": 8.0}]
    assert [u["number"] for u in data["label"]["unlabelled"]] == [2]
    made = fake.bins[data["bin"]]
    (tl,) = made["text_labels"]
    assert (tl["text"], tl["emboss"]) == ("wrench", True)
    pocket = made["placed_tools"][0]
    assert abs(tl["rotation"]) < 1e-6  # along the wrench, which lies across the bin
    corners = label_box(tl)
    for point in edge_points(corners):
        assert inside(point, pocket["points"])
        for hole in pocket["finger_holes"]:
            assert math.hypot(point[0] - hole["x"], point[1] - hole["y"]) >= hole["radius"] - 1e-6

    with pytest.raises(BadArguments, match="floor label names each tool"):
        g.call(
            "gridfinity_make_bin",
            {
                "tools": [{"tool": wrench}, {"tool": socket_}],
                "depth_mm": 10,
                "label": {"placement": "floor", "text": "tray"},
            },
        )
    # Tracefinity puts every floor label at the bin's pocket depth, so a deeper pocket gets none
    with pytest.raises(
        Refused, match=r"No pocket has room for a floor label: tool 1: its pocket is 14 mm deep"
    ):
        g.call(
            "gridfinity_make_bin",
            {
                "tools": [{"tool": wrench, "depth_mm": 14}, {"tool": socket_}],
                "depth_mm": 10,
                "label": {"placement": "floor"},
            },
        )


def test_label_arguments_are_checked(fake, home):
    g = connector(fake, home)
    wrench, _ = saved_pair(g, home)
    for bad in (
        "wrench",
        {"text": 5},
        {"text": "日本"},
        {"text": "x" * 41},
        {"placement": "side"},
        {"style": "engrave"},
        {"height_mm": 3},
        {"depth_mm": 2},
        {"font": "Arial"},
    ):
        with pytest.raises(BadArguments):
            g.call("gridfinity_make_bin", {"tools": [{"tool": wrench}], "depth_mm": 8, "label": bad})
    assert fake.bins == {}
    assert labels.clean("  Café   crème\t10 mm ") == "Cafe creme 10 mm"


# --------------------------------------------------------------------------- laying a bin out with the chat
def made_files(home) -> list[str]:
    folder = home / "Documents" / "Gridfinity bins"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def entries(reply: dict, **changed: dict) -> list[dict]:
    """The tools of a layout's reply as a chat gives them back to place them by hand: every
    tool's centre_mm and turned_deg, with ``changed`` (by name) put in."""
    out = []
    for t in reply["tools"]:
        entry = {"tool": t["tool"], "centre_mm": t["centre_mm"], "turned_deg": t["turned_deg"]}
        out.append({**entry, **changed.get(t["name"], {})})
    return out


def test_a_preview_lays_the_bin_out_as_making_it_would_and_makes_nothing(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    args = {"tools": [{"tool": wrench}, {"tool": socket_}], "depth_mm": 10, "name": "tray"}
    preview, images = g.call("gridfinity_preview_bin", args)
    assert fake.bins == {} and made_files(home) == [], "nothing is made or saved"
    assert fake.calls("POST", r"/api/bins.*") == [] and fake.calls("PUT", r"/api/bins/.*") == []
    assert (preview["grid"], preview["height_units"], preview["placed"]) == ([6.0, 2.0], 3, "automatically")
    edge = round(layout.BIN_GAP / 2 + layout.inset(True), 2)
    assert preview["room_mm"] == [edge, edge, round(6 * 42 - edge, 2), round(2 * 42 - edge, 2)]
    first, second = preview["tools"]
    assert (first["number"], first["name"], second["name"]) == (1, "wrench", "socket")
    for t in preview["tools"]:
        x0, y0, x1, y1 = t["pocket_mm"]
        assert x0 < t["centre_mm"][0] < x1 and y0 < t["centre_mm"][1] < y1
        assert all(round(v, 2) == v for v in [*t["centre_mm"], *t["pocket_mm"], t["turned_deg"]])
    assert "turned_deg" in preview["next"] and "gridfinity_make_bin" in preview["next"]
    (drawing,) = images
    assert png_size(drawing)[0] > png_size(drawing)[1]
    made, made_images = g.call("gridfinity_make_bin", args)
    assert made["bin"] in fake.bins and made["files"] == ["tray 6x2x3.stl"]
    for key in ("grid", "height_units", "tools", "room_mm", "placed"):
        assert made[key] == preview[key], key
    assert made_images == images, "the same arguments draw the same bin"


def test_turning_a_tool_from_the_chat_keeps_it_turned(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    args = {"tools": [{"tool": wrench}, {"tool": socket_}], "depth_mm": 10}
    before, _ = g.call("gridfinity_preview_bin", args)
    turned = before["tools"][0]["turned_deg"] + 90  # "turn the wrench 90 degrees"
    after, _ = g.call(
        "gridfinity_preview_bin",
        {**args, "tools": [{"tool": wrench, "turned_deg": turned}, {"tool": socket_}]},
    )
    assert after["tools"][0]["turned_deg"] == pytest.approx(layout.normal_turn(turned))
    x0, y0, x1, y1 = after["tools"][0]["pocket_mm"]
    assert y1 - y0 > x1 - x0, "the wrench now lies along the bin's depth"
    assert after["grid"][1] >= 5
    made, _ = g.call(
        "gridfinity_make_bin", {**args, "tools": [{"tool": wrench, "turned_deg": turned}, {"tool": socket_}]}
    )
    (placed_wrench, _) = fake.bins[made["bin"]]["placed_tools"]
    assert placed_wrench["rotation"] == pytest.approx(layout.normal_turn(turned))


def test_tools_placed_by_hand_from_the_chat_go_where_it_says(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    args = {"tools": [{"tool": wrench}, {"tool": socket_}], "depth_mm": 10, "name": "tray"}
    packed, _ = g.call("gridfinity_preview_bin", args)
    w, s = packed["tools"]
    left = packed["room_mm"][0]
    # "put the socket on the left": the socket's pocket at the left of the room, the wrench 3 mm after it
    ds = left - s["pocket_mm"][0]
    dw = s["pocket_mm"][2] + ds + 3.0 - w["pocket_mm"][0]
    socket_at = [round(s["centre_mm"][0] + ds, 2), s["centre_mm"][1]]
    wrench_at = [round(w["centre_mm"][0] + dw, 2), w["centre_mm"][1]]
    by_hand = {
        **args,
        "tools": entries(packed, wrench={"centre_mm": wrench_at}, socket={"centre_mm": socket_at}),
    }
    preview, _ = g.call("gridfinity_preview_bin", by_hand)
    assert preview["placed"] == "by hand" and preview["grid"] == packed["grid"]
    assert [t["centre_mm"] for t in preview["tools"]] == [wrench_at, socket_at]
    assert preview["tools"][1]["pocket_mm"][2] < preview["tools"][0]["pocket_mm"][0], (
        "the socket is on the left"
    )
    assert fake.bins == {}
    made, _ = g.call("gridfinity_make_bin", by_hand)
    assert made["placed"] == "by hand" and made["files"] == ["tray 6x2x3.stl"]
    placed = fake.bins[made["bin"]]["placed_tools"]
    for p, at in zip(placed, (wrench_at, socket_at), strict=True):
        library = fake.tools[p["tool_id"]]
        mx = sum(q["x"] for q in p["points"]) / len(p["points"])
        my = sum(q["y"] for q in p["points"]) / len(p["points"])
        assert (mx, my) == (pytest.approx(at[0], abs=1e-3), pytest.approx(at[1], abs=1e-3))
        again = rebuilt(library["points"], p["points"], p["rotation"])  # as Tracefinity's editor rebuilds it
        assert (
            max(abs(a - q["x"]) + abs(b - q["y"]) for (a, b), q in zip(again, p["points"], strict=True))
            < 1e-3
        )
    # the packed layout's own numbers, given back by hand, make the same bin
    same, _ = g.call("gridfinity_preview_bin", {**args, "tools": entries(packed)})
    assert same["grid"] == packed["grid"]
    for a, b in zip(same["tools"], packed["tools"], strict=True):
        assert a["pocket_mm"] == pytest.approx(b["pocket_mm"], abs=0.02)


def test_a_layout_by_hand_that_does_not_fit_says_why_and_makes_nothing(fake, home):
    g = connector(fake, home)
    wrench, socket_ = saved_pair(g, home)
    args = {"tools": [{"tool": wrench}, {"tool": socket_}], "depth_mm": 10}
    packed, _ = g.call("gridfinity_preview_bin", args)
    w, s = packed["tools"]
    on_top = entries(packed, socket={"centre_mm": w["centre_mm"]})
    for tool in ("gridfinity_preview_bin", "gridfinity_make_bin"):
        with pytest.raises(Refused, match=r"pockets of tool 1 \(wrench\) and tool 2 \(socket\) overlap"):
            g.call(tool, {**args, "tools": on_top})
    off = entries(packed, socket={"centre_mm": [5.0, s["centre_mm"][1]]})
    with pytest.raises(Refused, match=r"tool 2 \(socket\) reaches .* past the left edge"):
        g.call("gridfinity_make_bin", {**args, "tools": off})
    with pytest.raises(Refused, match=r"past the right edge .* in a 4 x 2 bin"):
        g.call("gridfinity_make_bin", {**args, "tools": entries(packed), "grid": [4, 2]})
    assert fake.bins == {} and made_files(home) == []
    one_only = [{"tool": wrench, "centre_mm": w["centre_mm"], "turned_deg": 0}, {"tool": socket_}]
    no_turn = [
        {"tool": wrench, "centre_mm": w["centre_mm"]},
        {"tool": socket_, "centre_mm": s["centre_mm"], "turned_deg": 0},
    ]
    for bad in (
        one_only,
        no_turn,
        [{"tool": wrench, "turned_deg": 400}],
        [{"tool": wrench, "turned_deg": "90"}],
        [{"tool": wrench, "turned_deg": True}],
        *(
            [{"tool": wrench, "turned_deg": 0, "centre_mm": centre}]
            for centre in (
                "100,40",
                [100],
                [100, 40, 3],
                [-1, 40],
                [100, 1e9],
                [True, 40],
                [100, float("nan")],
            )
        ),
    ):
        with pytest.raises(BadArguments):
            g.call("gridfinity_preview_bin", {**args, "tools": bad})
    assert fake.bins == {}


def test_a_lip_label_on_a_layout_by_hand_says_how_far_to_move_the_pockets(fake, home):
    g = connector(fake, home)
    wrench, _ = saved_pair(g, home)
    args = {"tools": [{"tool": wrench}], "depth_mm": 8, "label": {}}
    packed, _ = g.call("gridfinity_preview_bin", args)  # the packing keeps a strip free for the label
    (w,) = packed["tools"]
    room_back = packed["room_mm"][1]
    pushed_back = [w["centre_mm"][0], round(w["centre_mm"][1] - (w["pocket_mm"][1] - room_back), 2)]
    need = f"{labels.band(labels.MIN_CAP):.1f}"  # the strip for the smallest letters
    with pytest.raises(Refused, match=rf"they leave 0\.0 mm: move the pockets at least {need} mm forward"):
        g.call(
            "gridfinity_preview_bin", {**args, "tools": entries(packed, wrench={"centre_mm": pushed_back})}
        )
    # as the packing left it, by hand, there is room: the label goes in front of the lip
    kept, _ = g.call("gridfinity_preview_bin", {**args, "tools": entries(packed)})
    assert kept["label"]["text"] == "wrench" and kept["label"]["height_mm"] == packed["label"]["height_mm"]
    # a floor label goes in its pocket wherever the pocket is
    floor, _ = g.call(
        "gridfinity_preview_bin",
        {
            **args,
            "label": {"placement": "floor"},
            "tools": entries(packed, wrench={"centre_mm": pushed_back}),
        },
    )
    assert floor["label"]["pockets"][0]["text"] == "wrench"


def test_the_layout_keeps_a_strip_along_the_back_edge_when_asked():
    bar = layout.Shape(((-70, -15), (70, -15), (70, 15), (-70, 15)))
    plain = layout.lay_out([bar], clearance=1, gap=3, stacking_lip=True)
    kept = layout.lay_out([bar], clearance=1, gap=3, stacking_lip=True, reserve=4)
    edge = layout.BIN_GAP / 2 + layout.inset(True)
    assert plain.grid == kept.grid == (4.0, 1.0)
    (p,) = kept.placements
    assert p.box[1] >= edge + 4 - 1e-6 and p.box[3] <= 42 - edge + 1e-6
    # a wider strip turns the bar along the depth, unless the bin must be wide for the label
    assert layout.lay_out([bar], clearance=1, gap=3, stacking_lip=True, reserve=12).grid == (1.0, 4.0)
    wide = layout.lay_out([bar], clearance=1, gap=3, stacking_lip=True, reserve=12, min_across=4)
    assert wide.grid == (4.0, 2.0) and wide.placements[0].box[1] >= edge + 12 - 1e-6
    with pytest.raises(layout.LayoutError):
        layout.lay_out([bar], clearance=1, gap=3, stacking_lip=True, grid=(4, 1), reserve=12)
    assert labels.sizes(6) == [6, 5.5, 5.0, 4.5, 4.0] and labels.sizes(4.2) == [4.2, 4.0]


def test_file_names_from_the_chat_stay_names():
    assert safe_file_name("tray 5x2x3") == "tray 5x2x3"
    assert safe_file_name("..\\..\\Windows\\evil") == "Windows evil"
    assert safe_file_name('a/b:c*d?e"f<g>h|i') == "a b c d e f g h i"
    assert safe_file_name("CON") == "bin CON" and safe_file_name("nul.stl") == "bin nul.stl"
    assert safe_file_name(" ... ") == "bin"
    assert len(safe_file_name("x" * 500)) == gridfinity.MAX_NAME


# --------------------------------------------------------------------------- the layout
def test_the_long_side_is_turned_along_x():
    w, h = 40.0, 10.0
    for angle in (0.0, 17.0, 63.0, 90.0, -30.0):
        rect = layout.turn([(0, 0), (w, 0), (w, h), (0, h)], angle)
        turned = layout.turn(rect, layout.long_side_angle(rect))
        x0, y0, x1, y1 = layout.extent(turned)
        assert (x1 - x0, y1 - y0) == (pytest.approx(w), pytest.approx(h))
    assert layout.size([(0, 0), (3, 0), (3, 4), (0, 4)]) == (pytest.approx(4.0), pytest.approx(3.0))


def test_a_scoop_goes_across_a_narrow_tool_and_over_the_edge_of_a_wide_one():
    bar = [(-88, -12), (88, -12), (88, 12), (-88, 12)]
    across = layout.finger_scoop(bar)
    assert (across.x, across.y, across.radius) == (0, 0, 18.0)
    plate = [(-50, -40), (50, -40), (50, 40), (-50, 40)]
    edge = layout.finger_scoop(plate)
    assert (abs(edge.x), abs(edge.y), edge.radius) == (0, 40, layout.EDGE_SCOOP)
    tiny = layout.finger_scoop([(-3, -2), (3, -2), (3, 2), (-3, 2)])
    assert tiny.radius == layout.SCOOP_MIN


def test_the_layout_keeps_the_smallest_bin_with_the_pockets_apart_and_inside():
    def rect(w, h):
        return layout.Shape(((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)))

    shapes = [rect(150, 20), rect(30, 30), rect(30, 30), rect(60, 15), rect(15, 90)]
    for lip in (True, False):
        result = layout.lay_out(shapes, clearance=1.0, gap=3.0, stacking_lip=lip)
        across, deep = result.grid
        edge = layout.BIN_GAP / 2 + layout.inset(lip)
        boxes = [p.box for p in result.placements]
        for x0, y0, x1, y1 in boxes:
            assert edge - 1e-6 <= x0 and x1 <= across * 42 - edge + 1e-6
            assert edge - 1e-6 <= y0 and y1 <= deep * 42 - edge + 1e-6
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                apart = max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])
                assert apart >= 3.0 - 1e-6, (a, b)
        smaller = [
            (x, y)
            for x in range(1, int(across) + 1)
            for y in range(1, int(deep) + 1)
            if x * y < across * deep
        ]
        for x, y in smaller:
            with pytest.raises(layout.LayoutError):
                layout.lay_out(shapes, clearance=1.0, gap=3.0, stacking_lip=lip, grid=(x, y))
    half = layout.lay_out([rect(50, 20)], clearance=1.0, gap=3.0, stacking_lip=True, half=True)
    assert half.grid == (1.5, 1.0)


def test_heights_and_widths_follow_tracefinitys_numbers():
    assert layout.height_units_for(20) == 4 and layout.max_depth(4) == pytest.approx(21.25)
    assert layout.height_units_for(21.25) == 4 and layout.height_units_for(21.26) == 5
    assert layout.height_units_for(3) == 2
    assert layout.units_for(36.3, layout.inset(True), False) == 1.0
    assert layout.units_for(36.31, layout.inset(True), False) == 2.0
    assert layout.units_for(57.3, layout.inset(True), True) == 1.5


def test_too_many_tools_for_any_bin_are_refused():
    big = layout.Shape(((0, 0), (1500, 0), (1500, 10), (0, 10)))
    with pytest.raises(layout.LayoutError, match="do not fit in any bin"):
        layout.lay_out([big], clearance=1, gap=3, stacking_lip=True)


# --------------------------------------------------------------------------- placing by hand
def rect_shape(w: float, h: float, holes=()) -> layout.Shape:
    return layout.Shape(((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)), tuple(holes))


EDGE = layout.BIN_GAP / 2 + layout.inset(True)  # where the room for pockets starts, with a stacking lip
HAND = {"clearance": 1.0, "gap": 3.0, "stacking_lip": True}


def test_a_turn_the_person_asks_for_is_kept_by_the_packing():
    bar = rect_shape(140, 30)
    (along,) = layout.lay_out([bar], **HAND).placements
    assert along.rotation == 0 and along.box[2] - along.box[0] == pytest.approx(142)
    turned = layout.lay_out([bar], turns=[90.0], **HAND)
    (p,) = turned.placements
    assert p.rotation == 90.0 and p.box[3] - p.box[1] == pytest.approx(142), "the bar lies along the depth"
    assert turned.grid == (1.0, 4.0)
    assert layout.lay_out([bar, bar], turns=[None, 30.0], **HAND).placements[1].rotation == 30.0
    assert layout.normal_turn(270) == -90 and layout.normal_turn(-180) == 180 and layout.normal_turn(45) == 45


def test_placing_by_hand_puts_each_tool_where_it_is_asked_in_the_smallest_bin_that_holds_it():
    shapes = [rect_shape(100, 20), rect_shape(30, 30)]
    result = layout.place_by_hand(shapes, [(60, 20), (60, 58)], [0.0, 45.0], **HAND)
    first, second = result.placements
    assert first.centre == (60, 20) and first.box == pytest.approx((9, 9, 111, 31))
    assert second.rotation == 45.0 and second.centre == (60, 58)
    half = 15 * math.sqrt(2) + 1  # a 30 mm square turned 45 degrees, and the clearance
    assert second.box == pytest.approx((60 - half, 58 - half, 60 + half, 58 + half), abs=1e-3)
    # pockets reach 111 mm from the left and 80.2 mm from the back: inside the lip of a 3 x 2 bin
    assert result.grid == (3.0, 2.0)
    held = layout.place_by_hand(shapes, [(60, 20), (60, 58)], [0.0, 45.0], grid=(5, 3), **HAND)
    assert held.grid == (5, 3) and held.placements == result.placements
    deeper = layout.place_by_hand(shapes, [(60, 20), (60, 60)], [0.0, 45.0], **HAND)
    assert deeper.grid == (3.0, 3.0), "82.2 mm from the back is past a 2-unit bin's lip"


@pytest.mark.parametrize(
    "centre, grid, message",
    [
        ((50 + 1 + EDGE - 3.2, 40), None, r"tool 1 reaches 3\.2 mm past the left edge .* to the right"),
        ((100, 10 + 1 + EDGE - 0.6), None, r"reaches 0\.6 mm past the back edge .* forward"),
        (
            (42 * 3 - EDGE - 51 + 2.5, 40),
            (3, 2),
            r"2\.5 mm past the right edge .* in a 3 x 2 bin: move it left",
        ),
        ((60, 84 - EDGE - 11 + 7), (3, 2), r"7\.0 mm past the front edge .* give a deeper grid"),
    ],
)
def test_a_pocket_past_the_room_says_which_edge_and_how_far(centre, grid, message):
    with pytest.raises(layout.LayoutError, match=message):
        layout.place_by_hand([rect_shape(100, 20)], [centre], [0.0], grid=grid, **HAND)


def test_pockets_too_near_each_other_say_how_far_apart_they_are():
    shapes = [rect_shape(60, 20), rect_shape(60, 20)]
    named = {"names": ["tool 1 (knife)", "tool 2 (pliers)"]}
    # outlines 4.5 mm apart: the pockets, grown by 1 mm each, are 2.5 mm apart
    with pytest.raises(
        layout.LayoutError, match=r"tool 1 \(knife\) and tool 2 \(pliers\) are 2\.5 mm apart: they need 3"
    ):
        layout.place_by_hand(shapes, [(40, 20), (40, 44.5)], [0.0, 0.0], **HAND, **named)
    with pytest.raises(layout.LayoutError, match="overlap"):
        layout.place_by_hand(shapes, [(40, 20), (60, 25)], [0.0, 0.0], **HAND, **named)
    with pytest.raises(layout.LayoutError, match="overlap"):  # one turned across the other
        layout.place_by_hand(shapes, [(80, 50), (80, 50)], [0.0, 90.0], **HAND, **named)
    fine = layout.place_by_hand(shapes, [(40, 20), (40, 45)], [0.0, 0.0], **HAND, **named)
    assert [p.centre for p in fine.placements] == [(40, 20), (40, 45)]


def test_a_tool_may_sit_in_the_crook_of_another_when_placed_by_hand():
    # an L 120 mm long and 80 mm tall, its arms 20 mm thick, and a 40 mm square in its crook
    ell = layout.Shape(((0, 0), (20, 0), (20, 60), (120, 60), (120, 80), (0, 80)))
    square = rect_shape(40, 40)
    mx, my = layout.mean(ell.points)
    # each pocket reaches 1 mm past its outline, and the two stay 5 mm apart from both arms
    x, y = 20 + 1 + 5 + 1 + 20, 60 - 1 - 5 - 1 - 20
    result = layout.place_by_hand([ell, square], [(mx + 10, my + 10), (x + 10, y + 10)], [0, 0], **HAND)
    a, b = (p.box for p in result.placements)
    assert a[0] < b[0] < b[2] < a[2] and a[1] < b[1] < b[3] < a[3], "the boxes overlap; the pockets do not"
    # the packing keeps the boxes apart, so it never nests them, and needs a bigger bin
    packed = layout.lay_out([ell, square], **HAND)
    assert result.grid == (4.0, 3.0) and packed.grid[0] * packed.grid[1] > 12
    with pytest.raises(layout.LayoutError, match=r"are 2\.0 mm apart"):  # 3 mm nearer the long arm
        layout.place_by_hand([ell, square], [(mx + 10, my + 10), (x + 10, y + 13)], [0, 0], **HAND)


def test_finger_holes_are_part_of_a_pocket_placed_by_hand():
    scooped = rect_shape(60, 20, [layout.Hole(0, 10, 12)])  # a scoop half over its front edge
    plain = rect_shape(60, 20)
    # outlines 14 mm apart, but the scoop reaches 12 mm toward the other: 2 mm, less the clearances
    with pytest.raises(layout.LayoutError, match="overlap"):
        layout.place_by_hand([scooped, plain], [(40, 20), (40, 54)], [0, 0], **HAND)
    clear = layout.place_by_hand([scooped, plain], [(40, 20), (40, 60)], [0, 0], **HAND)
    assert len(clear.placements) == 2


def test_a_packed_layout_copied_back_by_hand_is_the_same_bin():
    """A chat moves one tool by giving every tool's centre_mm and turned_deg as the last
    layout's reply gave them, to 0.01: the others must not then be refused for the rounding."""
    shapes = [
        rect_shape(150, 20),
        rect_shape(30, 30),
        rect_shape(30, 30),
        rect_shape(60, 15),
        rect_shape(15, 90),
    ]
    for lip in (True, False):
        packed = layout.lay_out(shapes, clearance=1.0, gap=3.0, stacking_lip=lip)
        centres = [(round(p.centre[0], 2), round(p.centre[1], 2)) for p in packed.placements]
        turns = [round(p.rotation, 2) for p in packed.placements]
        by_hand = layout.place_by_hand(shapes, centres, turns, clearance=1.0, gap=3.0, stacking_lip=lip)
        assert by_hand.grid == packed.grid
        for a, b in zip(packed.placements, by_hand.placements, strict=True):
            assert a.box == pytest.approx(b.box, abs=0.02)


def test_the_distance_between_outlines():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]

    def moved(points, dx, dy):
        return [(x + dx, y + dy) for x, y in points]

    assert layout.outline_gap(square, moved(square, 15, 0), 50) == pytest.approx(5)
    assert layout.outline_gap(square, moved(square, 13, 14), 50) == pytest.approx(5)  # corner to corner
    assert layout.outline_gap(square, moved(square, 5, 5), 50) == 0  # overlapping
    assert layout.outline_gap(square, [(2, 2), (4, 2), (4, 4)], 50) == 0  # one inside the other
    bar = [(0, 4), (20, 4), (20, 6), (0, 6)]
    cross = [(9, -5), (11, -5), (11, 15), (9, 15)]
    assert layout.outline_gap(bar, cross, 50) == 0  # crossing, no corner inside the other
    assert layout.outline_gap(square, moved(square, 100, 0), 7) == 7  # not measured past the reach


# --------------------------------------------------------------------------- drawings
def test_a_drawing_is_a_png_with_its_shapes_filled():
    canvas = Canvas(40, 30, (255, 255, 255))
    canvas.polygon(
        [[(5, 5), (35, 5), (35, 25), (5, 25)], [(15, 10), (25, 10), (25, 20), (15, 20)]], (0, 0, 0)
    )
    canvas.label((20, 15), "12 mm", ink=(1, 2, 3), paper=(9, 9, 9), scale=1)
    assert png_size(canvas.png()) == (40, 30)
    assert canvas.rows[7][10 * 3 : 10 * 3 + 3] == b"\x00\x00\x00"  # in the ring
    assert canvas.rows[2][2 * 3 : 2 * 3 + 3] == b"\xff\xff\xff"  # outside it
    pil = pytest.importorskip("PIL.Image")
    import io

    assert pil.open(io.BytesIO(canvas.png())).size == (40, 30)


# --------------------------------------------------------------------------- the MCP server
def test_the_mcp_server_serves_the_gridfinity_tools_with_their_drawings(fake, home, policy_reader):
    def no_solidworks():
        raise AssertionError("SOLIDWORKS was reached for a Gridfinity tool")

    server = McpServer(no_solidworks, gridfinity_factory=lambda: connector(fake, home))
    try:
        message = {"name": "gridfinity_trace", "arguments": {"photo": photo(home), "paper": "a4"}}
        reply = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": message})[
            "result"
        ]
        assert reply["isError"] is False
        text, image = reply["content"]
        assert json.loads(text["text"]) == reply["structuredContent"]
        assert image["type"] == "image" and image["mimeType"] == "image/png"
        png_size(base64.b64decode(image["data"]))
        bad = {"name": "gridfinity_trace", "arguments": {"photo": "x.jpg", "paper": "a4", "path": "C:\\"}}
        error = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": bad})["error"]
        assert error["code"] == -32602
        missing = {"name": "gridfinity_trace", "arguments": {"photo": "nope.jpg", "paper": "a4"}}
        refused = server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": missing})[
            "result"
        ]
        assert refused["isError"] is True and "no photo" in refused["content"][0]["text"]
        policy_reader(policy.Policy(local_only=True))
        listed = {"name": "gridfinity_photos", "arguments": {}}
        local = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": listed})["result"]
        assert local["isError"] is True and local["content"][0]["text"] == LOCAL_ONLY
    finally:
        server.close()


def test_a_cancelled_call_stops_waiting_for_tracefinity(fake, home):
    fake.hold.clear()  # the trace waits until released
    server = McpServer(gridfinity_factory=lambda: connector(fake, home))
    result: dict = {}
    message = {"name": "gridfinity_trace", "arguments": {"photo": photo(home), "paper": "a4"}}
    worker = threading.Thread(
        target=lambda: result.update(
            server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": message})
        )
    )
    started = time.monotonic()
    worker.start()
    deadline = time.monotonic() + 10
    while not fake.calls("POST", r"/api/sessions/[^/]+/trace") and time.monotonic() < deadline:
        time.sleep(0.02)
    server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}})
    worker.join(5)
    assert not worker.is_alive() and time.monotonic() - started < 8
    assert result["result"]["isError"] is True
    fake.hold.set()
    server.close()


def test_a_cancel_reaches_the_connector_as_cancelled(fake, home):
    fake.hold.clear()
    cancel = Cancel()
    threading.Timer(0.3, cancel.cancel).start()
    with pytest.raises(CancelledError):
        connector(fake, home).call("gridfinity_trace", {"photo": photo(home), "paper": "a4"}, cancel)
    fake.hold.set()


def test_the_folders_come_from_the_settings_or_the_profile(monkeypatch, tmp_path):
    chosen = tmp_path / "phone"
    monkeypatch.setenv(gridfinity.PHOTOS_ENV, str(chosen))
    assert gridfinity.default_photos() == os.path.normpath(str(chosen))
    monkeypatch.setenv(gridfinity.PHOTOS_ENV, "relative\\folder")
    with pytest.raises(Refused, match="must be a full path"):
        gridfinity.default_photos()
    monkeypatch.delenv(gridfinity.PHOTOS_ENV)
    monkeypatch.delenv(gridfinity.BINS_ENV, raising=False)
    assert os.path.basename(gridfinity.default_photos()) == "Gridfinity"
    assert os.path.basename(gridfinity.default_bins()) == "Gridfinity bins"
    g = Gridfinity(home=str(tmp_path))
    assert g.shown(str(tmp_path / "a" / "b")) == os.path.join("%USERPROFILE%", "a", "b")
    assert g.shown(str(tmp_path.parent / "elsewhere")) == os.path.normpath(str(tmp_path.parent / "elsewhere"))


# --------------------------------------------------------------------------- the SSH tunnel
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def through_ssh(fake: FakeTracefinity, monkeypatch, tmp_path) -> tuple[Tracefinity, SshTunnel]:
    monkeypatch.setenv("FAKE_SSH_TARGET", str(fake.server.server_address[1]))
    monkeypatch.setenv("FAKE_SSH_ARGS", str(tmp_path / "ssh-args.txt"))
    port = free_port()
    way = SshTunnel("root@nas", port, key=str(tmp_path / "tunnel-key"), ssh=FAKE_SSH)
    return Tracefinity(f"http://127.0.0.1:{port}", tunnel=way), way


def test_a_tracefinity_on_a_server_is_reached_through_an_ssh_tunnel(fake, monkeypatch, tmp_path):
    client, way = through_ssh(fake, monkeypatch, tmp_path)
    assert not way.running and not listening(way.port)
    assert client.version() == "0.10.0"  # the first call opens the tunnel
    args = (tmp_path / "ssh-args.txt").read_text(encoding="utf-8").split("\n")
    assert args[-1] == "root@nas" and args[:2] == ["-N", "-T"]
    assert args[args.index("-L") + 1] == f"127.0.0.1:{way.port}:127.0.0.1:{way.port}"
    assert args[args.index("-i") + 1] == str(tmp_path / "tunnel-key")
    for option in (
        "BatchMode=yes",
        "ExitOnForwardFailure=yes",
        "IdentitiesOnly=yes",
        "ServerAliveInterval=30",
    ):
        assert option in args, option
    assert client.page("bins", "b1") == f"http://127.0.0.1:{way.port}/bins/b1"
    first = way._process
    first.kill()  # the PC slept, the network went: the next call opens it again
    first.wait()
    assert closed(way.port)
    assert client.tools() == [] and way.running and way._process is not first
    client.close()
    assert not way.running and closed(way.port)


def test_a_tunnel_that_cannot_sign_in_says_why(monkeypatch):
    monkeypatch.setenv("FAKE_SSH_FAIL", "root@nas: Permission denied (publickey).")
    way = SshTunnel("root@nas", free_port(), ssh=FAKE_SSH)
    with pytest.raises(TracefinityError, match=r"did not open: root@nas: Permission denied \(publickey\)"):
        Tracefinity(f"http://127.0.0.1:{way.port}", tunnel=way).version()
    assert not way.running


def test_a_server_whose_tracefinity_is_down_is_named(fake, monkeypatch, tmp_path):
    client, way = through_ssh(fake, monkeypatch, tmp_path)
    monkeypatch.setenv("FAKE_SSH_TARGET", str(free_port()))  # nothing listens there
    try:
        with pytest.raises(TracefinityError, match="not answering on root@nas through the SSH tunnel"):
            client.version()
    finally:
        client.close()


def test_the_server_is_a_host_never_an_ssh_option():
    for bad in ("-oProxyCommand=calc", "root@-oX", "a b", "root@host;rm", "", "@host", "x" * 300, None):
        with pytest.raises(TunnelError, match="host or user@host"):
            SshTunnel(bad, 3077)
    assert SshTunnel("nas", 3077).command()[-1] == "nas"
    assert "-i" not in SshTunnel("root@nas.local", 3077).command()


def test_the_tunnel_comes_from_the_settings(monkeypatch, tmp_path):
    assert tunnel.from_settings(3077) is None
    monkeypatch.setenv(tunnel.SSH_ENV, "root@nas")
    monkeypatch.setenv(tunnel.KEY_ENV, str(tmp_path / "key"))
    way = tunnel.from_settings(3077)
    assert (way.destination, way.port, way.key) == ("root@nas", 3077, str(tmp_path / "key"))
    assert Tracefinity().tunnel.destination == "root@nas"
    monkeypatch.setenv(tunnel.KEY_ENV, "relative\\key")
    with pytest.raises(TunnelError, match="full path"):
        tunnel.from_settings(3077)
    monkeypatch.setenv(tunnel.SSH_ENV, "-oProxyCommand=calc")
    monkeypatch.delenv(tunnel.KEY_ENV)
    with pytest.raises(TracefinityError, match="host or user@host"):
        Tracefinity()


@pytest.mark.skipif(sys.platform != "win32", reason="the Job Object is Windows only")
def test_the_tunnel_ends_with_a_server_that_is_killed(fake, tmp_path):
    port = free_port()
    child = textwrap.dedent(
        f"""
        import os, sys
        sys.path[:0] = {[str(Path(__file__).resolve().parents[1] / "src")]!r}
        from solidseas_app.gridfinity.tunnel import SshTunnel
        way = SshTunnel("root@nas", {port}, ssh={FAKE_SSH!r})
        way.ensure()
        print("open", flush=True)
        os._exit(0)  # no close(): as when the MCP client kills the server
        """
    )
    env = {**os.environ, "FAKE_SSH_TARGET": str(fake.server.server_address[1])}
    done = subprocess.run([sys.executable, "-c", child], env=env, capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "open", done.stderr
    assert closed(port, within=10), "ssh outlived the server that started it"
