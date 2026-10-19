"""``solidseas serve``: a small, read-only REST service over configured roots.

``docs/API.md`` section 8 is the reference. The rules, in the order a request
meets them:

1. **Bind.** 127.0.0.1 by default (``localhost`` means 127.0.0.1; ``::1`` is
   accepted). Any other address needs ``allow_remote`` and at least one allowed
   host name, or the service refuses to start (:class:`~solidseas.errors.BindRefusedError`).
   Plain HTTP only: a remote bind is for a private network such as a compose
   network. The listening socket is the service's only socket; it makes no
   outbound connection (not even the reverse DNS lookup ``HTTPServer`` does).
2. **Reading the request.** The request line and headers must arrive within
   ``read_timeout`` seconds in all (a byte-a-second sender is cut off), and a
   connection that sends no byte of a request for ``idle_timeout`` seconds is
   closed. A URL may be 4 KiB and the headers 16 KiB: the headers stop being
   read, and the request answers 431, as soon as they pass that, so no client
   makes the service hold more. A request may carry no body, and must name
   HTTP/1.0 or 1.1. At most ``max_connections`` connections are open at once;
   one closed because its head did not arrive in time is logged.
3. **Host, Origin and Fetch Metadata** (````),
   before routing: the ``Host`` header must name the bound address or an
   allowed host, with the bound port, which stops DNS rebinding. Any
   ``Origin`` header, and a ``Sec-Fetch-Site`` other than ``none`` or
   ``same-origin``, is a browser request from another site and is refused:
   there is no CORS, and no response carries ``Access-Control-Allow-Origin``.
4. **Method.** GET and HEAD only; anything else, a method the service has never
   heard of included, answers 405 with ``Allow`` (after the Host check).
5. **Token.** Every route but ``/v1/health`` and ``/v1/identity`` needs
   ``Authorization: Bearer``, on loopback too (:mod:`.tokens`). More than
   ``max_auth_failures`` failures in a minute from one address answer 429.
   ``/v1/identity`` lets a client check, before it sends its token, that the
   service holds that token: it answers the client's nonce with an HMAC under
   the token, bound to the address and port the connection reached.
6. **Query.** One allowlist per route (:mod:`.query`).
7. **Paths.** A request names a root by id and a path relative to it; the path
   is checked as text and found in the root's folder index (:mod:`.paths`),
   never joined into a path. While a root's index is being built the service
   answers 503 ``busy`` with ``Retry-After``. A resolution (``resolve=1``)
   walks every root again for its request, so it sees the folders as they are
   now, not as they were at the start.
8. **Reading.** The server process never opens a CAD file. Every document is
   read in a :class:`~solidseas.workers.WorkerPool` worker, opened ``within`` the
   root, with a deadline per route; a worker that misses it is replaced and the
   request answers 504. At most ``in_flight`` requests read at once; more
   answer 503 ``busy``.
9. **Answering.** Every JSON answer is built by the same builder the Python API
   and the CLI use (:mod:`solidseas.model`), wrapped in an envelope whose
   ``source`` is ``{"root", "path"}``. Error objects never carry the reader's
   own message (it can hold an absolute path). Answers have size caps, an
   ``ETag`` computed from a ``stat`` (``If-None-Match`` answers 304 without
   reading the file), and the security headers on every response. No HTML,
   SVG or XML is ever served; a preview is served only after its bytes are
   checked to be a PNG or a BMP.
10. **The catalog** (``--catalog``, provisional). The service keeps a catalog of
    its roots (:mod:`solidseas.catalog`) in the user's cache folder, scanned when it
    starts and again every ``catalog_rescan`` seconds by a thread of its own that
    reads documents with workers of its own (at most two, below normal priority,
    with the service's limits), so a scan and the requests never wait for each
    other's workers; a request never starts a scan. The catalog indexes the
    formats the service reads (``formats``), no more. ``/v1/catalog``,
    ``/v1/where-used`` and ``/v1/search`` answer from it on a read-only
    connection, with a deadline that holds for the SQL and for where-used's own
    walk, and only with root ids and relative paths; a where-used answer over
    the size cap keeps the nearest users that fit and says ``truncated``. Before
    the first scan has finished they answer 503 ``busy``, and without
    ``--catalog`` 403 ``feature_disabled``.
11. **Logging.** One line per request: time, request id, client (the token's
    name), peer, method, route, root id, status, error code, refusal rule and
    component index, duration and bytes. Never a path, a query, a token or
    anything read from a file.

The service never writes, renames or deletes anything under a root; its only
write is its own token file, on first start.
"""

import base64
import contextlib
import hashlib
import http.client
import ipaddress
import itertools
import logging
import os
import queue
import re
import signal
import socket
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .. import __version__, model
from .. import bom as bom_mod
from ..errors import (
    AddressUnavailableError,
    BindRefusedError,
    InvalidArgumentError,
    UnsupportedOperationError,
    WorkerCrashedError,
    WorkerJobError,
    WorkerTimeoutError,
)
from ..formats import registry
from ..formats.solidworks._io import check_folder_within
from ..formats.solidworks.preview import PNG_SIGNATURE
from ..listing import Scan
from ..resolve import Gateway, ResolutionInput, resolve_references
from ..resolve.identity import Identity, parse_creation_time
from ..roots import Roots
from ..workers import WorkerPool
from .paths import Located, check_path_text, locate
from .query import Param, ServiceError, parse_query, requested_location
from .tokens import IDENTITY_SCHEME, TokenChecker, proof_address

DEFAULT_PORT = 8765
MAX_URL = 4096
MAX_HEADER_BYTES = 16 << 10
# The header bytes read before a request is refused 431: the limit, with room for the line
# ends and the blank line. The stdlib alone would buffer 100 lines of 64 KiB each.
HEAD_BUDGET = MAX_HEADER_BYTES + 1024
REFUSED_DRAIN_S = 0.1  # how long a refused connection's bytes are read before it is closed
# What a worker's answer may hold beyond the route's cap (the server adds only the envelope):
# a longer one is refused in the worker, or at the pipe, before this process parses it.
REPLY_MARGIN = 64 << 10
CATALOG_WORKERS = 2  # the catalog's own workers (at most the service's), below normal priority
CATALOG_SCANS_KEPT = 10  # the last scans' results the service keeps (Server.catalog_scans)
LOG = logging.getLogger("solidseas.serve")

DEFAULT_DEADLINES: dict[str, float] = {
    "document": 15.0,
    "preview": 10.0,
    "path_report": 30.0,
    "list_page": 60.0,
    "list_file": 10.0,
    # a BOM reads its component files in a worker, which gives itself 60 s (solidseas.bom), after
    # the assembly's own reading and the resolution in this process
    "bom": 120.0,
    "catalog": 5.0,
}
DEFAULT_CAPS: dict[str, int] = {
    "document": 1 << 20,
    "components": 8 << 20,
    "references": 8 << 20,
    "bom": 8 << 20,
    "path_report": 8 << 20,
    "list": 8 << 20,
    "preview": 16 << 20,
    "catalog": 1 << 20,
}
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cache-Control", "private, no-cache"),
)
JSON_TYPE = "application/json; charset=utf-8"
_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
_SAFE_TOKEN = re.compile(r"[a-z_]{1,40}\Z")
_METHOD = re.compile(r"[A-Z]{1,10}\Z")
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,8192}\Z")
_RETRY_AFTER = {"busy": "2", "root_unavailable": "30", "too_many_failures": "60"}
_TRANSIENT = ("timeout", "worker_crashed")  # entry errors that say nothing lasting about the file


def default_workers() -> int:
    return max(1, min(4, os.cpu_count() or 1))


