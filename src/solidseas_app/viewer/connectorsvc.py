"""The connector: other apps on this PC read the open folder through SolidSeas.

Settings > Connector (:mod:`.connectorpage`) has two parts. This module holds what runs
behind them; it makes no widget.

**The local API.** With "Let other apps on this PC read the open folder" on,
:class:`ConnectorService` runs the REST service (``solidseas serve``, ``docs/API.md``
section 8) as a child process: this executable with ``--cli serve`` when frozen, else
``python -m solidseas serve``. It binds 127.0.0.1 alone, on the page's port, with the
open folder as its one root (id ``folder``), and with ``--json`` so the ready line names
the port it bound. The token file sits in the ``Connector`` folder beside the viewer's
settings file; the service creates it, and nothing here reads it. The service follows the
open folder (it starts again when another folder is opened) and stops when the option is
turned off or the window closes: SIGTERM, or Ctrl+Break on Windows, as the service
expects, and a kill only when it has not ended after :data:`STOP_WAIT_S` seconds. On
Linux it also dies with the viewer (``PR_SET_PDEATHSIG``), and on Windows it is held in a
Job Object that ends it when the viewer's process ends, so no service outlives the viewer.

**AI apps.** :func:`mcp_config` is the block an MCP client such as Claude Desktop needs to
start ``solidseas mcp`` over the open folder itself (``docs/MCP.md``). SolidSeas writes it
into no other app's files; the person copies it.

The settings are the ``[Connector]`` section of the viewer's settings file: off, port 8765,
unless the file says otherwise.
"""

from __future__ import annotations

import atexit
import collections
import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

SECTION = "connector"  # the settings file's [Connector] section; names are read in lower case
SHARE_KEY, PORT_KEY = "share_open_folder", "port"
DEFAULT_PORT = 8765
MIN_PORT, MAX_PORT = 1024, 65535
ROOT_ID = "folder"
BIND = "127.0.0.1"
TOKEN_FOLDER = "Connector"
TOKEN_NAME = "serve-tokens"
MCP_NAME = "solidseas-files"
STOP_WAIT_S = 5.0  # the service waits up to 5 s for requests in flight, then ends itself
STDERR_LINES = 20  # of the service's standard error, kept for the details box
MAX_OUTPUT_CHARS = 64 * 1024  # of its standard output after the ready line

OFF, NO_FOLDER, STARTING, RUNNING, FAILED = "off", "no_folder", "starting", "running", "failed"


@dataclass(frozen=True)
class ConnectorSettings:
    """The Connector page's choices. ``ConnectorSettings()`` is every default."""

    share: bool = False
    port: int = DEFAULT_PORT


def load_settings(store) -> ConnectorSettings:
    """The ``[Connector]`` section of ``store``: a value that is not valid gives its default."""
    values = store.load_section(SECTION)
    share = (values.get(SHARE_KEY) or "").strip().lower() in ("true", "1", "yes", "on")
    port = DEFAULT_PORT
    raw = (values.get(PORT_KEY) or "").strip()
    if raw.isdigit() and MIN_PORT <= int(raw) <= MAX_PORT:
        port = int(raw)
    return ConnectorSettings(share=share, port=port)


def save_settings(store, settings: ConnectorSettings) -> bool:
    return store.save_section(
        SECTION, {SHARE_KEY: "true" if settings.share else "false", PORT_KEY: str(settings.port)}
    )


# --------------------------------------------------------------------------- command lines
def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def program(*, is_frozen: bool | None = None, executable: str | None = None) -> list[str]:
    """How this program runs the ``solidseas`` command line: this executable with
    ``--cli`` when frozen, else Python with ``-m solidseas``."""
    exe = executable or sys.executable
    if frozen() if is_frozen is None else is_frozen:
        return [exe, "--cli"]
    return [exe, "-m", "solidseas"]


def service_command(folder: str, port: int, token_file: str, *, base: list[str] | None = None) -> list[str]:
    return [
        *(base or program()),
        "serve",
        "--root",
        f"{ROOT_ID}={folder}",
        "--bind",
        BIND,
        "--port",
        str(port),
        "--token-file",
        token_file,
        "--json",
    ]


def mcp_config(folder: str, *, is_frozen: bool | None = None, executable: str | None = None) -> str:
    """The ``mcpServers`` block an MCP client needs to read ``folder`` through
    ``solidseas mcp``, as indented JSON."""
    command, *args = program(is_frozen=is_frozen, executable=executable)
    entry = {"command": command, "args": [*args, "mcp", "--root", f"{ROOT_ID}={folder}"]}
    return json.dumps({"mcpServers": {MCP_NAME: entry}}, indent=2, ensure_ascii=False)


def token_file_path(settings_path: str | None) -> str:
    """The service's token file: ``Connector\\serve-tokens`` beside the viewer's settings
    file, else in SolidSeas' own data folder (a store kept in memory has no file)."""
    if settings_path:
        base = os.path.dirname(os.path.abspath(settings_path))
    else:
        from ..extensions import data_dir

        base = data_dir()
    return os.path.join(base, TOKEN_FOLDER, TOKEN_NAME)


