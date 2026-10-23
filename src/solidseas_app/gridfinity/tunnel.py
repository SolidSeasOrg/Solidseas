"""An SSH tunnel to a Tracefinity on another machine, so that SolidSeas still reaches it on
this PC's loopback only (``docs/GRIDFINITY.md``, "Tracefinity on a server").

The person names the server in :data:`SSH_ENV` the way ssh takes it (``host``,
``user@host``, or a Host of their ssh config). SolidSeas then starts the system's ssh client
with one local forward, 127.0.0.1:<port> here to 127.0.0.1:<port> on the server, the port of
the Tracefinity address. ssh runs without a window and never asks anything (``BatchMode``:
the key must be set up, as ``scripts/tracefinity-server.ps1`` does), never accepts a host key
it has not seen before (``StrictHostKeyChecking=yes``, whatever the person's ssh config says;
their ``known_hosts`` decides), and ends with the MCP server
(a Job Object on Windows). The tunnel opens on the first call that needs Tracefinity and
opens again when it has dropped, after the PC slept, say.
"""

from __future__ import annotations

import collections
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence

SSH_ENV = "SOLIDSEAS_TRACEFINITY_SSH"
KEY_ENV = "SOLIDSEAS_TRACEFINITY_SSH_KEY"
DEFAULT_KEY = os.path.join("~", ".ssh", "solidseas_tracefinity")
OPEN_S = 20.0  # for ssh to sign in and listen
# A host name or address with an optional user: nothing ssh could take as an option.
_DESTINATION = re.compile(r"\A(?:[A-Za-z0-9_][A-Za-z0-9._-]{0,31}@)?[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")
_CREATE_NO_WINDOW = 0x08000000


class TunnelError(RuntimeError):
    """The tunnel could not be opened: said to the chat as it is."""


def system_ssh() -> str | None:
    """The system's ssh client as an absolute path, or None. On Windows, the one Windows
    ships (``System32\\OpenSSH``) when it is there; otherwise the first ``ssh`` on PATH, never
    one in the current folder, which Windows would otherwise search first and where a
    cloned project could hold an ``ssh.bat`` of its own."""
    if sys.platform == "win32":
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        shipped = os.path.join(root, "System32", "OpenSSH", "ssh.exe")
        if os.path.isfile(shipped):
            return shipped
    found = shutil.which("ssh")
    if not found or not os.path.isabs(found):
        return None
    try:
        here = os.path.normcase(os.path.abspath(os.getcwd()))
    except OSError:
        here = None
    if os.path.normcase(os.path.dirname(os.path.abspath(found))) == here:
        return None
    return found