# --------------------------------------------------------------------------- configuration
@dataclass
class ServeConfig:
    """What ``solidseas serve`` runs with. ``tokens`` maps each client's name to its
    bearer token (:func:`.tokens.load_tokens`). The limits are per route kind:
    ``deadlines`` in seconds (``document``, ``preview``, ``path_report``,
    ``list_page``, ``list_file``) and ``response_caps`` in bytes."""

    roots: Roots
    tokens: Mapping[str, str]
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    allow_remote: bool = False
    allowed_hosts: tuple[str, ...] = ()
    workers: int = field(default_factory=default_workers)
    worker_memory_mb: int | None = 2048
    max_file_bytes: int = 256 << 20
    in_flight: int = 16
    max_connections: int = 64
    read_timeout: float = 10.0
    idle_timeout: float = 5.0
    write_timeout: float = 60.0
    max_requests_per_connection: int = 100
    deadlines: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_DEADLINES))
    response_caps: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_CAPS))
    refuse_hard_links: bool = True
    index_max_examined: int = 1_000_000
    shutdown_budget_s: float = 5.0
    max_auth_failures: int = 20
    catalog: bool = False
    catalog_rescan_s: float = 300.0
    catalog_cache_dir: str | None = None
    # The file formats the service reads (provisional): "solidworks", "all" or format ids.
    formats: Any = registry.SOLIDWORKS

    def __post_init__(self) -> None:
        if not isinstance(self.roots, Roots) or not len(self.roots):
            raise InvalidArgumentError("the service needs at least one root", detail={"parameter": "root"})
        self.formats = tuple(sorted(registry.select(self.formats)))
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise InvalidArgumentError("a port is 0 to 65535", detail={"parameter": "port"})
        self.allowed_hosts = tuple(self.allowed_hosts)
        self.deadlines = {**DEFAULT_DEADLINES, **dict(self.deadlines)}
        self.response_caps = {**DEFAULT_CAPS, **dict(self.response_caps)}
        for name in (
            "workers",
            "in_flight",
            "max_connections",
            "max_requests_per_connection",
            "max_auth_failures",
        ):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise InvalidArgumentError(f"{name} must be at least 1", detail={"parameter": name})
        for name in (
            "read_timeout",
            "idle_timeout",
            "write_timeout",
            "shutdown_budget_s",
            "catalog_rescan_s",
        ):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
                raise InvalidArgumentError(f"{name} must be positive", detail={"parameter": name})
        if self.catalog:
            self._check_catalog_folder()

    def _check_catalog_folder(self) -> None:
        """The service never writes under a root, its catalog included: a cache folder
        inside a root (``SOLIDSEAS_CACHE_DIR`` there, or a root at the home folder, which
        holds the cache) is refused before anything starts."""
        from ..catalog import store
        from ..resolve.names import fold

        folder = fold(os.path.realpath(store.catalogs_dir(self.catalog_cache_dir)))
        for r in self.roots:
            base = fold(os.path.realpath(r.path)).rstrip("\\/")
            if folder == base or folder.startswith(base + os.sep):
                raise InvalidArgumentError(
                    f"the catalog would be kept inside the root {r.id}, and the service never writes under "
                    "a root: set SOLIDSEAS_CACHE_DIR to a folder outside the roots",
                    detail={"parameter": "catalog"},
                )


def check_bind(host: str, *, allow_remote: bool, allowed_hosts) -> str:
    """The address to bind for ``host``: ``localhost`` is 127.0.0.1. Anything but a
    loopback address needs ``allow_remote`` and at least one allowed host, or
    :class:`~solidseas.errors.BindRefusedError` (exit 3) names what is missing."""
    if not isinstance(host, str) or not host or len(host) > 255:
        raise InvalidArgumentError("--bind takes an address", detail={"parameter": "bind"})
    if host == "localhost":
        return "127.0.0.1"
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if loopback:
        return host
    if not allow_remote:
        raise BindRefusedError(
            "refusing a non-loopback address: the service answers anything that reaches it; "
            "pass --allow-remote and --allowed-host to bind it",
            detail={"rule": "remote_not_allowed"},
        )
    if not allowed_hosts:
        raise BindRefusedError(
            "a remote bind needs at least one --allowed-host name for the Host check",
            detail={"rule": "no_allowed_hosts"},
        )
    return host


# --------------------------------------------------------------------------- routes
@dataclass(frozen=True)
class Route:
    """One route: the kind it answers with (None for the preview image), its query
    allowlist, whether it needs a token, the worker job, and its deadline and cap."""

    path: str
    kind: str | None
    params: dict[str, Param]
    auth: bool = True
    job: str | None = None
    deadline: str = "document"
    cap: str = "document"


_ROOT = Param("root", required=True)
_FILE = Param("path", required=True)
_NESTED = Param("nested")
_CONFIGURATION = Param("text")

ROUTES: dict[str, Route] = {
    r.path: r
    for r in (
        Route("/v1/health", "health", {}, auth=False),
        Route(
            "/v1/identity",
            "identity",
            {"client": Param("client", required=True), "nonce": Param("nonce", required=True)},
            auth=False,
        ),
        Route("/v1/version", "version", {}),
        Route("/v1/roots", "roots", {}),
        Route(
            "/v1/list",
            "listing",
            {
                "root": _ROOT,
                "path": Param("path", default=""),
                "recursive": Param("bool", default=False),
                "include": Param("include", choices=model.LISTING_PARTS, default=model.LISTING_DEFAULT),
                "limit": Param("int", low=1, high=500, default=100),
                "cursor": Param("cursor"),
                "formats": Param("text", max_len=1000),
            },
            deadline="list_page",
            cap="list",
        ),
        Route(
            "/v1/document",
            "document_summary",
            {"root": _ROOT, "path": _FILE, "nested": _NESTED},
            job="document_summary",
        ),
        Route(
            "/v1/properties",
            "properties",
            {
                "root": _ROOT,
                "path": _FILE,
                "configuration": _CONFIGURATION,
                "view": Param("enum", choices=model.PROPERTY_VIEWS, default="effective"),
                "nested": _NESTED,
            },
            job="properties",
        ),
        Route("/v1/configurations", "configurations", {"root": _ROOT, "path": _FILE}, job="configurations"),
        Route(
            "/v1/components",
            "components",
            {
                "root": _ROOT,
                "path": _FILE,
                "configuration": _CONFIGURATION,
                "max_depth": Param("int", low=1, high=32, default=32),
                "max_nodes": Param("int", low=1, high=10_000, default=10_000),
                "flat": Param("bool", default=False),
            },
            job="components",
            cap="components",
        ),
        Route(
            "/v1/references",
            "references",
            {
                "root": _ROOT,
                "path": _FILE,
                "configuration": _CONFIGURATION,
                "resolve": Param("bool", default=False),
            },
            job="references",
            cap="references",
        ),
        Route(
            "/v1/bom",
            "bom",
            {
                "root": _ROOT,
                "path": _FILE,
                "configuration": _CONFIGURATION,
                "type": Param("enum", choices=bom_mod.BOM_TYPES, default=bom_mod.DEFAULT_TYPE),
                "columns": Param("text", max_len=4096),
                "part_number_property": Param("text"),
            },
            job="bom",
            deadline="bom",
            cap="bom",
        ),
        Route(
            "/v1/preview",
            None,
            {
                "root": _ROOT,
                "path": _FILE,
                "prefer": Param("enum", choices=("png", "dib"), default="png"),
                "nested": _NESTED,
                "render": Param("enum", choices=("auto", "never", "always"), default="auto"),
            },
            job="preview",
            deadline="preview",
            cap="preview",
        ),
        Route(
            "/v1/path-report",
            "path_report",
            {"root": _ROOT, "path": _FILE},
            job="path_report",
            deadline="path_report",
            cap="path_report",
        ),
        Route("/v1/catalog", "catalog", {}, deadline="catalog", cap="catalog"),
        Route(
            "/v1/where-used",
            "where_used",
            {
                "root": _ROOT,
                "path": _FILE,
                "configuration": _CONFIGURATION,
                "direct": Param("bool", default=False),
            },
            deadline="catalog",
            cap="catalog",
        ),
        Route(
            "/v1/search",
            "catalog_search",
            {
                "q": Param("text", required=True, max_len=1000),
                "limit": Param("int", low=1, high=500, default=100),
                "cursor": Param("cursor"),
                "sort": Param("enum", choices=("relevance", "name", "modified"), default="relevance"),
            },
            deadline="catalog",
            cap="catalog",
        ),
    )
}
CATALOG_KINDS = ("catalog", "where_used", "catalog_search")
# the worker job's parameters, from the route's query parameters
_JOB_PARAMS = {
    "/v1/document": ("nested",),
    "/v1/properties": ("view", "configuration", "nested"),
    "/v1/configurations": (),
    "/v1/components": ("configuration", "max_nodes", "max_depth", "flat"),
    "/v1/references": ("configuration",),
    "/v1/bom": (),  # Server.bom passes its own
    "/v1/preview": ("prefer", "nested"),
    "/v1/path-report": (),
}
# A model file's job and parameters on the routes that read model files (provisional); every
# other document route answers not_implemented for one.
_MODEL_JOBS = {
    "/v1/document": ("model_summary", "model_summary", ()),
    "/v1/properties": ("model_properties", "properties", ("view", "configuration")),
    "/v1/preview": ("model_preview", None, ("render",)),
}