def powershell_example(token_file: str, port: int) -> str:
    """A PowerShell example that reads the token from the file into a variable and lists
    the roots: the token never appears on a command line."""
    quoted = "'" + token_file.replace("'", "''") + "'"
    return (
        f"$line = Get-Content -LiteralPath {quoted} | Where-Object {{ $_ -like 'default:*' }}\n"
        '$auth = @{ Authorization = "Bearer " + $line.Substring(8) }\n'
        f'Invoke-RestMethod -Headers $auth "http://{BIND}:{port}/v1/roots"\n'
    )


# --------------------------------------------------------------------------- the child process
_LIVE: set[Any] = set()  # services running, ended at exit should the window not have


@atexit.register
def _end_live() -> None:  # pragma: no cover - at exit
    for proc in list(_LIVE):
        try:
            proc.kill()
        except Exception:
            pass


def _posix_child() -> None:  # pragma: no cover - runs in the child before exec
    if sys.platform.startswith("linux"):
        try:
            import ctypes

            ctypes.CDLL(None).prctl(1, int(signal.SIGKILL))  # PR_SET_PDEATHSIG: end with the viewer
        except Exception:
            pass


def _has_console() -> bool:  # pragma: no cover - Windows
    import ctypes

    return bool(ctypes.windll.kernel32.GetConsoleWindow())


def launch(argv: list[str]) -> Any:
    """Start the service: a ``subprocess.Popen`` with text pipes for its standard output
    and error, in a process group of its own so Ctrl+Break reaches it alone."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "close_fds": True,
    }
    if sys.platform == "win32":  # pragma: no cover - Windows
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        if frozen() or not _has_console():
            flags |= subprocess.CREATE_NO_WINDOW  # no console window of its own
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _posix_child
    proc = subprocess.Popen(argv, **kwargs)
    if sys.platform == "win32":  # pragma: no cover - Windows
        try:
            from solidseas.workers import _JobObject  # type: ignore[attr-defined]

            job = _JobObject(256, None)  # its workers' own Job Object nests inside this one
            job.assign(proc.pid)
            proc._solidseas_job = job  # closed with the process; until then it holds the child
        except Exception:
            pass
    return proc


def stop_process(proc: Any, wait_s: float = STOP_WAIT_S) -> None:
    """End ``proc`` the way the service expects (Ctrl+Break on Windows, SIGTERM elsewhere),
    and kill it only when it has not ended after ``wait_s`` seconds."""
    if proc.poll() is None:
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
        except (OSError, ValueError):
            pass  # a viewer with no console cannot send Ctrl+Break: the kill below ends it
        try:
            proc.wait(wait_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(wait_s)
    job = getattr(proc, "_solidseas_job", None)
    if job is not None:  # pragma: no cover - Windows
        job.close()


def error_words(code: str | None, message: str, port: int) -> str:
    """What went wrong, in plain words, from the service's error code."""
    if code == "address_unavailable":
        return f"Port {port} is in use by another program. Choose another port, or close that program."
    if code in (
        "not_found",
        "root_not_found",
        "path_refused",
        "link_refused",
        "placeholder_file",
        "permission_denied",
    ):
        return "The folder was refused: it no longer exists or cannot be shared."
    if code in ("token_file_refused", "identity_key_refused"):
        return "The token file was refused: its folder or file can be read or changed by other accounts."
    if code:
        return f"The service did not start: {message or code}."
    return message