def listening(port: int, timeout: float = 0.2) -> bool:
    """Something accepts connections on 127.0.0.1:``port``."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


class SshTunnel:
    """One local forward through ssh (see the module notes). ``ssh`` is the command that
    starts the client, the system's ssh by default (tests pass a stand-in)."""

    def __init__(
        self, destination: str, port: int, *, key: str | None = None, ssh: Sequence[str] | None = None
    ) -> None:
        if not isinstance(destination, str) or not _DESTINATION.match(destination):
            raise TunnelError(
                f"{SSH_ENV} must be a host or user@host for ssh, such as root@nas; "
                f"it is {destination!r:.80}."
            )
        if not 1 <= port <= 65535:
            raise TunnelError("The Tracefinity port is not a port number.")
        self.destination = destination
        self.port = port
        self.key = key
        self._ssh = list(ssh) if ssh else [system_ssh() or "ssh"]
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._said: collections.deque[str] = collections.deque(maxlen=20)
        self._job: _Job | None = None

    def command(self) -> list[str]:
        forward = f"127.0.0.1:{self.port}:127.0.0.1:{self.port}"
        command = [*self._ssh, "-N", "-T"]
        for option in (
            "BatchMode=yes",
            "ExitOnForwardFailure=yes",
            "ServerAliveInterval=30",
            "ServerAliveCountMax=3",
            "ConnectTimeout=10",
            "StrictHostKeyChecking=yes",
        ):
            command += ["-o", option]
        command += ["-L", forward]
        if self.key:
            command += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        return [*command, self.destination]

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure(self) -> None:
        """Open the tunnel unless it is open; raises :class:`TunnelError` with ssh's reason."""
        with self._lock:
            if self.running:
                return
            self._stop()
            if listening(self.port):
                return  # an earlier SolidSeas' tunnel, or one the person opened, carries the port
            self._start()

    def _start(self) -> None:
        self._said.clear()
        if not os.path.isabs(self._ssh[0]):
            raise TunnelError(
                "SolidSeas could not find ssh: install the OpenSSH client (Windows Settings, "
                "Optional features) and try again."
            )
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            process = subprocess.Popen(
                self.command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=flags,
            )
        except OSError as exc:
            raise TunnelError(f"SolidSeas could not start ssh ({exc.strerror or exc}).") from None
        self._process = process
        if sys.platform == "win32":
            try:
                self._job = _Job()
                self._job.assign(process)
            except OSError:
                self._job = None  # it still ends with close(); only a killed server leaves it behind
        threading.Thread(target=self._listen_to, args=(process,), name="solidseas-ssh", daemon=True).start()
        deadline = time.monotonic() + OPEN_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                process.wait()
                why = (
                    next((line for line in reversed(self._said) if line), "") or f"code {process.returncode}"
                )
                self._stop()
                raise TunnelError(
                    f"The SSH tunnel to {self.destination} did not open: {why[:200]}. "
                    "docs/GRIDFINITY.md says how to set it up (scripts\\tracefinity-server.ps1)."
                )
            if listening(self.port):
                return
            time.sleep(0.1)
        self._stop()
        raise TunnelError(f"The SSH tunnel to {self.destination} did not open within {OPEN_S:g} s.")

    def _listen_to(self, process: subprocess.Popen) -> None:
        """Keep ssh's last lines (its reason, if it ends), so its pipe never fills."""
        stream = process.stderr
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            text = raw.decode("utf-8", "replace").strip()
            self._said.append("".join(c for c in text if c.isprintable()))

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self._job is not None:
            self._job.close()
            self._job = None

    def close(self) -> None:
        """End the tunnel (if this SolidSeas opened it)."""
        with self._lock:
            self._stop()


def from_settings(port: int) -> SshTunnel | None:
    """The tunnel :data:`SSH_ENV` asks for, if any: through the key in :data:`KEY_ENV`, else
    ``%USERPROFILE%\\.ssh\\solidseas_tracefinity`` when that exists, else ssh's own choice."""
    from ..extensions import setting

    destination = setting("gridfinity", "ssh")  # the variable, else the Extensions page
    if not destination:
        return None
    key = setting("gridfinity", "ssh_key") or None
    if key is None and os.path.isfile(os.path.expanduser(DEFAULT_KEY)):
        key = os.path.expanduser(DEFAULT_KEY)
    if key is not None and not os.path.isabs(os.path.expanduser(key)):
        raise TunnelError(f"{KEY_ENV} must be a full path.")
    return SshTunnel(destination.strip(), port, key=os.path.expanduser(key) if key else None)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    class _Job:
        """A Job Object that ends ssh when the last handle to it closes: when the MCP
        server ends, however it ends."""

        def __init__(self) -> None:
            handle = _k32.CreateJobObjectW(None, None)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = handle
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error

        def assign(self, process: subprocess.Popen) -> None:
            if not _k32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):  # type: ignore[attr-defined]
                raise ctypes.WinError(ctypes.get_last_error())

        def close(self) -> None:
            if self.handle:
                _k32.CloseHandle(self.handle)
                self.handle = None

else:

    class _Job:  # pragma: no cover - ssh ends with close() off Windows
        def __init__(self) -> None:
            raise OSError("Job Objects are Windows only")

        def assign(self, process: subprocess.Popen) -> None:
            pass

        def close(self) -> None:
            pass


__all__ = ["DEFAULT_KEY", "KEY_ENV", "SSH_ENV", "SshTunnel", "TunnelError", "from_settings", "listening"]