# --------------------------------------------------------------------------- per-root state
class _RootState:
    """A configured root and its folder index: ``building``, ``ready`` or ``unavailable``."""

    def __init__(self, root) -> None:
        self.root = root
        self.state = "building"
        self.index = None
        self.root_dev: int | None = None
        self.error: str | None = None

    @property
    def id(self) -> str:
        return self.root.id

    @property
    def role(self) -> str:
        return self.root.role

    @property
    def recursive(self) -> bool:
        return self.root.recursive

    @property
    def index_partial(self) -> bool:
        return self.index is not None and self.index.partial is not None

    @property
    def documents(self) -> int | None:
        return self.index.documents if self.index is not None else None


def _frames(thread: threading.Thread) -> str:
    """Where a thread is, as module:function:line, without file paths."""
    frame = sys._current_frames().get(thread.ident or -1)
    chain = []
    while frame is not None and len(chain) < 40:
        chain.append(f"{frame.f_globals.get('__name__', '?')}:{frame.f_code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    return " < ".join(chain) or "-"


def _tb_summary(exc: BaseException) -> str:
    chain = [
        f"{f.f_globals.get('__name__', '?')}:{f.f_code.co_name}:{lineno}"
        for f, lineno in traceback.walk_tb(exc.__traceback__)
    ]
    return " > ".join(chain[-20:]) or "-"


# --------------------------------------------------------------------------- the server
class Server:
    """The service: bound when constructed, serving after :meth:`start` and
    :meth:`serve_forever`. ``pool`` is a worker pool to use instead of the one the
    service would create (tests pass one with test jobs; the CLI never does); the
    service closes a pool it created, and one it was given only when :meth:`shutdown`
    is asked to."""

    def __init__(self, config: ServeConfig, *, pool: WorkerPool | None = None) -> None:
        bind_host = check_bind(
            config.host, allow_remote=config.allow_remote, allowed_hosts=config.allowed_hosts
        )
        self.config = config
        self.tokens = TokenChecker(config.tokens)
        self._states = [_RootState(r) for r in config.roots]
        self._by_id = {s.id: s for s in self._states}
        self._pool = pool
        self._own_pool = pool is None
        self._slots = threading.BoundedSemaphore(config.in_flight)
        self._active: dict[int, threading.Thread] = {}
        self._active_cv = threading.Condition()
        self._failures: dict[str, deque] = {}
        self._fail_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._serving = False
        self.dispatched: deque = deque(maxlen=5000)  # host paths handed to workers, newest last
        self._catalog_path: str | None = None  # the catalog's database once its first scan finished
        self._catalog_name = ""
        self._catalog_thread: threading.Thread | None = None
        self._catalog_stop = threading.Event()
        # the last scans' catalog_scan data, newest last (a long-running service keeps a few)
        self.catalog_scans: deque = deque(maxlen=CATALOG_SCANS_KEPT)
        try:
            self.httpd = _HTTPServer((bind_host, config.port), self)
        except OSError as exc:  # the port is taken, or the address is not this machine's
            raise AddressUnavailableError(
                f"cannot listen on {bind_host} port {config.port}: {exc.strerror or exc}"
            ) from None
        self.host, self.port = self.httpd.server_address[:2]
        self._allowed = self._host_allowlist()

    # ------------------------------------------------------------------ life cycle
    def start(self) -> None:
        """Start the workers (unless a pool was given) and build each root's folder
        index in the background; requests for a root answer 503 until it is ready."""
        if self._pool is None:
            self._pool = WorkerPool(
                self.config.workers,
                timeout_s=max(self.config.deadlines.values()),
                memory_mb=self.config.worker_memory_mb,
                roots=[s.root.path for s in self._states],
                reader_message=False,
                refuse_hard_links=self.config.refuse_hard_links,
                max_file_bytes=self.config.max_file_bytes,
                max_result_bytes=max(self.config.response_caps.values()) + REPLY_MARGIN,
                log=LOG,
            )
        for s in self._states:
            threading.Thread(
                target=self._build_index, args=(s,), name=f"solidseas-index-{s.id}", daemon=True
            ).start()
        if self.config.catalog:
            self._catalog_thread = threading.Thread(
                target=self._catalog_loop, name="solidseas-catalog", daemon=True
            )
            self._catalog_thread.start()

    def wait_ready(self, timeout: float = 60.0) -> bool:
        """Whether every root's index finished building (ready or unavailable) in time."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if all(s.state != "building" for s in self._states):
                return True
            time.sleep(0.02)
        return False

    def serve_forever(self) -> None:
        self._serving = True
        self.httpd.serve_forever(poll_interval=0.5)

    def shutdown(self, *, budget_s: float | None = None, close_pool: bool = True) -> list[str]:
        """Stop accepting, let requests in flight finish within the budget, then close the
        worker pool (which ends a request still waiting on a worker). Returns a line for
        each request thread still running afterwards, as module:function:line."""
        budget = self.config.shutdown_budget_s if budget_s is None else budget_s
        if self._serving:
            self.httpd.shutdown()
        self.httpd.server_close()
        self._catalog_stop.set()  # a scan stops between files, before the workers go
        if self._catalog_thread is not None:
            self._catalog_thread.join(budget)
        self._drain(budget)
        if self._pool is not None and (self._own_pool or close_pool):
            self._pool.close()
        self._drain(1.0)
        with self._active_cv:
            return [f"{t.name}: {_frames(t)}" for t in self._active.values()]

    def close(self) -> None:
        """Shut down and close the worker pool if the service created it."""
        self.shutdown(close_pool=False)

    def _drain(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        with self._active_cv:
            while self._active and time.monotonic() < end:
                self._active_cv.wait(max(0.01, end - time.monotonic()))

    @property
    def pool(self) -> WorkerPool | None:
        return self._pool

    @property
    def url(self) -> str:
        shown = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{shown}:{self.port}/v1/"

    # ------------------------------------------------------------------ roots
    def _build_index(self, s: _RootState) -> None:
        started = time.monotonic()
        try:
            st = os.stat(s.root.path)  # a root may be a junction or a link (C6)
            if not os.path.isdir(s.root.path):
                raise NotADirectoryError(20, "the root is not a folder")
            s.root_dev = st.st_dev
            s.index = Gateway(allow_outside_roots=False).build_index(
                s.root, max_examined=self.config.index_max_examined, deadline=None
            )
            s.state = "ready"
            LOG.info(
                "root=%s index=ready documents=%d partial=%s ms=%d",
                s.id,
                s.index.documents,
                s.index.partial or "-",
                (time.monotonic() - started) * 1000,
            )
        except Exception as exc:  # the root is reported unavailable; the service goes on
            s.error = model.error_code(exc)
            s.state = "unavailable"
            LOG.warning("root=%s index=unavailable code=%s", s.id, s.error)

    def root_states(self) -> list[_RootState]:
        return list(self._states)

    # ------------------------------------------------------------------ the catalog
    def _catalog_pool(self) -> WorkerPool:
        """The catalog's own workers: few, below normal priority, with the service's limits.
        A scan never waits for a worker busy with a request (a wait would count as a timeout
        against the file), and a request never waits behind a scan."""
        from ..catalog import record
        from ..catalog.scan import DEFAULT_FILE_TIMEOUT, HASH_BASE_SECONDS

        return WorkerPool(
            max(1, min(CATALOG_WORKERS, self.config.workers)),
            timeout_s=max(DEFAULT_FILE_TIMEOUT, HASH_BASE_SECONDS),
            memory_mb=self.config.worker_memory_mb,
            roots=[s.root.path for s in self._states],
            reader_message=False,
            refuse_hard_links=self.config.refuse_hard_links,
            max_file_bytes=self.config.max_file_bytes,
            max_result_bytes=record.REPLY_LIMIT,
            priority="below_normal",
            log=LOG,
        )

    def _catalog_loop(self) -> None:
        """Scan the catalog of the roots now and every ``catalog_rescan_s`` seconds, with
        workers of its own, until the service stops. Logged with counts only."""
        from .. import catalog

        cat = None
        try:
            cat = catalog.open(Roots([x.root for x in self._states]), cache_dir=self.config.catalog_cache_dir)
            cat.configure(formats=self.config.formats)  # it indexes what the service reads, no more
        except Exception as exc:  # the service goes on without its catalog
            LOG.warning("catalog=unavailable code=%s", model.error_code(exc))
            if cat is not None:
                cat.close()
            return
        self._catalog_name = cat.name
        pool = None
        try:
            while not self._catalog_stop.is_set():
                started = time.monotonic()
                try:
                    if pool is None:
                        pool = self._catalog_pool()
                    data = cat.scan(pool=pool, cancel=self._catalog_stop)
                    self.catalog_scans.append(data)
                    if data["state"] != "cancelled":
                        self._catalog_path = cat.path
                    c = data["counts"]
                    LOG.info(
                        "catalog=scanned state=%s documents=%d read=%d errors=%d ms=%d",
                        data["state"],
                        c["seen"],
                        c["read_ok"],
                        c["read_errors"],
                        (time.monotonic() - started) * 1000,
                    )
                except Exception as exc:
                    LOG.warning("catalog=scan_failed code=%s", model.error_code(exc))
                self._catalog_stop.wait(self.config.catalog_rescan_s)
        finally:
            if pool is not None:
                pool.close()
            cat.close()

    def catalog_answer(
        self, route: Route, q: dict[str, Any], canonical, if_none_match: str | None
    ) -> "_Answer":
        """``/v1/catalog``, ``/v1/where-used`` and ``/v1/search``: read-only queries of the
        catalog, bounded by the route's deadline (the query is interrupted past it)."""
        from .. import catalog

        if not self.config.catalog:
            raise ServiceError("feature_disabled", "the catalog is off: start the service with --catalog")
        if self._catalog_path is None:
            raise ServiceError(
                "busy", "the catalog's first scan is still running", detail={"rule": "catalog_scanning"}
            )
        source = None
        if route.kind == "where_used":
            if q["root"] not in self._by_id:
                raise ServiceError("root_not_found", "no root has that id")
            parts = check_path_text(q["path"], want="file", extensions=self.catalog_extensions)
            source = {"root": q["root"], "path": "/".join(parts)}
        answer = _Answer(source=source, cap=self.config.response_caps[route.cap])
        deadline = time.monotonic() + self.config.deadlines[route.deadline]
        with self.slot():
            cat = catalog.Catalog(
                self._catalog_path, location="cache", name=self._catalog_name, roots=None, mode="r"
            )
            try:
                cat.con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
                try:
                    if route.kind == "catalog":
                        data = cat.status(paths=False)
                    elif route.kind == "where_used":
                        data = cat.where_used(
                            source["root"],
                            source["path"],
                            configuration=q.get("configuration"),
                            indirect=not q["direct"],
                            max_seconds=max(0.001, deadline - time.monotonic()),
                        )
                    else:
                        data = cat.search(q["q"], sort=q["sort"], limit=q["limit"], cursor=q.get("cursor"))
                except Exception as exc:
                    if time.monotonic() > deadline and type(exc).__name__ == "OperationalError":
                        raise WorkerTimeoutError("the catalog query did not finish in time") from None
                    raise
            finally:
                cat.close()
        if route.kind == "where_used":
            _fit_users(data, source, answer.cap)
        answer.json(model.envelope(route.kind, data, source=source))
        answer.etag = self.etag(route.kind, hashlib.sha256(answer.body).hexdigest())
        answer.not_modified_for(if_none_match)
        return answer

    def _ready(self, root_id: str) -> _RootState:
        s = self._by_id.get(root_id)
        if s is None:
            raise ServiceError("root_not_found", "no root has that id")
        if s.state == "building":
            raise ServiceError("busy", "the root's folder index is still being built")
        if s.state != "ready" or not os.path.isdir(s.root.path):
            raise ServiceError("root_unavailable", "the root folder is not available")
        return s

    # ------------------------------------------------------------------ guards
    def _host_allowlist(self) -> set[tuple[str, int]]:
        names: set[str] = set()
        try:
            addr = ipaddress.ip_address(self.host)
        except ValueError:
            addr = None
        if addr is not None and (addr.is_loopback or addr.is_unspecified):
            names.update(("localhost", "127.0.0.1") if addr.version == 4 else ("localhost", "::1"))
        out = {(n, self.port) for n in names}
        for entry in self.config.allowed_hosts:
            parts = urlsplit("//" + entry)
            if parts.hostname:
                out.add((parts.hostname, parts.port or self.port))
        return out

    def host_allowed(self, header: str | None) -> bool:
        if not header or len(header) > 255 or any(c in header for c in "/\\@?#") or not header.isprintable():
            return False
        try:
            parts = urlsplit("//" + header)
            port = parts.port
        except ValueError:  # "[::1" and other junk
            return False
        if not parts.hostname:
            return False
        return (parts.hostname, port if port is not None else 80) in self._allowed

    def too_many_failures(self, peer: str) -> bool:
        with self._fail_lock:
            q = self._failures.get(peer)
            if not q:
                return False
            while q and q[0] < time.monotonic() - 60:
                q.popleft()
            return len(q) > self.config.max_auth_failures

    def record_failure(self, peer: str) -> None:
        with self._fail_lock:
            if len(self._failures) > 10_000:
                self._failures.clear()
            self._failures.setdefault(peer, deque(maxlen=self.config.max_auth_failures * 4)).append(
                time.monotonic()
            )

    @contextlib.contextmanager
    def slot(self):
        if not self._slots.acquire(blocking=False):
            raise ServiceError("busy", "too many requests are being read; try again shortly")
        try:
            yield
        finally:
            self._slots.release()

    @contextlib.contextmanager
    def active(self):
        t = threading.current_thread()
        with self._active_cv:
            self._active[t.ident or 0] = t
        try:
            yield
        finally:
            with self._active_cv:
                self._active.pop(t.ident or 0, None)
                self._active_cv.notify_all()

    # ------------------------------------------------------------------ answers
    def etag(self, *parts: Any) -> str:
        text = "\x1f".join(str(p) for p in (__version__, *parts))
        return '"' + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:32] + '"'

    def call(self, job: str, params: dict[str, Any], deadline: float, cap: int):
        """Run ``job`` in a worker by ``deadline``. Its answer may be ``cap`` bytes (the
        route's) plus the margin: a longer one is refused before this process reads it."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerTimeoutError("the request's deadline passed before a worker was free")
        if "path" in params:
            self.dispatched.append(params["path"])
        try:
            return self._pool.call(job, params, timeout=remaining, max_result_bytes=cap + REPLY_MARGIN)
        except WorkerJobError as exc:
            if exc.code != "response_too_large":
                raise
            raise ServiceError(  # the route's own limit, as when this process refuses an answer
                "response_too_large", "the answer exceeds its size limit", detail={"limit": cap}
            ) from None

    def workers_alive(self) -> int | None:
        """How many worker processes are running, or None before the pool exists."""
        return self._pool.alive() if self._pool is not None else None

    @property
    def extensions(self) -> tuple[str, ...]:
        """The file extensions of the formats the service reads."""
        return registry.extensions(self.config.formats)

    @property
    def catalog_extensions(self) -> tuple[str, ...]:
        """The file extensions of the formats the service's catalog indexes: those it reads."""
        from ..catalog import record

        return record.indexed_extensions(record.indexed_formats(self.config.formats))

    def _model_route(self, route: Route, name: str, q: dict[str, Any]) -> tuple[str, str | None, tuple]:
        """The job, kind and job parameters of a document route for a model file."""
        spec = registry.by_extension(name)
        if route.path not in _MODEL_JOBS:
            raise UnsupportedOperationError(
                f"{route.path} reads SOLIDWORKS documents only",
                detail={"rule": "model_file", "value": spec.id if spec is not None else "unknown"},
            )
        if q.get("nested") is not None:
            raise InvalidArgumentError(
                "nested documents belong to SOLIDWORKS assemblies", detail={"parameter": "nested"}
            )
        return _MODEL_JOBS[route.path]

    def document(
        self, route: Route, q: dict[str, Any], canonical, started: float, if_none_match: str | None
    ) -> "_Answer":
        s = self._ready(q["root"])
        parts = check_path_text(q["path"], want="file", extensions=self.extensions)
        spec = registry.by_extension(parts[-1])
        job, kind_name, job_params = route.job, route.kind, _JOB_PARAMS[route.path]
        if spec is not None and spec.id != registry.SOLIDWORKS:
            job, kind_name, job_params = self._model_route(route, parts[-1], q)
        elif route.path == "/v1/preview" and q.get("render") == "always":
            raise UnsupportedOperationError(
                "a SOLIDWORKS document's preview is the one it stores",
                detail={"rule": "solidworks_render", "value": "solidworks"},
            )
        loc = locate(s.index, parts, want="file", root_dev=s.root_dev)
        source: dict[str, Any] = {"root": s.id, "path": loc.rel}
        if q.get("nested") is not None:
            source["nested"] = q["nested"]
        resolve = route.path == "/v1/references" and q.get("resolve")
        kind = kind_name or "preview"
        version = model.KINDS[kind_name].schema_version if kind_name else 1
        tag = self.etag(kind, version, s.id, loc.rel, loc.size, loc.mtime_ns, canonical)
        answer = _Answer(source=source, etag=tag, cap=self.config.response_caps[route.cap])
        # A resolved answer depends on every file under the roots, not on this one alone: its
        # tag is taken from the answer itself, after the search (below).
        if not resolve and answer.not_modified_for(if_none_match):
            return answer
        deadline = started + self.config.deadlines[route.deadline]
        params = {"path": loc.host, "within": s.root.path, "name": loc.name}
        params.update({k: q[k] for k in job_params if q.get(k) is not None})
        if resolve:
            params["resolution_input"] = True
        with self.slot():
            result = self.call(job, params, deadline, answer.cap)
            if route.path == "/v1/preview":
                return answer.image(result.payload or b"")
            data = result.data
            if resolve:
                if not isinstance(data, dict) or "references" not in data:
                    raise WorkerCrashedError("the worker's answer was not what the job returns")
                data = self._resolve(loc, data["references"], data.get("resolution_input"), deadline)
        answer.json(model.envelope(kind_name, data, source=source))
        if resolve:
            answer.etag = self.etag("resolved", hashlib.sha256(answer.body).hexdigest())
            answer.not_modified_for(if_none_match)
        return answer

    def bom(
        self, route: Route, q: dict[str, Any], canonical, started: float, if_none_match: str | None
    ) -> "_Answer":
        """``/v1/bom`` in three steps (C10): a worker reads what resolution needs from the
        assembly, this process resolves its references against every root, and a worker
        builds the BOM from that resolution, opening each component file it found
        within its root. The answer depends on every file under the roots, not on the
        assembly alone, so its tag is taken from the answer itself."""
        s = self._ready(q["root"])
        parts = check_path_text(q["path"], want="file", extensions=self.extensions)
        spec = registry.by_extension(parts[-1])
        if spec is not None and spec.id != registry.SOLIDWORKS:
            self._model_route(route, parts[-1], q)
        loc = locate(s.index, parts, want="file", root_dev=s.root_dev)
        source: dict[str, Any] = {"root": s.id, "path": loc.rel}
        columns = bom_mod.check_columns(q["columns"].split(",")) if q.get("columns") is not None else ()
        if q.get("part_number_property") is not None:
            bom_mod.check_property_name(q["part_number_property"], "part_number_property")
        answer = _Answer(source=source, cap=self.config.response_caps[route.cap])
        deadline = started + self.config.deadlines[route.deadline]
        base = {"path": loc.host, "within": s.root.path, "name": loc.name}
        with self.slot():
            got = self.call("resolution_input", base, deadline, answer.cap).data
            if not isinstance(got, dict) or "doc_type" not in got:
                raise WorkerCrashedError("the worker's answer was not what the job returns")
            payload = None
            if got["doc_type"] == "assembly":
                res = self._resolution(loc, got.get("resolution_input"), deadline)
                payload = bom_mod.resolution_payload(res)
            params = {
                **base,
                "configuration": q.get("configuration"),
                "type": q["type"],
                "columns": list(columns),
                "part_number_property": q.get("part_number_property"),
                "resolution": payload,
                "roots": [
                    {"id": x.root.id, "path": x.root.path, "recursive": x.root.recursive, "role": x.root.role}
                    for x in self._states
                ],
            }
            data = self.call(route.job, params, deadline, answer.cap).data
        answer.json(model.envelope(route.kind, data, source=source))
        answer.etag = self.etag("bom", hashlib.sha256(answer.body).hexdigest())
        answer.not_modified_for(if_none_match)
        return answer

    def _resolve(self, loc: Located, refs: dict, inp: Any, deadline: float) -> dict:
        """The ``references`` data ``refs`` with the resolution of :meth:`_resolution`."""
        return model.attach_resolution(refs, self._resolution(loc, inp, deadline))

    def _resolution(self, loc: Located, inp: Any, deadline: float):
        """Resolution in this process from the worker's reading (C10): every root walked
        again for this request, as Python's ``resolve_references`` walks them on each call,
        so files moved or copied since the service started are found where they are now;
        one batched identity read in a worker; then the rules. A root that cannot be
        walked is searched without, and the result says so (``root_unavailable``)."""

        def read(items: list[tuple[str, str]]) -> list[Identity]:
            try:
                for path, _within in items:
                    self.dispatched.append(path)
                result = self.call(
                    "identities",
                    {"items": [{"path": p, "within": w} for p, w in items]},
                    deadline,
                    self.config.response_caps["references"],
                )
                rows = (
                    result.data if isinstance(result.data, list) and len(result.data) == len(items) else None
                )
                if rows is None:
                    raise WorkerCrashedError("the identity job answered with the wrong shape")
            except (WorkerTimeoutError, WorkerCrashedError, WorkerJobError, ServiceError) as exc:
                return [Identity(None, error=model.error_code(exc))] * len(items)
            out = []
            for row in rows:
                row = row if isinstance(row, dict) else {}
                error = row.get("error")
                out.append(
                    Identity(
                        parse_creation_time(row.get("creation_time")),
                        row.get("source") if isinstance(row.get("source"), str) else None,
                        error if isinstance(error, str) and _SAFE_TOKEN.match(error) else None,
                    )
                )
            return out

        remaining = max(0.001, deadline - time.monotonic())
        gateway = Gateway(allow_outside_roots=False, deadline=deadline, identity_reader=read)
        res = resolve_references(
            ResolutionInput.from_json(inp, path=loc.host),
            Roots([x.root for x in self._states]),
            allow_outside_roots=False,
            max_examined=self.config.index_max_examined,
            max_seconds=remaining,
            gateway=gateway,
            skip_unavailable_roots=True,
        )
        return res

    def listing(
        self, route: Route, q: dict[str, Any], canonical, started: float, if_none_match: str | None
    ) -> "_Answer":
        s = self._ready(q["root"])
        if q["recursive"] and not s.recursive:
            raise InvalidArgumentError(
                "this root is served without its subfolders", detail={"parameter": "recursive"}
            )
        loc = locate(s.index, check_path_text(q["path"], want="folder"), want="folder", root_dev=s.root_dev)
        check_folder_within(loc.host, s.root.path)
        qhash = hashlib.sha256(
            repr([p for p in canonical if p[0] not in ("cursor", "limit")]).encode()
        ).hexdigest()[:16]
        after = _decode_cursor(q["cursor"], qhash) if q.get("cursor") is not None else None
        options = dict(
            recursive=q["recursive"],
            include=q["include"],
            max_entries=q["limit"],
            root_id=s.id,
            folder_rel=loc.rel,
            within=s.root.path,
            after=after,
            reader_message=False,
            formats=self._list_formats(q.get("formats")),
        )
        cap = self.config.response_caps[route.cap]
        with self.slot():  # the walk for the ETag counts as reading, too
            page = self.config.deadlines["list_page"] - (time.monotonic() - started)
            if page <= 0:
                raise WorkerTimeoutError("the listing's deadline passed")
            # the ETag comes from the directory entries alone: no file is opened for it
            fingerprint = Scan(loc.host, max_seconds=page, **options).fingerprint()
            answer = _Answer(
                source={"root": s.id, "path": loc.rel},
                etag=self.etag(
                    "listing", model.KINDS["listing"].schema_version, s.id, loc.rel, fingerprint, canonical
                ),
                cap=cap,
            )
            if answer.not_modified_for(if_none_match):
                return answer
            page = self.config.deadlines["list_page"] - (time.monotonic() - started)
            if page <= 0:
                raise WorkerTimeoutError("the listing's deadline passed")
            scan = Scan(
                loc.host,
                pool=self._pool,
                file_timeout=self.config.deadlines["list_file"],
                max_seconds=page,
                max_preview_data_bytes=max(1, cap - (2 << 20)),
                **options,
            )
            data = scan.listing(cursor=lambda rel: _encode_cursor(qhash, rel))
        if any(_transient(e) for e in data["entries"]):
            # The tag covers the directory entries, not how reading each file went: a page
            # with an entry that may read differently later (locked, timed out, a worker
            # that crashed) gets no tag, so no client can revalidate it into a 304.
            answer.etag = None
        return answer.json(model.envelope("listing", data, source=answer.source))

    def _list_formats(self, value: str | None) -> tuple[str, ...]:
        """The formats a listing asks for: SOLIDWORKS documents by default, ``all`` for every
        format the service reads, or format ids among those."""
        enabled = set(self.config.formats)
        if value is None:
            return (registry.SOLIDWORKS,) if registry.SOLIDWORKS in enabled else tuple(sorted(enabled))
        if value == "all":
            return tuple(sorted(enabled))
        asked = registry.select(value)
        if not asked <= enabled:
            raise InvalidArgumentError(
                "formats names a format this service was not started to read", detail={"parameter": "formats"}
            )
        return tuple(sorted(asked))


