"""A running ``solidseas serve`` for tests, and plain HTTP helpers.

The service runs in this process on an ephemeral loopback port, with its own
worker processes. Requests go through ``http.client`` or, where a client would
refuse to send what the test needs (a wrong Host, a slow trickle), through a raw
socket.

:func:`no_outbound_connections` (from ``netguard``) makes any connection or name lookup to anything
but this machine's loopback fail, so a test module that uses it proves the
service in this process reaches nothing else (``docs/API.md`` section 8).
"""

import http.client
import json
import logging
import os
import shutil
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from netguard import OutboundConnection, no_outbound_connections  # noqa: F401  (the service tests use them)
from solidseas import Root, Roots
from solidseas.serve import ServeConfig, Server
from support import FIXTURES

TOKEN = "tests-token-" + "Ab0_" * 8  # 44 URL-safe characters, as token_urlsafe(32) makes
OTHER_TOKEN = "other-token-" + "Zz9-" * 8
FIXDIR = Path(os.environ.get("SOLIDSEAS_FIXTURES_DIR") or FIXTURES)
DOCUMENT_SUFFIXES = (".sldprt", ".sldasm", ".slddrw")
PNG = b"\x89PNG\r\n\x1a\n"


def fixture_documents() -> list[Path]:
    """The SOLIDWORKS documents in the fixtures folder (``SOLIDSEAS_FIXTURES_DIR`` overrides it)."""
    if not FIXDIR.is_dir():
        return []
    return sorted(p for p in FIXDIR.iterdir() if p.is_file() and p.suffix.lower() in DOCUMENT_SUFFIXES)


def copy_documents(dest: Path, docs: list[Path] | None = None) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for p in fixture_documents() if docs is None else docs:
        shutil.copy2(p, dest / p.name)
        out.append(dest / p.name)
    return out


@dataclass
class Response:
    status: int
    headers: dict[str, str]  # lower-cased names; a repeated header keeps its last value
    header_list: list[tuple[str, str]]
    body: bytes

    def json(self):
        def refuse(name):
            raise ValueError(f"{name} is not strict JSON")

        return json.loads(self.body, parse_constant=refuse)


class LogCapture(logging.Handler):
    """Every line the service logs, formatted as it would be."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class Running:
    """A started service over ``roots`` ({id: folder}, or a :class:`Roots`), on ``port``
    (a free one when 0); close it with :meth:`close`."""

    def __init__(self, roots, *, pool=None, tokens=None, workers: int = 2, port: int = 0, **config) -> None:
        self.log = LogCapture()
        logger = logging.getLogger("solidseas.serve")
        logger.addHandler(self.log)
        logger.setLevel(logging.INFO)
        cfg = ServeConfig(
            roots=roots if isinstance(roots, Roots) else Roots([Root(k, str(v)) for k, v in roots.items()]),
            tokens=tokens or {"tests": TOKEN},
            port=port,
            workers=workers,
            **config,
        )
        self.server = Server(cfg, pool=pool)
        self.server.start()
        self.thread = threading.Thread(target=self.server.serve_forever, name="test-serve", daemon=True)
        self.thread.start()
        assert self.server.wait_ready(120), "the roots' folder indexes were not built in time"
        self.port = self.server.port
        self.responses: list[Response] = []

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        token: str | None = TOKEN,
        headers: dict | None = None,
        timeout: float = 120,
    ) -> Response:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            h = {"Authorization": f"Bearer {token}"} if token is not None else {}
            h.update(headers or {})
            conn.request(method, path, headers=h)
            r = conn.getresponse()
            body = r.read()
            pairs = r.getheaders()
        finally:
            conn.close()
        resp = Response(r.status, {k.lower(): v for k, v in pairs}, pairs, body)
        self.responses.append(resp)
        return resp

    def get(self, route: str, token: str | None = TOKEN, **params) -> Response:
        from urllib.parse import urlencode

        query = urlencode(params)
        return self.request(f"/v1/{route}" + (f"?{query}" if query else ""), token=token)

    def raw(self, data: bytes, *, timeout: float = 20) -> bytes:
        """Send ``data`` as is on a new connection and read until the server closes it."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as s:
            s.sendall(data)
            chunks = []
            while True:
                try:
                    chunk = s.recv(65536)
                except (ConnectionResetError, ConnectionAbortedError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks)

    def close(self, *, close_pool: bool = True) -> list[str]:
        try:
            return self.server.shutdown(close_pool=close_pool)
        finally:
            logging.getLogger("solidseas.serve").removeHandler(self.log)


def status_of(raw: bytes) -> int:
    """The status code of a raw HTTP response."""
    first = raw.split(b"\r\n", 1)[0].split()
    return int(first[1]) if len(first) > 1 and first[1].isdigit() else 0


def body_of(raw: bytes) -> dict:
    return json.loads(raw.split(b"\r\n\r\n", 1)[1])


def wait_for(predicate, timeout: float = 30.0, step: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return False
