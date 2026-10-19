"""HTTP for the AI providers, on the standard library's ``http.client``.

One :class:`HttpClient` per provider. What it guarantees:

- **Timeouts.** Connecting (TCP, a proxy's CONNECT and TLS) gets
  :data:`CONNECT_TIMEOUT`, 5 seconds, and each read the read timeout, 60
  seconds for a cloud provider and 180 for Ollama. The whole call must finish
  within the two together and before the caller's deadline (an Automatic
  run's), so a server that trickles bytes cannot hold a call open.
- **Cancellation.** :class:`Cancel` stops a call in flight at once: the
  exchange runs on a worker thread, the caller stops waiting for it the moment
  Stop is pressed, and its socket is shut down; a back-off wait ends with it.
- **Delivered.** A timeout, Stop or broken connection after the connection was
  made and the request had started out is marked ``delivered`` (the provider
  may be working on it, and may bill for it), so the caller can charge the
  budgets for it; a failure before that, and a reply with an error status, is
  not.
- **429.** Retry-After is honoured (seconds or an HTTP date), otherwise the
  wait doubles from one second, with jitter, and the client gives up after
  :data:`MAX_TRIES` tries or when Retry-After asks for more than
  :data:`MAX_RETRY_WAIT` seconds. 503 and 529 (overloaded) are retried the same
  way. 401 and 403 are never retried. Spare keys are never used to get past a
  limit.
- **TLS** comes from ``truststore`` when it is installed, so the Windows
  certificate store decides and a TLS-inspecting proxy's root is trusted;
  otherwise from :func:`ssl.create_default_context`. TLS 1.2 is the minimum.
- **Proxies** come from :func:`urllib.request.getproxies` (the environment,
  then the static WinINET setting) for a cloud provider, through CONNECT. PAC,
  WPAD and proxy sign-in other than a user and password in the proxy URL are
  not supported, and a failure says so instead of blaming the key. A loopback
  host never goes through a proxy, and a client made with ``use_proxies=False``
  (Ollama's) never uses one.
- **Pinned addresses.** A client made with ``pin=True`` (Ollama's) resolves
  the host itself on every call and connects only to the addresses it
  resolved, so no second lookup can send the connection elsewhere.
  ``localhost`` must resolve only to loopback addresses, so for it what was
  checked is what is reached; any other host name the user or the policy
  allows goes wherever the name resolves on that call.
- **Plain HTTP** is allowed only to a loopback host or a host the caller lists
  (``plain_http_hosts``); everything else must be HTTPS. A base URL never holds
  a user name, a password, a query or a fragment.
- **Nothing secret in errors.** Messages name the host and what went wrong,
  never a header, a key or a query string. A reply body is quoted only for
  statuses other than 401 and 403: the provider's message is passed whole
  through the caller's ``scrub``, and only then cut to 200 characters, so the
  cut cannot leave part of a key the scrub would have caught.
"""

from __future__ import annotations

import base64
import email.utils
import http.client
import ipaddress
import json
import random
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    AIError,
    CancelledError,
    NetworkError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    UnauthorizedError,
    UnavailableError,
)

CONNECT_TIMEOUT = 5.0
CLOUD_READ_TIMEOUT = 60.0
LOCAL_READ_TIMEOUT = 180.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TRIES = 4
MAX_RETRY_WAIT = 30.0
RETRY_STATUSES = (429, 503, 529)
LOOPBACK_NAMES = frozenset({"localhost"})
_EXCERPT_CHARS = 200
_EXCERPT_SOURCE_CHARS = 20_000  # a longer provider message is not quoted at all


class Cancel:
    """A cancellation token for one call, or for every call of an Automatic run.

    :meth:`cancel` may be called from any thread; it runs the hooks that open calls
    registered (closing their sockets) and wakes a back-off wait."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._hooks: dict[int, Callable[[], None]] = {}
        self._next = 0

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            hooks = list(self._hooks.values())
            self._hooks.clear()
        for hook in hooks:
            try:
                hook()
            except Exception:
                pass

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; True as soon as the token is cancelled."""
        return self._event.wait(max(0.0, seconds))

    def on_cancel(self, hook: Callable[[], None]) -> int | None:
        """Run ``hook`` when the token is cancelled (at once if it already is). Returns an id
        for :meth:`remove`, or None when the hook already ran."""
        with self._lock:
            if not self._event.is_set():
                self._next += 1
                self._hooks[self._next] = hook
                return self._next
        try:
            hook()
        except Exception:
            pass
        return None

    def remove(self, hook_id: int | None) -> None:
        if hook_id is not None:
            with self._lock:
                self._hooks.pop(hook_id, None)