def _transient(entry: dict[str, Any]) -> bool:
    """Whether a listing entry failed in a way that may not happen again."""
    error = entry.get("error")
    return isinstance(error, dict) and (error.get("retryable") is True or error.get("code") in _TRANSIENT)


def _encode_cursor(qhash: str, rel: str) -> str:
    return base64.urlsafe_b64encode(f"{qhash}\n{rel}".encode()).rstrip(b"=").decode("ascii")


def _decode_cursor(text: str, qhash: str) -> str:
    bad = InvalidArgumentError("the cursor is not one this listing gave", detail={"parameter": "cursor"})
    if not _CURSOR.match(text):
        raise bad
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise bad from None
    got, sep, rel = raw.partition("\n")
    if not sep or got != qhash or not rel or len(rel) > 4096:
        raise bad
    return rel


def _fit_users(data: dict[str, Any], source: dict[str, Any] | None, cap: int | None) -> None:
    """Keep only as many of a where-used answer's users as fit in the route's size cap,
    the nearest first (they come sorted by depth), and mark the answer ``truncated``: a
    file used by thousands of assemblies still gets an answer. ``counts`` still counts
    them all."""
    if cap is None or len(model.dumps(model.envelope("where_used", data, source=source))) <= cap:
        return
    users = data["users"]
    data["truncated"] = True
    data["users"] = []
    room = cap - len(model.dumps(model.envelope("where_used", data, source=source)))
    kept = 0
    for u in users:
        room -= len(model.dumps(u)) + 1  # the user and the comma before the next
        if room < 0:
            break
        kept += 1
    data["users"] = users[:kept]


