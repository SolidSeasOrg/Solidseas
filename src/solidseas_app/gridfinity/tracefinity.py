"""Tracefinity's HTTP API, reached on this PC's loopback only.

Requests go through :class:`solidseas.ai.http.HttpClient`: the address is resolved on every
call and only the loopback addresses it resolved to are connected to, no proxy is used, and
every call has a time limit and can be cancelled. An address that is not loopback is
refused when the client is made, whatever its scheme. Ids the chat passes in are checked
before they become part of a path.

Tracefinity runs either on this PC (``scripts/tracefinity.ps1``, Docker Desktop) or on a
server, reached through an SSH tunnel that SolidSeas opens to the same port on the server's
own loopback (:mod:`.tunnel`, ``scripts/tracefinity-server.ps1``). Either way it is in its
``open`` mode (``AUTH_MODE=open``), one library without a sign-in, which is safe only
because nothing but its own machine reaches it; a Tracefinity that asks to sign in is
reported, never signed in to.
"""

from __future__ import annotations

import json
import re
import secrets
import urllib.parse
from typing import Any

from solidseas.ai.errors import AIError, CancelledError, NetworkError, ProviderTimeoutError
from solidseas.ai.http import Cancel, HttpClient, is_loopback_host, parse_endpoint

from .tunnel import SSH_ENV, SshTunnel, TunnelError, from_settings

DEFAULT_URL = "http://127.0.0.1:3077"
URL_ENV = "SOLIDSEAS_TRACEFINITY_URL"
QUICK_S = 60.0  # reading and saving
SLOW_S = 900.0  # tracing (the first trace downloads Tracefinity's model) and making a bin
MAX_PHOTO_BYTES = 20 << 20  # Tracefinity's own upload limit
MAX_FILE_BYTES = 512 << 20  # one of a bin's files: STL, 3MF or the zip of its parts
PAPER_SIZES = ("a4", "letter", "a3", "tabloid")
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
_ID = re.compile(r"\A[0-9A-Za-z][0-9A-Za-z_-]{0,63}\Z")
_DETAIL_CHARS = 300

NOT_ANSWERING = (
    "Tracefinity is not answering at {where}. Start Docker Desktop, then Tracefinity with "
    "scripts\\tracefinity.ps1 in the SolidSeas folder (or docker start tracefinity), and try again. "
    "docs/GRIDFINITY.md says how to set it up."
)
NOT_ANSWERING_THERE = (
    "Tracefinity is not answering on {server} through the SSH tunnel. Start its container there "
    "(docker start tracefinity, or the server's Docker page) and try again. docs/GRIDFINITY.md says "
    "how to set it up (scripts\\tracefinity-server.ps1)."
)
SIGN_IN = (
    "Tracefinity at {where} asks to sign in. SolidSeas does not sign in: run Tracefinity with "
    "AUTH_MODE=open, bound to this PC only, as scripts\\tracefinity.ps1 does."
)


class TracefinityError(RuntimeError):
    """Tracefinity could not do what was asked: said to the chat as it is."""


def segment(value: Any, what: str) -> str:
    """An id the chat gave, checked before it becomes part of a path."""
    if not isinstance(value, str) or not _ID.match(value):
        raise TracefinityError(f"{str(value)[:40]!r} is not a {what} id.")
    return value