@dataclass(frozen=True)
class Endpoint:
    """A provider's base URL, checked: scheme, host (normalised), port and path prefix."""

    scheme: str
    host: str
    port: int
    path: str

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    def display(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default = 443 if self.scheme == "https" else 80
        return f"{self.scheme}://{host}" + ("" if self.port == default else f":{self.port}")


def is_loopback_host(host: str) -> bool:
    """``localhost`` or a loopback address literal (127.0.0.0/8, ::1, or an IPv4-mapped
    IPv6 form of 127.0.0.0/8, the same on every Python version)."""
    host = host.lower().rstrip(".")
    if host in LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def parse_endpoint(url: str, *, plain_http_hosts: frozenset[str] | tuple[str, ...] = ()) -> Endpoint:
    """Check a provider base URL. Raises :class:`ValueError` with a reason that never quotes
    a query string or a password."""
    if not isinstance(url, str) or not url or len(url) > 2048 or any(ord(c) < 0x21 for c in url):
        raise ValueError("the address is empty, too long or holds spaces or control characters")
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("the address must start with http:// or https://")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("the address must not hold a user name or password")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise ValueError("the address must not hold a query or a fragment")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("the address has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise ValueError("the address has a port that is not a number from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("the address has a port that is not a number from 1 to 65535")
    if scheme == "http" and not is_loopback_host(host) and host not in set(plain_http_hosts):
        raise ValueError("only a server on this machine, or one the policy lists, may use http://")
    path = parts.path.rstrip("/")
    return Endpoint(scheme=scheme, host=host, port=port, path=path)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        """The body as strict JSON: no NaN or Infinity. Raises :class:`ProviderError`."""
        try:
            return json.loads(self.body.decode("utf-8"), parse_constant=_refuse_constant)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ProviderError(
                "The provider's reply was not valid JSON.", detail={"value": self.status}
            ) from None


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def default_ssl_context() -> ssl.SSLContext:
    """``truststore``'s context when it is installed (the Windows certificate store decides),
    else the standard library's default; TLS 1.2 at least."""
    try:
        import truststore  # optional: the [ai] extra

        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _abort(conn: http.client.HTTPConnection) -> None:
    sock = conn.sock
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    """Retry-After as seconds: a number of seconds or an HTTP date; None when absent or
    not understood."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when is None:
            return None
        seconds = when.timestamp() - (time.time() if now is None else now)
    if seconds != seconds:  # NaN
        return None
    return max(0.0, seconds)


def error_excerpt(body: bytes, scrub: Callable[[str], str] | None = None) -> str | None:
    """The provider's own error message from a JSON error body, if it has one, passed whole
    through ``scrub`` and then cut to 200 characters. Scrubbing first matters: a key the
    cut split would no longer match the key, and its tail could be too short to look
    like one. A message longer than 20,000 characters is not quoted."""
    try:
        data = json.loads(body.decode("utf-8", errors="replace"), parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        return None
    text = None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]  # Gemini wraps its error in a list on some routes
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            text = err["message"]
        elif isinstance(err, str):
            text = err
        elif isinstance(data.get("message"), str):
            text = data["message"]
    if not text or len(text) > _EXCERPT_SOURCE_CHARS:
        return None
    text = "".join(c if c.isprintable() else " " for c in text)
    if scrub is not None:
        text = scrub(text)
    return text.strip()[:_EXCERPT_CHARS].strip() or None


@dataclass
class HttpClient:
    """Requests to one provider endpoint (see the module notes).

    ``proxies`` replaces :func:`urllib.request.getproxies` (tests); ``scrub`` cleans any
    provider text quoted in an error; ``sleep_scale`` shortens back-off waits (tests);
    ``max_response_bytes`` raises the cap on a reply for a client that downloads files
    (unset, :data:`MAX_RESPONSE_BYTES`)."""

    base_url: str
    read_timeout: float = CLOUD_READ_TIMEOUT
    connect_timeout: float = CONNECT_TIMEOUT
    use_proxies: bool = True
    pin: bool = False
    plain_http_hosts: tuple[str, ...] = ()
    proxies: dict[str, str] | None = None
    ssl_context: ssl.SSLContext | None = None
    scrub: Callable[[str], str] = field(default=lambda text: text)
    max_tries: int = MAX_TRIES
    backoff_base: float = 1.0
    rng: random.Random = field(default_factory=random.Random)
    max_response_bytes: int | None = None
    endpoint: Endpoint = field(init=False)

    def __post_init__(self) -> None:
        self.endpoint = parse_endpoint(self.base_url, plain_http_hosts=frozenset(self.plain_http_hosts))

    # ----------------------------------------------------------------- connection
    def _proxy(self) -> tuple[str, int, dict[str, str]] | None:
        """The proxy for this endpoint: (host, port, CONNECT headers), or None."""
        ep = self.endpoint
        if not self.use_proxies or ep.is_loopback:
            return None
        if self.proxies is not None:
            proxies = dict(self.proxies)
            bypass = urllib.request.proxy_bypass_environment(ep.host, proxies) if proxies.get("no") else False
        else:
            proxies = urllib.request.getproxies()
            try:
                bypass = urllib.request.proxy_bypass(ep.host)
            except Exception:
                bypass = False
        if bypass:
            return None
        url = proxies.get(ep.scheme)
        if not url:
            return None
        if "://" not in url:
            url = "http://" + url
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() != "http":
            raise NetworkError(
                f"The proxy for {ep.display()} is not an http:// proxy; SolidSeas supports only those."
            )
        try:
            host, port = parts.hostname, parts.port or 8080
        except ValueError:
            host, port = None, 0
        if not host:
            raise NetworkError("The proxy setting does not name a host SolidSeas can use.")
        headers: dict[str, str] = {}
        if parts.username is not None:
            user = urllib.parse.unquote(parts.username)
            password = urllib.parse.unquote(parts.password or "")
            token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
            headers["Proxy-Authorization"] = "Basic " + token
        return host, port, headers

    def _addresses(self) -> list[str] | None:
        """The addresses a pinned client may connect to, resolved now, in the resolver's
        order; None when not pinned."""
        ep = self.endpoint
        if not self.pin:
            return None
        try:
            return [str(ipaddress.ip_address(ep.host))]
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(ep.host, ep.port, type=socket.SOCK_STREAM)
        except OSError:
            raise NetworkError(f"The name {ep.host} could not be resolved.") from None
        addresses: list[str] = []
        for info in infos:
            address = str(info[4][0])
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise NetworkError(f"The name {ep.host} could not be resolved.")
        if ep.host in LOOPBACK_NAMES:
            addresses.sort(key=lambda a: ":" in a)  # 127.0.0.1 first: Ollama listens there by default
            for a in addresses:
                if not ipaddress.ip_address(a.split("%", 1)[0]).is_loopback:
                    raise NetworkError(
                        f"{ep.host} resolves to an address that is not this machine, "
                        "so SolidSeas does not use it."
                    )
        return addresses

    def _connection(self, connect_timeout: float) -> http.client.HTTPConnection:
        ep = self.endpoint
        proxy = self._proxy()
        if ep.scheme == "https":
            context = self.ssl_context or default_ssl_context()
            if proxy is not None:
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    proxy[0], proxy[1], timeout=connect_timeout, context=context
                )
                conn.set_tunnel(ep.host, ep.port, headers=proxy[2] or None)
            else:
                conn = http.client.HTTPSConnection(ep.host, ep.port, timeout=connect_timeout, context=context)
        else:
            conn = http.client.HTTPConnection(ep.host, ep.port, timeout=connect_timeout)
        pinned = self._addresses()
        if pinned is not None:
            port = ep.port

            def connect_pinned(_address, timeout=None, source_address=None):
                # only the addresses checked above, in order, as create_connection would try them
                last: OSError | None = None
                for address in pinned:
                    try:
                        return socket.create_connection((address, port), timeout, source_address)
                    except OSError as exc:
                        last = exc
                raise last or OSError("no address to connect to")

            conn._create_connection = connect_pinned  # type: ignore[attr-defined]
        return conn

    # ----------------------------------------------------------------- one request
    def _exchange(
        self,
        holder: dict[str, Any],
        stop: threading.Event,
        method: str,
        path: str,
        headers: dict[str, str] | None,
        body: bytes | None,
        connect_timeout: float,
        read_timeout: float,
    ) -> Response:
        conn = self._connection(connect_timeout)
        holder["conn"] = conn
        try:
            if stop.is_set():
                raise CancelledError()
            conn.connect()
            if stop.is_set():
                raise CancelledError()
            if conn.sock is not None:
                conn.sock.settimeout(read_timeout)
            send_headers = {"Accept": "application/json", "User-Agent": "SolidSeas"}
            send_headers.update(headers or {})
            if body is not None:
                send_headers.setdefault("Content-Type", "application/json")
            holder["sending"] = True  # from here the provider may have the request
            conn.request(method, self.endpoint.path + path, body=body, headers=send_headers)
            reply = conn.getresponse()
            limit = self.max_response_bytes or MAX_RESPONSE_BYTES
            data = reply.read(limit + 1)
            if len(data) > limit:
                raise ProviderError("The provider's reply was larger than SolidSeas accepts.")
            return Response(reply.status, {k.lower(): v for k, v in reply.getheaders()}, data)
        finally:
            conn.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        cancel: Cancel | None = None,
        deadline: float | None = None,
    ) -> Response:
        """One request and its whole reply, with the timeouts and cancellation above.

        The exchange runs on a worker thread and this thread waits for it, for Stop or for
        the time limit, whichever comes first, so neither Stop nor a timeout depends on a
        blocked socket call noticing. A worker left behind has its socket shut down and
        ends by its own read timeout at the latest; its result is dropped. An error after
        the request started out is marked ``delivered`` (see the module notes)."""
        if cancel is not None and cancel.cancelled:
            raise CancelledError()
        now = time.monotonic()
        remaining = None if deadline is None else deadline - now
        if remaining is not None and remaining <= 0:
            raise ProviderTimeoutError("The run's time limit was reached before the provider answered.")
        connect_timeout = self.connect_timeout if remaining is None else min(self.connect_timeout, remaining)
        read_timeout = self.read_timeout if remaining is None else min(self.read_timeout, remaining)
        total = self.connect_timeout + self.read_timeout
        if remaining is not None:
            total = min(total, remaining)
        holder: dict[str, Any] = {}
        result: dict[str, Any] = {}
        stop = threading.Event()
        done = threading.Event()

        def work() -> None:
            try:
                result["reply"] = self._exchange(
                    holder, stop, method, path, headers, body, connect_timeout, read_timeout
                )
            except BaseException as exc:  # handed to the waiting thread
                result["error"] = exc
            finally:
                done.set()

        def abandon() -> None:
            stop.set()
            conn = holder.get("conn")
            if conn is not None:
                _abort(conn)

        worker = threading.Thread(target=work, name="solidseas-ai-http", daemon=True)
        hook = cancel.on_cancel(done.set) if cancel is not None else None
        worker.start()
        try:
            end = time.monotonic() + total
            while not done.wait(max(0.0, min(0.25, end - time.monotonic()))):
                if time.monotonic() >= end:
                    break
            if cancel is not None and cancel.cancelled:
                abandon()
                raise CancelledError(delivered=bool(holder.get("sending")))
            if "reply" not in result and "error" not in result:
                abandon()
                raise ProviderTimeoutError(
                    f"{self.endpoint.display()} did not answer in time.",
                    delivered=bool(holder.get("sending")),
                )
        finally:
            if cancel is not None:
                cancel.remove(hook)
        if "reply" in result:
            return result["reply"]
        exc = result["error"]
        sent = bool(holder.get("sending"))
        if isinstance(exc, AIError):
            exc.delivered = exc.delivered or sent
            raise exc
        if isinstance(exc, (TimeoutError, socket.timeout)):
            raise ProviderTimeoutError(
                f"{self.endpoint.display()} did not answer in time.", delivered=sent
            ) from None
        if isinstance(exc, (OSError, http.client.HTTPException, ValueError)):
            error = self._network_error(exc)
            error.delivered = sent
            raise error from None
        raise exc

    def _network_error(self, exc: BaseException) -> NetworkError:
        where = self.endpoint.display()
        text = str(exc)
        if isinstance(exc, OSError) and text.startswith("Tunnel connection failed"):
            status = text.split(":", 1)[1].strip().split(" ", 1)[0] if ":" in text else ""
            if status == "407":
                return NetworkError(
                    f"The proxy asked to sign in before reaching {where}. SolidSeas supports a user and "
                    "password in the proxy setting, but not NTLM, Kerberos, PAC or WPAD, in this release."
                )
            return NetworkError(
                f"The proxy refused the connection to {where} (status {status or 'unknown'})."
            )
        if isinstance(exc, ssl.SSLCertVerificationError):
            return NetworkError(
                f"The certificate of {where} was not trusted. On a network that inspects TLS, install the "
                "truststore package (the [ai] extra) so the Windows certificate store is used."
            )
        if isinstance(exc, ssl.SSLError):
            return NetworkError(f"The secure connection to {where} failed ({type(exc).__name__}).")
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        reason = type(exc).__name__ + (f", error {code}" if code else "")
        return NetworkError(
            f"{where} could not be reached ({reason}). If this PC reaches the internet through a proxy "
            "chosen by a PAC file or WPAD, or one that needs NTLM sign-in, SolidSeas cannot use it yet."
        )

    # ----------------------------------------------------------------- with retries and status checks
    def send(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        cancel: Cancel | None = None,
        deadline: float | None = None,
    ) -> Response:
        """:meth:`request`, retried on 429, 503 and 529 as the module notes say; a 2xx reply,
        or an :class:`~solidseas.ai.errors.AIError` for any other status."""
        tries = max(1, self.max_tries)
        for attempt in range(tries):
            reply = self.request(method, path, headers=headers, body=body, cancel=cancel, deadline=deadline)
            if 200 <= reply.status < 300:
                return reply
            if reply.status in (401, 403):
                raise UnauthorizedError(
                    f"{self.endpoint.display()} refused the API key (status {reply.status}). "
                    "Check or replace the key in settings.",
                    detail={"value": reply.status},
                )
            if reply.status not in RETRY_STATUSES:
                excerpt = error_excerpt(reply.body, self.scrub)
                message = f"{self.endpoint.display()} returned status {reply.status}"
                if excerpt:
                    message += ": " + excerpt
                raise ProviderError(message + ".", detail={"value": reply.status})
            wait = retry_after_seconds(reply.headers.get("retry-after"))
            if wait is None:
                wait = self.backoff_base * (2**attempt) * (0.5 + self.rng.random() / 2)
            else:
                wait += self.rng.random() * 0.25 * self.backoff_base
            last = attempt == tries - 1
            past_deadline = deadline is not None and time.monotonic() + wait >= deadline
            if last or wait > MAX_RETRY_WAIT or past_deadline:
                break
            if cancel is not None:
                if cancel.wait(wait):
                    raise CancelledError()
            else:
                time.sleep(wait)
        if reply.status == 429:
            raise RateLimitedError(
                f"{self.endpoint.display()} is limiting requests (status 429). Try again in a minute.",
                detail={"value": 429},
            )
        raise UnavailableError(
            f"{self.endpoint.display()} is overloaded or down (status {reply.status}). Try again later.",
            detail={"value": reply.status},
        )


__all__ = [
    "CLOUD_READ_TIMEOUT",
    "CONNECT_TIMEOUT",
    "LOCAL_READ_TIMEOUT",
    "MAX_RESPONSE_BYTES",
    "MAX_RETRY_WAIT",
    "MAX_TRIES",
    "Cancel",
    "Endpoint",
    "HttpClient",
    "Response",
    "default_ssl_context",
    "error_excerpt",
    "is_loopback_host",
    "parse_endpoint",
    "retry_after_seconds",
]