class _Answer:
    """One response being built: status, body, headers."""

    def __init__(self, *, source=None, etag: str | None = None, cap: int | None = None) -> None:
        self.source = source
        self.etag = etag
        self.cap = cap
        self.status = 200
        self.body = b""
        self.content_type: str | None = JSON_TYPE
        self.headers: list[tuple[str, str]] = []
        self.code: str | None = None
        self.detail: dict[str, Any] = {}
        self.close = False

    def not_modified_for(self, header: str | None) -> bool:
        if not header or not self.etag:
            return False
        tags = [t.strip().removeprefix("W/") for t in header.split(",")]
        if self.etag in tags or "*" in tags:
            self.status, self.body, self.content_type = 304, b"", None
            return True
        return False

    def json(self, envelope: dict[str, Any]) -> "_Answer":
        body = model.dumps(envelope).encode("ascii")
        if self.cap is not None and len(body) > self.cap:
            raise ServiceError(
                "response_too_large", "the answer exceeds its size limit", detail={"limit": self.cap}
            )
        self.body = body
        return self

    def image(self, data: bytes) -> "_Answer":
        if data.startswith(PNG_SIGNATURE):
            self.content_type = "image/png"
        elif data[:2] == b"BM" and len(data) > 54:
            self.content_type = "image/bmp"
        else:  # only a raster the service checked itself is ever served
            raise WorkerCrashedError("the preview is neither a PNG nor a BMP")
        if self.cap is not None and len(data) > self.cap:
            raise ServiceError(
                "response_too_large", "the image exceeds its size limit", detail={"limit": self.cap}
            )
        self.body = data
        return self

    def error(self, exc: BaseException) -> "_Answer":
        env = model.error_envelope(exc, source=self.source, reader_message=False)
        err = env["error"]
        self.code = err["code"]
        self.detail = err["detail"]
        self.status = model.ERROR_CODES[self.code].http_status or 500
        self.body = model.dumps(env).encode("ascii")
        self.content_type = JSON_TYPE
        self.etag = None
        if self.code == "unauthorized":
            self.headers.append(("WWW-Authenticate", 'Bearer realm="solidseas"'))
        if self.code == "method_not_allowed":
            self.headers.append(("Allow", "GET, HEAD"))
        if self.code in _RETRY_AFTER:
            self.headers.append(("Retry-After", _RETRY_AFTER[self.code]))
        return self


