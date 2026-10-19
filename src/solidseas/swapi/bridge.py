"""The Python side of ``SolidSeas.SwBridge.exe``, the process that calls SOLIDWORKS.

The bridge is a small C# program (``SwBridge/`` next to this module) whose main
thread is a single-threaded apartment that owns every SOLIDWORKS object. This
module starts it, speaks its protocol and keeps the timeouts, so that a call
stuck inside SOLIDWORKS can never hang the Python process:

* **A Job Object.** On Windows the bridge is put in a Job Object with
  kill-on-close as soon as it starts, before it is sent anything. The
  ``SLDWORKS.exe`` it starts later inherits that job, and the bridge also puts
  it in a job of its own. Closing or terminating the job ends the bridge and its
  SOLIDWORKS together, and the job closes by itself if this process dies.
  Elsewhere (the fake bridge in the tests) the bridge leads its own process
  group, which is killed instead.
* **JSON lines.** One request per line on the bridge's standard input
  (``{"id": 7, "op": "save_copy", "args": {...}, "timeout_s": 600}``) and one
  reply per line on its standard output (``{"id": 7, "ok": true, "result":
  {...}}`` or ``{"id": 7, "ok": false, "error": {"code": ..., "message":
  ...}}``). Lines without an ``id`` are events (``{"event": "document", ...}``).
  A request line the bridge would refuse as too long is refused here, before it
  is sent.
* **A timeout on every request**, more than 0 and at most a day, the range the
  bridge accepts. :meth:`Bridge.request` waits for its reply up to its timeout.
  When the time is up it ends the job, which ends the bridge and the SOLIDWORKS
  it started, waits until every process in the job is gone, and raises
  :class:`BridgeTimeoutError`. Requests waiting at that moment, and any made
  later, fail with :class:`BridgeExitedError`. Start another :class:`Bridge` to
  carry on.
* **Events never hold the replies.** The thread that reads the bridge's output
  only queues an event; listeners run on a thread of their own. SOLIDWORKS waits
  for the bridge's event handlers, and they wait for nobody, so a slow listener
  can never stall SOLIDWORKS or a reply.
* **A dialog says why.** A request that times out while SOLIDWORKS shows a
  dialog (a ``window`` event with ``"action": "left"`` since it was sent) raises
  :class:`BridgeTimeoutError` naming it, with the events in ``details["dialogs"]``.

Call it from a worker thread, never from a Qt thread. ``docs/ARCHITECTURE.md``
section 6 has the design; the swapi ``README.md`` lists the operations.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from ..helpers import (
    EXIT_WAIT_S,
    MAX_LINE_BYTES,
    READY_TIMEOUT_S,
    Helper,
    HelperError,
    HelperExitedError,
    HelperRequestError,
    HelperTimeoutError,
)

PROTOCOL = 1
EXE_NAME = "SolidSeas.SwBridge.exe"
ENV_BRIDGE = "SOLIDSEAS_SWBRIDGE"
DEFAULT_SOLIDWORKS_EXE = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe")

# Seconds each operation may take before the bridge, and its SOLIDWORKS, are ended.
DEFAULT_TIMEOUTS: dict[str, float] = {
    "hello": 15.0,
    "start_solidworks": 360.0,
    "solidworks_info": 60.0,
    "new_document": 120.0,
    "open_document": 300.0,
    "document_info": 60.0,
    "list_features": 120.0,
    "save_copy": 600.0,
    "close_document": 120.0,
    "watch_document": 60.0,
    "unwatch_document": 60.0,
    "mass_properties": 600.0,
    "native_check": 900.0,
    "test_session_native_check": 900.0,
    "test_session_open": 600.0,
    "test_session_new_part": 300.0,
    "import_file": 600.0,
    "exit_solidworks": 180.0,
    "shutdown": 180.0,
}
HARD_LIMIT_S = 600.0  # any other operation
MAX_TIMEOUT_S = 86400.0  # the longest timeout the bridge accepts
MAX_REQUEST_CHARS = 1 << 20  # a request line, in UTF-16 code units, as the bridge counts

_WINDOWS = sys.platform == "win32"
_HERE = Path(__file__).resolve().parent
if _WINDOWS:
    from ..helpers import _Job  # noqa: F401 (the tests reach the bridge's job through this module)


class BridgeError(HelperError):
    """Base class for bridge failures. ``code`` is a protocol error code, ``op`` the request."""


class BridgeNotFoundError(BridgeError, FileNotFoundError):
    """No ``SolidSeas.SwBridge.exe`` was found or given."""

    code = "not_found"


class BridgeTimeoutError(BridgeError, HelperTimeoutError):
    """A request had no reply in time; the bridge and the SOLIDWORKS it started were ended."""

    code = "timeout"


class BridgeExitedError(BridgeError, HelperExitedError):
    """The bridge is not running: it crashed, exited, or was ended after a timeout."""

    code = "bridge_exited"


class BridgeRequestError(BridgeError, HelperRequestError):
    """The bridge answered the request with an error (``code``, ``details``, ``hresult``)."""


def _dialog_note(dialogs: list[dict]) -> str:
    """``" while SOLIDWORKS showed a dialog (title: text)"`` for the dialogs given, or nothing."""
    if not dialogs:
        return ""

    def one(d: dict) -> str:
        parts = (str(d.get(k) or "").strip() for k in ("title", "text"))
        return ": ".join(p for p in parts if p)[:200] or "untitled"

    listed = "; ".join(one(d) for d in dialogs[:3])
    if len(dialogs) > 3:
        listed += f"; and {len(dialogs) - 3} more"
    what = "a dialog" if len(dialogs) == 1 else f"{len(dialogs)} dialogs"
    return f" while SOLIDWORKS showed {what} ({listed})"


def find_bridge(explicit: str | os.PathLike | None = None) -> Path | None:
    """Where ``SolidSeas.SwBridge.exe`` is, or None.

    In order: ``explicit``; the ``SOLIDSEAS_SWBRIDGE`` environment variable;
    next to the running executable when SolidSeas is frozen (the viewer build
    puts it beside ``SolidSeasViewer.exe``); ``dist`` in a source checkout,
    where ``scripts/build-bridge.ps1`` writes it.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get(ENV_BRIDGE)
    if env:
        return Path(env)
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / EXE_NAME)
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            candidates.append(Path(bundle) / EXE_NAME)
    candidates.append(_HERE.parents[2] / "dist" / EXE_NAME)
    for c in candidates:
        if c.is_file():
            return c
    return None