class Tracefinity:
    """One Tracefinity, at ``url`` (default :data:`URL_ENV`, else :data:`DEFAULT_URL`), through
    ``tunnel`` when it runs on a server (default: the one :data:`.tunnel.SSH_ENV` names)."""

    def __init__(self, url: str | None = None, *, tunnel: SshTunnel | bool | None = True) -> None:
        if not url:
            from ..extensions import setting

            url = setting("gridfinity", "tracefinity_url")  # its variable, else the Extensions page
        url = url or DEFAULT_URL
        try:
            host = urllib.parse.urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        if host and not is_loopback_host(host):
            raise TracefinityError(
                f"SolidSeas reaches Tracefinity on this PC only, and the address names {host}. For a "
                f"Tracefinity on a server, name the server in {SSH_ENV} instead (docs/GRIDFINITY.md)."
            )
        try:
            endpoint = parse_endpoint(url)
        except ValueError as exc:
            raise TracefinityError(f"The Tracefinity address is not usable: {exc}.") from None
        if not endpoint.is_loopback:
            raise TracefinityError(
                f"SolidSeas reaches Tracefinity on this PC only, and the address names {endpoint.display()}."
            )
        self.where = endpoint.display()
        self.base = self.where + endpoint.path
        try:
            self.tunnel = from_settings(endpoint.port) if tunnel is True else (tunnel or None)
        except TunnelError as exc:
            raise TracefinityError(str(exc)) from None
        common: dict[str, Any] = {"use_proxies": False, "pin": True}
        self._quick = HttpClient(url, read_timeout=QUICK_S, **common)
        self._slow = HttpClient(url, read_timeout=SLOW_S, **common)
        self._files = HttpClient(url, read_timeout=SLOW_S, max_response_bytes=MAX_FILE_BYTES, **common)

    def page(self, kind: str, item: str) -> str:
        """The address of Tracefinity's own page for a trace, tool or bin, for the person."""
        return f"{self.base}/{kind}/{segment(item, kind)}"

    def close(self) -> None:
        """End the SSH tunnel, if this client opened one."""
        if self.tunnel is not None:
            self.tunnel.close()

    # ----------------------------------------------------------------- transport
    def _send(
        self,
        client: HttpClient,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        cancel: Cancel | None = None,
    ) -> bytes:
        if self.tunnel is not None:
            try:
                self.tunnel.ensure()
            except TunnelError as exc:
                raise TracefinityError(str(exc)) from None
        try:
            reply = client.request(method, path, headers=headers, body=body, cancel=cancel)
        except CancelledError:
            raise
        except ProviderTimeoutError:
            raise TracefinityError(f"Tracefinity at {self.where} did not answer in time.") from None
        except NetworkError:
            if self.tunnel is not None:
                raise TracefinityError(NOT_ANSWERING_THERE.format(server=self.tunnel.destination)) from None
            raise TracefinityError(NOT_ANSWERING.format(where=self.where)) from None
        except AIError as exc:
            raise TracefinityError(f"Tracefinity at {self.where}: {exc}") from None
        if reply.status in (401, 403):
            raise TracefinityError(SIGN_IN.format(where=self.where))
        if not 200 <= reply.status < 300:
            raise TracefinityError(f"Tracefinity refused: {_detail(reply.body)} (status {reply.status}).")
        return reply.body

    def _json(
        self,
        client: HttpClient,
        method: str,
        path: str,
        data: Any = None,
        *,
        cancel: Cancel | None = None,
    ) -> Any:
        body = None if data is None else json.dumps(data, allow_nan=False).encode("utf-8")
        raw = self._send(client, method, path, body=body, cancel=cancel)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise TracefinityError(
                f"The reply from {self.where} was not Tracefinity's: is something else answering there?"
            ) from None

    # ----------------------------------------------------------------- the API
    def version(self, *, cancel: Cancel | None = None) -> str:
        reply = self._json(self._quick, "GET", "/api/version", cancel=cancel)
        return str(reply.get("version", "")) if isinstance(reply, dict) else ""

    def upload(self, data: bytes, suffix: str, *, cancel: Cancel | None = None) -> dict:
        """Send a photo; Tracefinity looks for the paper's corners in it. The photo goes as
        ``photo<suffix>``, so its own name stays on this PC."""
        content_type = CONTENT_TYPES.get(suffix.lower())
        if content_type is None:
            raise TracefinityError(f"Tracefinity reads {', '.join(CONTENT_TYPES)} photos.")
        if len(data) > MAX_PHOTO_BYTES:
            raise TracefinityError("The photo is larger than the 20 MB Tracefinity takes.")
        boundary = "solidseas-" + secrets.token_hex(12)
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="photo{suffix.lower()}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("ascii")
        body = head + data + f"\r\n--{boundary}--\r\n".encode("ascii")
        raw = self._send(
            self._slow,
            "POST",
            "/api/upload",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            cancel=cancel,
        )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise TracefinityError(f"The reply from {self.where} was not Tracefinity's.") from None

    def set_corners(self, trace: str, corners: list, paper: str, *, cancel: Cancel | None = None) -> dict:
        if paper not in PAPER_SIZES:
            raise TracefinityError(f"The paper is one of {', '.join(PAPER_SIZES)}.")
        path = f"/api/sessions/{segment(trace, 'trace')}/corners"
        return self._json(self._slow, "POST", path, {"corners": corners, "paper_size": paper}, cancel=cancel)

    def trace(self, trace: str, *, cancel: Cancel | None = None) -> dict:
        path = f"/api/sessions/{segment(trace, 'trace')}/trace"
        return self._json(self._slow, "POST", path, {}, cancel=cancel)

    def session(self, trace: str, *, cancel: Cancel | None = None) -> dict:
        return self._json(self._quick, "GET", f"/api/sessions/{segment(trace, 'trace')}", cancel=cancel)

    def save_tools(self, trace: str, outline_ids: list[str], *, cancel: Cancel | None = None) -> list[str]:
        path = f"/api/sessions/{segment(trace, 'trace')}/save-tools"
        reply = self._json(
            self._quick,
            "POST",
            path,
            {"polygon_ids": [segment(i, "outline") for i in outline_ids]},
            cancel=cancel,
        )
        ids = reply.get("tool_ids") if isinstance(reply, dict) else None
        if not isinstance(ids, list):
            raise TracefinityError("Tracefinity did not say which tools it saved.")
        return [segment(i, "tool") for i in ids]

    def tools(self, *, cancel: Cancel | None = None) -> list[dict]:
        reply = self._json(self._quick, "GET", "/api/tools", cancel=cancel)
        tools = reply.get("tools") if isinstance(reply, dict) else None
        return [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else []

    def tool(self, tool: str, *, cancel: Cancel | None = None) -> dict:
        return self._json(self._quick, "GET", f"/api/tools/{segment(tool, 'tool')}", cancel=cancel)

    def update_tool(self, tool: str, fields: dict, *, cancel: Cancel | None = None) -> None:
        self._json(self._quick, "PUT", f"/api/tools/{segment(tool, 'tool')}", fields, cancel=cancel)

    def create_bin(self, name: str, config: dict, *, cancel: Cancel | None = None) -> dict:
        return self._json(
            self._quick,
            "POST",
            "/api/bins",
            {"name": name, "tool_ids": [], "bin_config": config},
            cancel=cancel,
        )

    def update_bin(self, bin_id: str, fields: dict, *, cancel: Cancel | None = None) -> None:
        self._json(self._quick, "PUT", f"/api/bins/{segment(bin_id, 'bin')}", fields, cancel=cancel)

    def generate(self, bin_id: str, *, cancel: Cancel | None = None) -> dict:
        return self._json(self._slow, "POST", f"/api/bins/{segment(bin_id, 'bin')}/generate", cancel=cancel)

    def bin_file(self, bin_id: str, name: str, *, cancel: Cancel | None = None) -> bytes:
        """One of a bin's files: ``bin.stl``, ``bin.3mf`` or ``bin_parts.zip``."""
        if name not in ("bin.stl", "bin.3mf", "bin_parts.zip"):
            raise TracefinityError(f"A bin has no file {name!r}.")
        path = f"/api/files/bins/{segment(bin_id, 'bin')}/{name}"
        return self._send(self._files, "GET", path, cancel=cancel)


def _detail(body: bytes) -> str:
    """Tracefinity's reason for refusing, as FastAPI gives it, cut short."""
    try:
        reply = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "no reason given"
    detail = reply.get("detail") if isinstance(reply, dict) else None
    if isinstance(detail, list):  # a validation error: one message per field
        detail = "; ".join(str(d.get("msg", "")) for d in detail if isinstance(d, dict))
    if not isinstance(detail, str) or not detail.strip():
        return "no reason given"
    text = "".join(c for c in detail if c.isprintable())
    return text if len(text) <= _DETAIL_CHARS else text[:_DETAIL_CHARS] + "..."


__all__ = [
    "CONTENT_TYPES",
    "DEFAULT_URL",
    "MAX_PHOTO_BYTES",
    "PAPER_SIZES",
    "URL_ENV",
    "Tracefinity",
    "TracefinityError",
    "segment",
]