# --------------------------------------------------------------------------- HTTP plumbing
class _HeadReader:
    """The connection's input, for the request line and headers only: every request's
    head must arrive within one deadline, however slowly its bytes trickle in, its
    first byte within the idle deadline, and its headers within ``HEAD_BUDGET``
    bytes. Past the budget nothing more is read: ``http.client.LineTooLong``, which
    the request parser answers with 431."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()
        self._deadline: float | None = None
        self._idle_deadline: float | None = None
        self._head_bytes: int | None = None  # header bytes so far; None while on the request line
        self.received = 0  # bytes received on this connection, for diagnostics and tests
        self.started_head = False  # a byte of the current request arrived
        self.timed_out = False
        self.closed = False

    def start(self, seconds: float, idle: float | None = None) -> None:
        now = time.monotonic()
        self._deadline = now + seconds
        self._idle_deadline = None if idle is None else now + min(idle, seconds)
        self._head_bytes = None
        self.started_head = bool(self._buf)
        self.timed_out = False

    def _take(self, n: int) -> bytes:
        out = bytes(self._buf[:n])
        del self._buf[:n]
        if self._head_bytes is None:
            self._head_bytes = 0  # the request line has its own limit (MAX_URL, 414)
        else:
            self._head_bytes += len(out)
            if self._head_bytes > HEAD_BUDGET:
                raise http.client.LineTooLong("the request's headers")
        return out

    def readline(self, limit: int = -1) -> bytes:
        while True:
            i = self._buf.find(b"\n")
            if i >= 0 and (limit < 0 or i < limit):
                return self._take(i + 1)
            if 0 <= limit <= len(self._buf):
                return self._take(limit)
            if self._head_bytes is not None and self._head_bytes + len(self._buf) > HEAD_BUDGET:
                raise http.client.LineTooLong("the request's headers")  # never buffer past the limit
            deadline = self._deadline
            if not self.started_head and self._idle_deadline is not None:
                deadline = self._idle_deadline
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                self.timed_out = True
                raise TimeoutError("the request did not arrive in time")
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(8192)
            except TimeoutError:
                self.timed_out = True
                raise
            if not chunk:
                return self._take(len(self._buf))
            self.received += len(chunk)
            self.started_head = True
            self._buf += chunk

    def read(self, n: int = -1) -> bytes:  # the service reads no bodies; only what is buffered
        return self._take(len(self._buf) if n < 0 else min(n, len(self._buf)))

    def close(self) -> None:
        self.closed = True


def _security_head(status: int, reason: str, body: bytes, rid: str) -> bytes:
    lines = [f"HTTP/1.1 {status} {reason}", f"Content-Type: {JSON_TYPE}", f"Content-Length: {len(body)}"]
    lines += [f"{k}: {v}" for k, v in SECURITY_HEADERS]
    lines += ["Server: solidseas", "Retry-After: 1", "Connection: close", f"X-Request-Id: {rid}"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


class _Refuser:
    """Answers connections over the cap with 503 ``busy``, in one background thread with a
    short queue: the reply is sent, the client's bytes are drained for a moment so the
    close does not reset the connection before the reply is read, and when the queue is
    full a connection is just closed. A flood never stalls the accept loop."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=64)
        threading.Thread(target=self._loop, name="solidseas-refuser", daemon=True).start()

    def refuse(self, request: socket.socket) -> None:
        try:
            self._queue.put_nowait(request)
        except queue.Full:
            with contextlib.suppress(OSError):
                request.close()

    def _loop(self) -> None:
        body = model.dumps(model.error_envelope(ServiceError("busy", "too many open connections"))).encode()
        reply = _security_head(503, "Service Unavailable", body, "-")
        while True:
            request = self._queue.get()
            try:
                request.settimeout(0.5)
                request.sendall(reply)
                request.shutdown(socket.SHUT_WR)
                # read what the client sent, briefly, so the close does not reset the
                # connection before the reply is read; an idle client is not waited for
                end = time.monotonic() + REFUSED_DRAIN_S
                while (left := end - time.monotonic()) > 0:
                    request.settimeout(left)
                    if not request.recv(65536):
                        break
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    request.close()


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"  # on Windows it would let another program take the port

    def __init__(self, address: tuple[str, int], app: Server) -> None:
        self.app = app
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        self._connections = threading.BoundedSemaphore(app.config.max_connections)
        self._refuser = _Refuser()
        super().__init__(address, _Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind asks DNS for the bound name (socket.getfqdn): an outbound
        # lookup the service never needs. Bind exclusively on Windows.
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        import socketserver

        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]

    def process_request(self, request, client_address) -> None:
        if not self._connections.acquire(blocking=False):
            self._refuser.refuse(request)
            LOG.info("rid=- client=- peer=%s status=503 code=busy reason=connections", _peer(client_address))
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connections.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connections.release()

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        LOG.error(
            "connection error peer=%s type=%s at %s",
            _peer(client_address),
            type(exc).__name__,
            _tb_summary(exc) if exc is not None else "-",
        )