class ConnectorService(QObject):
    """The local API's child process for one window: see the module notes. ``launcher``
    starts the command (``argv`` in, a Popen-like process out; tests pass their own), and
    ``token_file`` names the token file (beside ``store``'s settings file by default)."""

    changed = Signal()  # the state, the address or the error changed
    _event = Signal(int, str, object)  # (generation, what, payload), from the reader threads

    def __init__(
        self,
        parent: QObject | None,
        store,
        *,
        launcher: Callable[[list[str]], Any] | None = None,
        token_file: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.launcher = launcher or launch
        self.token_file = token_file or token_file_path(getattr(store, "path", None))
        self.settings = load_settings(store)
        self.folder: str | None = None
        self.state = OFF
        self.url: str | None = None
        self.port: int | None = None
        self.error: str | None = None
        self.details = ""
        self._proc: Any = None
        self._threads: list[threading.Thread] = []
        self._generation = 0
        self._closing = False
        self._event.connect(self._on_event)

    # ------------------------------------------------------------------ what the viewer calls
    def apply(self, settings: ConnectorSettings) -> bool:
        """Keep ``settings`` and start, restart or stop the service to match; whether
        they were saved."""
        ok = save_settings(self.store, settings)
        old, self.settings = self.settings, settings
        if not settings.share:
            self.stop()
        elif old != settings or self.state in (OFF, NO_FOLDER, FAILED):
            self.restart()
        return ok

    def folder_opened(self, folder: str | None) -> None:
        if folder == self.folder:
            return
        self.folder = folder
        if self.settings.share:
            self.restart()

    def shutdown(self) -> None:
        """The window is closing: the service stops and does not start again."""
        self._closing = True
        self.stop()

    def restart(self) -> None:
        self._end()
        self._start()

    def stop(self) -> None:
        self._end()
        self._set(NO_FOLDER if self.settings.share and not self.folder and not self._closing else OFF)

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def shown_port(self) -> int:
        """The port the service listens on, or the one it will."""
        return self.port or self.settings.port

    # ------------------------------------------------------------------ the process
    def _set(self, state: str, *, error: str | None = None, details: str = "") -> None:
        self.state, self.error, self.details = state, error, details
        if state != RUNNING:
            self.url = None
            self.port = None
        self.changed.emit()

    def _start(self) -> None:
        if self._closing or not self.settings.share:
            self._set(OFF)
            return
        if not self.folder:
            self._set(NO_FOLDER)
            return
        if not os.path.isdir(self.folder):
            self._set(FAILED, error=error_words("not_found", "", self.settings.port))
            return
        folder = os.path.dirname(self.token_file)
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
        except OSError as exc:
            self._set(FAILED, error=f"The token file's folder could not be made: {exc.strerror or exc}.")
            return
        argv = service_command(self.folder, self.settings.port, self.token_file)
        try:
            proc = self.launcher(argv)
        except OSError as exc:
            self._set(FAILED, error=f"The service could not be started: {exc.strerror or exc}.")
            return
        self._generation += 1
        self._proc = proc
        _LIVE.add(proc)
        self._set(STARTING)
        tail: collections.deque[str] = collections.deque(maxlen=STDERR_LINES)
        errors = threading.Thread(target=self._read_errors, args=(proc, tail), daemon=True)
        output = threading.Thread(
            target=self._read_output, args=(self._generation, proc, tail, errors), daemon=True
        )
        self._threads = [errors, output]
        errors.start()
        output.start()

    def _end(self) -> None:
        proc, self._proc = self._proc, None
        self._generation += 1  # what its threads still send is about a process that is gone
        if proc is None:
            return
        try:
            stop_process(proc)
        finally:
            _LIVE.discard(proc)
            for t in self._threads:
                t.join(2.0)
            self._threads = []

    @staticmethod
    def _read_errors(proc: Any, tail: collections.deque) -> None:
        try:
            for line in proc.stderr:
                tail.append(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass

    def _read_output(self, generation: int, proc: Any, tail: collections.deque, errors) -> None:
        rest: list[str] = []
        size = 0
        first = True
        try:
            for line in proc.stdout:
                if first:
                    first = False
                    try:
                        env = json.loads(line)
                    except ValueError:
                        env = None
                    if isinstance(env, dict) and env.get("ok") and env.get("kind") == "serve_started":
                        self._event.emit(generation, "ready", env.get("data") or {})
                        continue
                if size < MAX_OUTPUT_CHARS:
                    rest.append(line)
                    size += len(line)
        except (OSError, ValueError):
            pass
        try:
            code = proc.wait()
        except Exception:
            code = None
        errors.join(2.0)
        self._event.emit(generation, "ended", (code, "".join(rest), "\n".join(tail)))

    def _on_event(self, generation: int, what: str, payload: Any) -> None:
        if generation != self._generation:
            return
        if what == "ready":
            port = payload.get("port")
            self.port = port if isinstance(port, int) else self.settings.port
            url = payload.get("url")
            self.url = url if isinstance(url, str) else f"http://{BIND}:{self.port}/v1/"
            self.state, self.error, self.details = RUNNING, None, ""
            self.changed.emit()
            return
        code, out, err = payload
        proc, self._proc = self._proc, None
        if proc is not None:
            _LIVE.discard(proc)
            stop_process(proc, 0.5)  # closes its Job Object
        error_code = message = None
        try:
            env = json.loads(out) if out.strip() else None
        except ValueError:
            env = None
        if isinstance(env, dict) and isinstance(env.get("error"), dict):
            error_code = env["error"].get("code")
            message = env["error"].get("message")
        if error_code:
            words = error_words(error_code, message or "", self.settings.port)
        else:
            words = "The service ended unexpectedly" + (f" (exit code {code})." if code is not None else ".")
        self._set(FAILED, error=words, details=err)


__all__ = [
    "DEFAULT_PORT",
    "FAILED",
    "NO_FOLDER",
    "OFF",
    "RUNNING",
    "SECTION",
    "STARTING",
    "ConnectorService",
    "ConnectorSettings",
    "error_words",
    "launch",
    "load_settings",
    "mcp_config",
    "powershell_example",
    "program",
    "save_settings",
    "service_command",
    "stop_process",
    "token_file_path",
]