def interop_folder(solidworks_exe: str | os.PathLike | None = None) -> Path:
    """The SOLIDWORKS API redistributables folder for an installation (``<install>\\api\\redist``)."""
    exe = Path(solidworks_exe) if solidworks_exe else DEFAULT_SOLIDWORKS_EXE
    return exe.parent / "api" / "redist"


class Bridge(Helper):
    """One running ``SolidSeas.SwBridge.exe`` and the conversation with it, a
    :class:`~solidseas.helpers.Helper` (module notes).

    ``exe`` is the bridge (default: :func:`find_bridge`); ``solidworks_exe``
    only chooses where the SOLIDWORKS interop assemblies are loaded from.
    ``command`` replaces the whole command line, for a stand-in bridge in tests.
    ``on_event`` is called with every event line, in order, on a thread of its
    own, never the one that reads replies.
    """

    Error = BridgeError
    TimeoutError = BridgeTimeoutError
    ExitedError = BridgeExitedError
    RequestError = BridgeRequestError
    ended_words = "the bridge and the SOLIDWORKS it started were ended"

    def __init__(
        self,
        exe: str | os.PathLike | None = None,
        *,
        solidworks_exe: str | os.PathLike | None = None,
        test_ops: bool = False,
        test_session: bool = False,
        command: list[str] | None = None,
        ready_timeout: float = READY_TIMEOUT_S,
        on_event: Callable[[dict], None] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if command is None:
            found = find_bridge(exe)
            if found is None or not found.is_file():
                raise BridgeNotFoundError(
                    f"{EXE_NAME} not found; build it with scripts/build-bridge.ps1 or "
                    f"python -m solidseas.swapi build, or set {ENV_BRIDGE}"
                )
            command = [str(found), "--interop", str(interop_folder(solidworks_exe))]
            if test_ops:
                command.append("--test-ops")
            if test_session:
                command.append("--test-session")
        super().__init__(
            command,
            label="the bridge",
            protocol=PROTOCOL,
            ready_timeout=ready_timeout,
            on_event=on_event,
            env=env,
            timeouts=DEFAULT_TIMEOUTS,
            hard_limit=HARD_LIMIT_S,
            thread_name="swbridge",
        )

    def max_request_chars(self) -> int:
        return MAX_REQUEST_CHARS  # read when asked, so a test can change it

    def dialog_note(self, dialogs: list[dict]) -> str:
        return _dialog_note(dialogs)

    def __enter__(self) -> Bridge:
        return self


__all__ = [
    "DEFAULT_TIMEOUTS",
    "EXE_NAME",
    "EXIT_WAIT_S",
    "HARD_LIMIT_S",
    "MAX_LINE_BYTES",
    "MAX_REQUEST_CHARS",
    "MAX_TIMEOUT_S",
    "PROTOCOL",
    "READY_TIMEOUT_S",
    "Bridge",
    "BridgeError",
    "BridgeExitedError",
    "BridgeNotFoundError",
    "BridgeRequestError",
    "BridgeTimeoutError",
    "find_bridge",
    "interop_folder",
]