def _peer(client_address) -> str:
    try:
        host = str(client_address[0])
    except (IndexError, TypeError):
        return "-"
    return host if re.fullmatch(r"[0-9A-Fa-f.:%a-zA-Z]{1,64}", host) else "-"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "solidseas"
    sys_version = ""

    # ------------------------------------------------------------------ connection
    def setup(self) -> None:
        super().setup()
        self.app: Server = self.server.app
        self.rfile.close()  # the head is read through _HeadReader; bodies are never read
        self.rfile = _HeadReader(self.connection)
        self._served = 0

    def version_string(self) -> str:
        return "solidseas"

    def handle_one_request(self) -> None:
        self._served += 1
        self.rfile.start(self.app.config.read_timeout, self.app.config.idle_timeout)
        self._rid = f"{next(self.app._ids):08x}"
        self._t0 = time.monotonic()
        self._logged = False
        self._client = "-"
        self._route = "-"
        self._root = "-"
        super().handle_one_request()
        if self.rfile.timed_out and (self.rfile.started_head or self._served == 1):
            # a head that never arrived in full, or a connection that never sent one: the
            # trace a slow sender or a flood of idle connections leaves (an idle kept-alive
            # connection closing after a served request is not news)
            LOG.info(
                "rid=%s client=- peer=%s status=- code=timeout rule=%s",
                self._rid,
                _peer(self.client_address),
                "head_deadline" if self.rfile.started_head else "idle_connection",
            )
        if self._served >= self.app.config.max_requests_per_connection:
            self.close_connection = True

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        if self.request_version == "HTTP/0.9":  # its answer would be a bare body (see _send)
            self._refuse(
                ServiceError("invalid_argument", "HTTP/0.9 is not served", detail={"rule": "http_version"})
            )
            return False
        if not hasattr(self, "do_" + self.command):  # an unknown method: the Host check first
            self._refuse_method()
            return False
        if len(self.path) > MAX_URL:
            self.send_error(414)
            return False
        size = sum(len(k) + len(v) + 4 for k, v in self.headers.items())
        if size > MAX_HEADER_BYTES:
            self.send_error(431)
            return False
        self.connection.settimeout(self.app.config.write_timeout)
        return True

    def handle_expect_100(self) -> bool:
        return True  # no 100 Continue: the service accepts no body, and refuses one below

    # ------------------------------------------------------------------ logging: our own lines only
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
        pass  # the base class would log the request line, query string included

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        pass

    def log_error(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _log(self, answer: _Answer) -> None:
        if self._logged:
            return
        self._logged = True
        method = self.command if isinstance(self.command, str) and _METHOD.match(self.command) else "-"
        rule = answer.detail.get("rule") if answer.detail else None
        index = answer.detail.get("component_index") if answer.detail else None
        LOG.info(
            "rid=%s client=%s peer=%s method=%s route=%s root=%s status=%d code=%s rule=%s "
            "component=%s ms=%d bytes=%d",
            self._rid,
            self._client,
            _peer(self.client_address),
            method,
            self._route,
            self._root,
            answer.status,
            answer.code or "-",
            rule if isinstance(rule, str) and _SAFE_TOKEN.match(rule) else "-",
            index if isinstance(index, int) and not isinstance(index, bool) else "-",
            (time.monotonic() - getattr(self, "_t0", time.monotonic())) * 1000,
            len(answer.body),
        )

    # ------------------------------------------------------------------ errors from the base class
    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        mapped = {414: "uri_too_long", 431: "headers_too_large", 501: "method_not_allowed"}.get(
            int(code), "invalid_argument" if 400 <= int(code) < 500 or int(code) == 505 else "internal"
        )
        answer = _Answer().error(ServiceError(mapped, "the request was refused"))
        answer.close = True
        self._send(answer, head=self.command == "HEAD")

    def _send(self, answer: _Answer, *, head: bool) -> None:
        if getattr(self, "request_version", None) == "HTTP/0.9":
            # an HTTP/0.9 response is a bare body: answer as 1.1, with every header, and close
            self.request_version = "HTTP/1.1"
            answer.close = True
        if answer.close:
            self.close_connection = True
        try:
            self.send_response(answer.status)
            for k, v in SECURITY_HEADERS:
                self.send_header(k, v)
            self.send_header("X-Request-Id", getattr(self, "_rid", "-"))
            if answer.content_type:
                self.send_header("Content-Type", answer.content_type)
            if answer.etag:
                self.send_header("ETag", answer.etag)
            for k, v in answer.headers:
                self.send_header(k, v)
            if answer.status != 304:
                self.send_header("Content-Length", str(len(answer.body)))
            if answer.close:
                self.send_header("Connection", "close")
            self.end_headers()
            if not head and answer.status != 304:
                self.wfile.write(answer.body)
        finally:
            self._log(answer)

    # ------------------------------------------------------------------ methods
    def do_GET(self) -> None:
        self._dispatch(head=False)

    def do_HEAD(self) -> None:
        self._dispatch(head=True)

    def _refuse_method(self) -> None:
        try:
            self._check_host()  # the Host check comes first on every request
            raise ServiceError("method_not_allowed", "only GET and HEAD are accepted")
        except ServiceError as exc:
            self._refuse(exc)

    def _refuse(self, exc: ServiceError) -> None:
        answer = _Answer().error(exc)
        answer.close = True  # any body it sent is left unread
        self._send(answer, head=False)

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _refuse_method

    def _check_host(self) -> None:
        hosts = self.headers.get_all("Host") or ()
        if len(hosts) != 1 or not self.app.host_allowed(hosts[0]):
            raise ServiceError("forbidden_host", "the Host header names a host this service does not serve")

    def _guard(self) -> None:
        self._check_host()
        if self.headers.get("Origin") is not None:
            raise ServiceError("forbidden_origin", "cross-site browser requests are refused")
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site.strip().lower() not in ("none", "same-origin"):
            raise ServiceError("forbidden_origin", "cross-site browser requests are refused")
        length = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding") is not None or (
            length is not None and length.strip() != "0"
        ):
            raise ServiceError("invalid_argument", "a request body is not accepted", detail={"rule": "body"})

    def _authenticate(self) -> None:
        peer = _peer(self.client_address)
        if self.app.too_many_failures(peer):
            raise ServiceError("too_many_failures", "too many failed attempts; wait a minute")
        values = self.headers.get_all("Authorization") or []
        name = self.app.tokens.check(values[0]) if len(values) == 1 else None
        if name is None:
            self.app.record_failure(peer)
            raise ServiceError("unauthorized", "a valid bearer token is required")
        self._client = name

    def _dispatch(self, *, head: bool) -> None:
        app = self.app
        answer = _Answer()
        with app.active():
            try:
                self._guard()
                route_path, _, raw_query = self.path.partition("?")
                route = ROUTES.get(route_path)
                if route is not None:
                    self._route = route.path
                if route is None or route.auth:
                    self._authenticate()
                if route is None:
                    raise ServiceError("not_found", "no such route", detail={"rule": "route"})
                if "root" in route.params:  # until the query parses, the source is what it names
                    answer.source = requested_location(raw_query, nested="nested" in route.params)
                q, canonical = parse_query(raw_query, route.params)
                if q.get("root") in app._by_id:
                    self._root = q["root"]
                if "root" in route.params:  # an error names what was asked for, as the CLI does
                    answer.source = {"root": q["root"], "path": q["path"]}
                    if q.get("nested") is not None:
                        answer.source["nested"] = q["nested"]
                answer = self._answer(route, q, canonical)
            except Exception as exc:
                if (
                    isinstance(exc, (ServiceError, InvalidArgumentError))
                    and exc.detail
                    and exc.detail.get("rule") == "body"
                ):
                    answer.close = True
                if model.error_code(exc) == "internal" and not isinstance(
                    exc, (WorkerJobError, ServiceError)
                ):
                    LOG.error(
                        "rid=%s internal error type=%s at %s", self._rid, type(exc).__name__, _tb_summary(exc)
                    )
                answer.error(exc)
            self._send(answer, head=head)

    def _answer(self, route: Route, q: dict[str, Any], canonical) -> _Answer:
        app = self.app
        inm = self.headers.get("If-None-Match")
        if route.kind == "health":
            if app.workers_alive() == 0:  # every worker lost: nothing can be read until one is back
                raise ServiceError("busy", "no worker process is running", detail={"rule": "no_workers"})
            return _Answer().json(model.envelope("health", model.build_health()))
        if route.kind == "identity":
            # The address and port this connection reached, as this process sees them: a
            # program that forwards the question from another address or port gets a proof
            # for this one, which its client will not accept (8.16).
            host, port = self.connection.getsockname()[:2]
            address = proof_address(host)
            proof = app.tokens.identity(q["client"], q["nonce"], address, port)
            data = model.build_identity(
                scheme=IDENTITY_SCHEME,
                client=q["client"],
                nonce=q["nonce"],
                address=address,
                port=port,
                proof=proof,
            )
            return _Answer().json(model.envelope("identity", data))
        if route.kind == "version":
            return _Answer().json(model.envelope("version", model.build_version()))
        if route.kind == "roots":
            return _Answer().json(model.envelope("roots", model.build_roots(app.root_states())))
        if route.kind == "listing":
            return app.listing(route, q, canonical, self._t0, inm)
        if route.kind == "bom":
            return app.bom(route, q, canonical, self._t0, inm)
        if route.kind in CATALOG_KINDS:
            return app.catalog_answer(route, q, canonical, inm)
        return app.document(route, q, canonical, self._t0, inm)


# --------------------------------------------------------------------------- running
def configure_logging() -> None:
    """Send the service's log lines to standard error, in UTC, unless the caller set up
    logging for ``solidseas.serve`` already."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


class _Stop(BaseException):
    """A stop signal arrived."""


def run_until_signalled(server: Server) -> None:  # pragma: no cover - runs in a service process
    """Serve until SIGINT, SIGTERM or Ctrl+Break, then shut down within the budget and
    end the process with ``os._exit`` (````): exit 0, or 1
    when a request thread was still stuck, after logging where it was."""

    def stop(signum, frame) -> None:
        raise _Stop()

    signals = [getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, n)]
    for sig in signals:
        signal.signal(sig, stop)
    try:
        server.serve_forever()
    except (_Stop, KeyboardInterrupt):
        pass
    for sig in signals:
        signal.signal(sig, signal.SIG_IGN)
    LOG.info("stopping: waiting up to %.1f s for requests in flight", server.config.shutdown_budget_s)
    stuck = server.shutdown(close_pool=True)
    for line in stuck:
        LOG.error("still running at exit: %s", line)
    LOG.info("stopped")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(1 if stuck else 0)


__all__ = [
    "CATALOG_KINDS",
    "DEFAULT_CAPS",
    "DEFAULT_DEADLINES",
    "DEFAULT_PORT",
    "ROUTES",
    "Route",
    "SECURITY_HEADERS",
    "ServeConfig",
    "Server",
    "check_bind",
    "configure_logging",
    "default_workers",
    "run_until_signalled",
]
