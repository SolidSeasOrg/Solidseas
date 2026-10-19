"""A helper program SolidSeas starts and talks to: the SOLIDWORKS bridge, and the helper
of a packaged extension (``docs/EXTENSIONS.md`` section 6).

:class:`Helper` starts the program, speaks JSON lines with it and keeps a timeout on
every request, so that a helper that hangs can never hang SolidSeas:

* **A Job Object.** On Windows the helper is put in a Job Object with kill-on-close
  before it is sent anything; whatever it starts inherits the job. With ``memory_mb``
  each process in the job is capped at that much committed memory and ends at once on
  an unhandled exception, with no error report. Closing the job ends the helper and
  everything it started, and the job closes by itself if this process dies. Elsewhere
  the helper leads its own process group, which is killed instead.
* **JSON lines.** The helper's first line is ``{"event": "ready", "protocol": n, ...}``;
  then one request per line on its standard input (``{"id": 7, "op": ..., "args":
  {...}, "timeout_s": 600}``) and one reply per line on its output (``{"id": 7, "ok":
  true, "result": {...}}`` or ``{"id": 7, "ok": false, "error": {"code": ...,
  "message": ...}}``). Lines without an ``id`` are events. Every reply is data.
* **A timeout on every request.** When the time is up the job is ended and the request
  raises :class:`HelperTimeoutError`; later requests fail with
  :class:`HelperExitedError`.
* **Events never hold the replies.** The thread that reads the output only queues an
  event; listeners run on a thread of their own.

:class:`solidseas.swapi.bridge.Bridge` is the SOLIDWORKS bridge's own kind of helper.
Call a helper from a worker thread, never from a Qt thread.
"""

from __future__ import annotations

import collections
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

HARD_LIMIT_S = 600.0  # a request with no timeout of its own
MAX_TIMEOUT_S = 86400.0  # the longest timeout a request may have
READY_TIMEOUT_S = 30.0
EXIT_WAIT_S = 30.0  # how long to wait for the processes of an ended job to go
MAX_LINE_BYTES = 64 << 20  # a line from the helper
MAX_REQUEST_CHARS = 1 << 20  # a request line, in UTF-16 code units, as a helper counts
_STDERR_LINES = 200
_EVENTS_KEPT = 1000
_EVENT_BACKLOG = 10000  # events waiting for a slow listener before more are dropped
_DIALOGS_KEPT = 100  # dialogs the helper reported, kept to say why a request timed out


class HelperError(RuntimeError):
    """Base class for helper failures. ``code`` is a protocol error code, ``op`` the request."""

    code = "internal"

    def __init__(self, message: str, *, code: str | None = None, op: str | None = None, details=None):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.op = op
        self.details = details


class HelperTimeoutError(HelperError, TimeoutError):
    """A request had no reply in time; the helper and what it started were ended."""

    code = "timeout"


class HelperExitedError(HelperError):
    """The helper is not running: it crashed, exited, or was ended after a timeout."""

    code = "helper_exited"


class HelperRequestError(HelperError):
    """The helper answered the request with an error (``code``, ``details``, ``hresult``)."""

    def __init__(self, message: str, *, code: str, op: str | None = None, details=None, hresult=None):
        super().__init__(message, code=code, op=op, details=details)
        self.hresult = hresult


_WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------- the Job Object (Windows)
if _WINDOWS:
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

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _k32.IsProcessInJob.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long
    _CREATE_SUSPENDED = 0x00000004

    def _resume(handle: int) -> None:
        """Let a process started suspended run: all its threads (Popen keeps no thread handle)."""
        status = _ntdll.NtResumeProcess(handle)
        if status != 0:
            raise OSError(status, f"NtResumeProcess failed: NTSTATUS 0x{status & 0xFFFFFFFF:08x}")

    _KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_MEMORY = 0x0100
    _DIE_ON_UNHANDLED_EXCEPTION = 0x0400
    _EXTENDED_LIMIT_INFORMATION = 9
    _BASIC_ACCOUNTING_INFORMATION = 1
    _BASIC_PROCESS_ID_LIST = 3
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def _winerror(what: str) -> OSError:
        err = ctypes.get_last_error()
        return OSError(err, f"{what} failed: {ctypes.FormatError(err).strip()}")

    class _Job:
        """A Job Object with kill-on-close that holds a helper and whatever it starts; with
        ``memory_mb``, each process in it is also capped at that much committed memory, and
        any process in it with an unhandled exception ends at once (no error report)."""

        def __init__(self, memory_mb: int | None = None) -> None:
            handle = _k32.CreateJobObjectW(None, None)
            if not handle:
                raise _winerror("CreateJobObjectW")
            self.handle = handle
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if memory_mb is not None:
                info.BasicLimitInformation.LimitFlags |= _PROCESS_MEMORY | _DIE_ON_UNHANDLED_EXCEPTION
                info.ProcessMemoryLimit = int(memory_mb) << 20
            if not _k32.SetInformationJobObject(
                handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
            ):
                error = _winerror("SetInformationJobObject")
                self.close()
                raise error

        def assign(self, pid: int) -> None:
            proc = _k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not proc:
                raise _winerror("OpenProcess")
            try:
                if not _k32.AssignProcessToJobObject(self.handle, proc):
                    raise _winerror("AssignProcessToJobObject")
            finally:
                _k32.CloseHandle(proc)

        def contains(self, pid: int) -> bool:
            if not self.handle:
                return False
            proc = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not proc:
                return False
            try:
                result = wintypes.BOOL(False)
                return bool(_k32.IsProcessInJob(proc, self.handle, ctypes.byref(result)) and result.value)
            finally:
                _k32.CloseHandle(proc)

        def active(self) -> int:
            if not self.handle:
                return 0
            info = _Accounting()
            if not _k32.QueryInformationJobObject(
                self.handle, _BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None
            ):
                return 0
            return int(info.ActiveProcesses)

        def pids(self) -> list[int]:
            if not self.handle:
                return []

            class _List(ctypes.Structure):
                _fields_ = [
                    ("NumberOfAssignedProcesses", wintypes.DWORD),
                    ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * 256),
                ]

            info = _List()
            if not _k32.QueryInformationJobObject(
                self.handle, _BASIC_PROCESS_ID_LIST, ctypes.byref(info), ctypes.sizeof(info), None
            ):
                return []
            return [int(info.ProcessIdList[i]) for i in range(info.NumberOfProcessIdsInList)]

        def terminate(self) -> None:
            if self.handle:
                _k32.TerminateJobObject(self.handle, 1)

        def close(self) -> None:
            if self.handle:
                _k32.CloseHandle(self.handle)  # kill-on-close ends anything still in it
                self.handle = None


class _Pending:
    __slots__ = ("event", "reply")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.reply: dict | None = None


class Helper:
    """One running helper program and the conversation with it (module notes).

    ``command`` is its command line, ``label`` how messages name it ("the bridge"),
    ``protocol`` the protocol its ready line must name, ``memory_mb`` the cap on each
    process in its Job Object (none by default), ``timeouts`` each operation's timeout
    (else ``hard_limit``).
    ``on_event`` is called with every event line, in order, on a thread of its
    own, never the one that reads replies. While it is slow, events wait; past
    :data:`_EVENT_BACKLOG` waiting events, more are dropped and counted, and the
    listener then gets ``{"event": "events_lost", "count": n, "where":
    "client"}`` before the next one. A helper may do the same with
    ``"events_lost"`` lines of its own when this client stops reading.
    """

    def __init__(
        self,
        command: list[str],
        *,
        label: str = "the helper",
        protocol: int = 1,
        memory_mb: int | None = None,
        ready_timeout: float = READY_TIMEOUT_S,
        on_event: Callable[[dict], None] | None = None,
        env: Mapping[str, str] | None = None,
        timeouts: Mapping[str, float] | None = None,
        hard_limit: float = HARD_LIMIT_S,
        thread_name: str = "helper",
    ) -> None:
        self.label = label
        self.protocol = protocol
        self.timeouts = dict(timeouts or {})
        self.hard_limit = hard_limit
        self.command = list(command)
        self.on_event = on_event
        self.events: collections.deque[dict] = collections.deque(maxlen=_EVENTS_KEPT)
        self.ready: dict = {}
        self._stderr: collections.deque[str] = collections.deque(maxlen=_STDERR_LINES)
        self._pending: dict[int, _Pending] = {}
        # Request ids in the order they were written. The helper answers in that order, so a
        # reply it could not give an id (a line it could not read) belongs to the oldest one.
        self._sent: collections.deque[int] = collections.deque()
        self._ids = itertools.count(1)
        self._event_cond = threading.Condition()
        self._event_backlog: collections.deque[dict] = collections.deque()
        self._events_dropped = 0
        self._events_done = False
        self.events_lost = 0  # events this client dropped because a listener was too slow
        # Dialogs the helper left as they are ("window" events, "action": "left"), numbered as
        # they arrive, so a request that times out can say which appeared while it waited.
        self._dialogs: collections.deque[tuple[int, dict]] = collections.deque(maxlen=_DIALOGS_KEPT)
        self._dialog_count = 0
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._ready = threading.Event()
        self._dead = threading.Event()
        self._ended_reason: str | None = None
        self._kill_lock = threading.Lock()
        self._job = None
        kwargs: dict[str, Any] = {}
        if _WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            if self.start_suspended:
                # Not one instruction runs before the helper is in its job, so it cannot start
                # a process outside it or get past the memory cap at start (docs/OCCT.md 3).
                kwargs["creationflags"] |= _CREATE_SUSPENDED
        else:
            kwargs["start_new_session"] = True  # its own process group, killed as a whole
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env) if env is not None else None,
            **kwargs,
        )
        try:
            if _WINDOWS:
                self._job = _Job(memory_mb)
                self._job.assign(self._proc.pid)
                if not self._job.contains(self._proc.pid):
                    raise self.Error(f"{self.label} is not in its Job Object", code="start_failed")
                if self.start_suspended:
                    _resume(int(self._proc._handle))  # type: ignore[attr-defined]
        except OSError as e:
            self._kill_now()
            raise self.Error(
                f"{self.label} could not be put in a Job Object: {e}", code="start_failed"
            ) from e
        except BaseException:
            self._kill_now()
            raise
        self._reader = threading.Thread(target=self._read_stdout, name=f"{thread_name}-stdout", daemon=True)
        self._errreader = threading.Thread(
            target=self._read_stderr, name=f"{thread_name}-stderr", daemon=True
        )
        self._dispatcher = threading.Thread(
            target=self._dispatch_events, name=f"{thread_name}-events", daemon=True
        )
        self._reader.start()
        self._errreader.start()
        self._dispatcher.start()
        self._start_protocol(protocol, ready_timeout)

    def _start_protocol(self, protocol: Any, ready_timeout: float) -> None:
        """Wait for the helper's ready line and check its protocol (a kind of helper that
        speaks another protocol confirms its start its own way)."""
        if not self._ready.wait(ready_timeout) or not self.ready:
            reason = "exited" if self._dead.is_set() else f"sent nothing within {ready_timeout:g} s"
            self.kill(f"{self.label} {reason} while starting")
            self._errreader.join(5.0)  # its last words, if it had any
            raise self.ExitedError(f"{self.label} {reason} while starting{self._tail()}", code="start_failed")
        if self.ready.get("protocol") != protocol:
            self.kill("protocol mismatch")
            raise self.Error(
                f"{self.label} speaks protocol {self.ready.get('protocol')!r}, this client {protocol}",
                code="protocol_mismatch",
            )

    Error: type[HelperError] = HelperError
    TimeoutError: type[HelperError] = None  # set below the class
    ExitedError: type[HelperError] = None
    RequestError: type[HelperError] = None
    ended_words = "the helper and what it started were ended"
    # On Windows the helper starts suspended and runs only once it is in its Job Object.
    start_suspended = True

    def max_request_chars(self) -> int:
        """The longest request line, in UTF-16 code units, the helper reads."""
        return MAX_REQUEST_CHARS

    def dialog_note(self, dialogs: list[dict]) -> str:
        """Words for the dialogs reported while a request waited (none by default)."""
        return ""

    # ----------------------------------------------------------------------- state
    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def alive(self) -> bool:
        return not self._dead.is_set() and self._proc.poll() is None

    @property
    def ended_reason(self) -> str | None:
        """Why the helper was ended by this client (a timeout, close), or None."""
        return self._ended_reason

    def stderr_tail(self) -> list[str]:
        return list(self._stderr)

    def job_pids(self) -> list[int]:
        """Process ids in the helper's Job Object (Windows): the helper and what it started."""
        return self._job.pids() if self._job is not None else []

    def _tail(self) -> str:
        lines = [s for s in self._stderr if s.strip()][-5:]
        return (": " + " | ".join(lines)) if lines else ""

    # ----------------------------------------------------------------------- requests
    def _request_message(self, rid: int, op: str, args: Mapping[str, Any] | None, timeout: float) -> dict:
        """The line a request is sent as."""
        message: dict[str, Any] = {"id": rid, "op": op, "timeout_s": round(float(timeout), 3)}
        if args:
            message["args"] = dict(args)
        return message

    def _reply_of(self, message: dict) -> dict | None:
        """``message`` as a reply (``{"id", "ok", "result" or "error"}``), or None when it is
        not one: a ready line or an event."""
        return message if "id" in message and "ok" in message else None

    def request(
        self, op: str, args: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict:
        """Send one request and wait for its reply; the ``result`` object on success.

        Raises :attr:`RequestError` when the helper refuses or fails the request,
        :attr:`TimeoutError` when there is no reply within ``timeout`` seconds
        (default the operation's in ``timeouts``, else ``hard_limit``), after ending
        the helper and what it started, and :attr:`ExitedError` when the helper is
        not running.
        Raises ``ValueError``, sending nothing, for a timeout outside the range
        a helper accepts (more than 0, at most :data:`MAX_TIMEOUT_S`) and for
        a request longer than it reads (:meth:`max_request_chars`).
        """
        if timeout is None:
            timeout = self.timeouts.get(op, self.hard_limit)
        if isinstance(timeout, bool) or not (0 < timeout <= MAX_TIMEOUT_S):
            raise ValueError(f"timeout must be more than 0 and at most {MAX_TIMEOUT_S:g} s, not {timeout!r}")
        rid = next(self._ids)
        message = self._request_message(rid, op, args, timeout)
        text = json.dumps(message, ensure_ascii=False, allow_nan=False)
        units = len(text.encode("utf-16-le")) // 2
        most = self.max_request_chars()
        if units > most:
            raise ValueError(
                f"{op}: the request is {units} characters long; {self.label} reads at most {most}"
            )
        line = (text + "\n").encode("utf-8")
        if not self.alive:
            raise self.ExitedError(self._exited_message(), op=op)
        pending = _Pending()
        with self._lock:
            self._pending[rid] = pending
            dialogs_before = self._dialog_count
        start = time.monotonic()
        try:
            with self._write_lock:
                with self._lock:
                    self._sent.append(rid)
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
        except (OSError, ValueError):
            with self._lock:
                self._pending.pop(rid, None)
            raise self.ExitedError(self._exited_message(), op=op) from None
        if not pending.event.wait(timeout):
            with self._lock:  # the reader sets a reply under this lock, so it cannot be half-delivered
                self._pending.pop(rid, None)
                late = pending.reply
            if late is None:
                elapsed = time.monotonic() - start
                with self._lock:
                    shown = [e for n, e in self._dialogs if n > dialogs_before]
                self.kill(f"{op} had no reply within {timeout:g} s")
                raise self.TimeoutError(
                    f"{op} had no reply within {timeout:g} s ({elapsed:.1f} s waited)"
                    f"{self.dialog_note(shown)}; {self.ended_words}",
                    op=op,
                    details={"dialogs": shown} if shown else None,
                )
        reply = pending.reply
        if reply is None:
            raise self.ExitedError(self._exited_message(), op=op)
        if reply.get("ok") is True:
            result = reply.get("result")
            return result if isinstance(result, dict) else {}
        error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        raise self.RequestError(
            f"{op}: {error.get('message') or 'failed'}",
            code=str(error.get("code") or "internal"),
            op=op,
            details=error.get("details"),
            hresult=error.get("hresult"),
        )

    def _exited_message(self) -> str:
        if self._ended_reason:
            return f"{self.label} was ended: {self._ended_reason}"
        code = self._proc.poll()
        return f"{self.label} is not running (exit code {code}){self._tail()}"

    # ----------------------------------------------------------------------- readers
    def _read_stdout(self) -> None:
        out = self._proc.stdout
        try:
            while True:
                raw = out.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES:
                    self._stderr.append(f"protocol: a line from {self.label} was too long")
                    self.kill(f"{self.label} sent a line longer than the limit")
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    shown = raw[:200].decode("utf-8", "replace").rstrip()
                    self._stderr.append("protocol: not JSON: " + shown)
                    continue
                if not isinstance(message, dict):
                    continue
                reply = self._reply_of(message)
                if reply is not None:
                    message = reply
                    rid = message.get("id")
                    with self._lock:
                        pending = self._answered(rid)
                        if pending is not None:
                            pending.reply = message
                    if pending is not None:
                        pending.event.set()
                    if rid is None:
                        self._stderr.append("protocol: " + str((message.get("error") or {}).get("message")))
                    continue
                if message.get("event") == "ready" and not self._ready.is_set():
                    self.ready = message
                    self._ready.set()
                    continue
                if "event" in message:
                    if message.get("event") == "window" and message.get("action") == "left":
                        with self._lock:
                            self._dialog_count += 1
                            self._dialogs.append((self._dialog_count, message))
                    self.events.append(message)
                    self._queue_event(message)
        except (OSError, ValueError):
            pass
        finally:
            self._dead.set()
            self._ready.set()
            with self._lock:
                waiting = list(self._pending.values())
                self._pending.clear()
                self._sent.clear()
            for p in waiting:
                p.event.set()  # reply stays None: the request raises ExitedError
            with self._event_cond:
                self._events_done = True
                self._event_cond.notify_all()

    def _answered(self, rid: object) -> _Pending | None:
        """The request a reply answers, taken out of the pending ones (call holding ``_lock``).

        A helper answers requests one at a time, in the order it read them, so
        the oldest request written and not yet answered is the one being
        answered. A reply without an id (the helper could not read the line)
        goes to that request instead of leaving it to wait out its timeout.
        """
        if isinstance(rid, bool) or not isinstance(rid, int):
            if rid is not None:
                return None
            while self._sent:
                pending = self._pending.pop(self._sent.popleft(), None)
                if pending is not None:
                    return pending
            return None
        while self._sent and (self._sent[0] == rid or self._sent[0] not in self._pending):
            self._sent.popleft()
        return self._pending.pop(rid, None)

    # ----------------------------------------------------------------------- events
    def _queue_event(self, message: dict) -> None:
        with self._event_cond:
            if len(self._event_backlog) >= _EVENT_BACKLOG:
                self._events_dropped += 1
                self.events_lost += 1
                return
            if self._events_dropped:
                self._event_backlog.append(self._lost_notice())
            self._event_backlog.append(message)
            self._event_cond.notify()

    def _lost_notice(self) -> dict:
        """The event that says how many were dropped since the last one (call holding ``_event_cond``)."""
        notice = {"event": "events_lost", "count": self._events_dropped, "where": "client"}
        self._events_dropped = 0
        return notice

    def _dispatch_events(self) -> None:
        while True:
            with self._event_cond:
                while not self._event_backlog and not self._events_dropped and not self._events_done:
                    self._event_cond.wait()
                if self._event_backlog:
                    message = self._event_backlog.popleft()
                elif self._events_dropped:
                    message = self._lost_notice()
                else:
                    return
            listener = self.on_event
            if listener is not None:
                try:
                    listener(message)
                except Exception:  # a listener's bug must not stop the others
                    pass

    def _read_stderr(self) -> None:
        try:
            for raw in iter(self._proc.stderr.readline, b""):
                self._stderr.append(raw.decode("utf-8", "replace").rstrip())
        except (OSError, ValueError):
            pass

    # ----------------------------------------------------------------------- ending
    def kill(self, reason: str = "ended by the client") -> None:
        """End the helper and everything it started, now, and wait until they are gone."""
        if self._ended_reason is None:
            self._ended_reason = reason
        self._kill_now()

    def _kill_now(self) -> None:
        with self._kill_lock:
            self._end_processes()

    def _end_processes(self) -> None:
        if self._job is not None:
            self._job.terminate()
            # A helper that never joined the job (the assignment failed) is ended by its handle.
            if self._proc.poll() is None and not self._job.contains(self._proc.pid):
                try:
                    self._proc.kill()
                except OSError:
                    pass
        elif not _WINDOWS:
            # The whole group, even when the helper itself has already gone: what it
            # started keeps the group alive.
            import signal

            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except OSError:
                pass
        elif self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        try:
            self._proc.wait(EXIT_WAIT_S)
        except subprocess.TimeoutExpired:
            pass
        if self._job is not None:
            deadline = time.monotonic() + EXIT_WAIT_S
            while self._job.active() and time.monotonic() < deadline:
                time.sleep(0.05)
            self._job.close()
            self._job = None
        for stream in (self._proc.stdin,):
            try:
                stream.close()
            except OSError:
                pass

    def close(self, timeout: float = 60.0) -> None:
        """Ask the helper to end what it started and exit (its ``shutdown`` request); end it if it
        has not within ``timeout``."""
        if self.alive:
            self._ask_to_end(timeout)
            try:
                self._proc.wait(min(timeout, 15.0))
            except subprocess.TimeoutExpired:
                pass
        if self._ended_reason is None:
            self._ended_reason = "closed"
        self._kill_now()
        self._reader.join(5.0)
        self._errreader.join(5.0)
        self._dispatcher.join(5.0)  # a listener that never returns is left behind
        for stream in (self._proc.stdout, self._proc.stderr):
            try:
                stream.close()
            except OSError:
                pass

    def _ask_to_end(self, timeout: float) -> None:
        """Ask the helper to end (its ``shutdown`` request)."""
        try:
            self.request("shutdown", timeout=timeout)
        except HelperError:
            pass

    def __enter__(self) -> Helper:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            if self._job is not None:
                self._job.close()
        except Exception:
            pass


Helper.TimeoutError = HelperTimeoutError
Helper.ExitedError = HelperExitedError
Helper.RequestError = HelperRequestError

MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # the MCP revisions McpHelper speaks


class McpHelper(Helper):
    """An MCP server on standard input and output (JSON-RPC 2.0, one message a line) run as
    a helper: in the same Job Object, with the same memory cap, timeouts and kill as any
    other. Its start is confirmed by ``initialize`` instead of a ready line; ``ready``
    then holds the protocol revision and the server's name. Its requests are MCP methods
    (:meth:`tools`, :meth:`call`); a JSON-RPC error raises :attr:`RequestError` with the
    error's code. Requests the server sends are not answered: the client offers no
    capabilities (no roots, no sampling), so a server has nothing to ask it."""

    def __init__(self, command: list[str], *, label: str = "the MCP server", protocol: Any = None, **kwargs):
        super().__init__(command, label=label, protocol=MCP_VERSIONS[1], **kwargs)

    def _request_message(self, rid: int, op: str, args: Mapping[str, Any] | None, timeout: float) -> dict:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": op}
        if args is not None:
            message["params"] = dict(args)
        return message

    def _reply_of(self, message: dict) -> dict | None:
        if "method" in message or "id" not in message or not ("result" in message or "error" in message):
            return None
        error = message.get("error")
        if error is None:
            return {"id": message["id"], "ok": True, "result": message.get("result")}
        error = error if isinstance(error, dict) else {}
        return {
            "id": message["id"],
            "ok": False,
            "error": {"code": str(error.get("code", "internal")), "message": str(error.get("message") or "")},
        }

    def _start_protocol(self, protocol: Any, ready_timeout: float) -> None:
        asked = {
            "protocolVersion": protocol,
            "capabilities": {},
            "clientInfo": {"name": "SolidSeas", "version": _version()},
        }
        try:
            got = self.request("initialize", asked, timeout=ready_timeout)
        except HelperError as e:
            self.kill(f"{self.label} did not start")
            raise self.ExitedError(
                f"{self.label} did not start: {e}{self._tail()}", code="start_failed"
            ) from e
        version = got.get("protocolVersion")
        if version not in MCP_VERSIONS:
            self.kill("protocol mismatch")
            raise self.Error(
                f"{self.label} speaks MCP {version!r}, this client {', '.join(MCP_VERSIONS)}",
                code="protocol_mismatch",
            )
        info = got.get("serverInfo") if isinstance(got.get("serverInfo"), dict) else {}
        self.ready = {"protocol": version, "server": info, "capabilities": got.get("capabilities") or {}}
        self._notify("notifications/initialized")

    def _notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
        except (OSError, ValueError):
            raise self.ExitedError(self._exited_message(), op=method) from None

    def _ask_to_end(self, timeout: float) -> None:
        """An MCP server on stdio ends when its input closes."""
        try:
            with self._write_lock:
                self._proc.stdin.close()
        except (OSError, ValueError):
            pass

    def tools(self, *, timeout: float = 60.0) -> list[dict]:
        """Every tool the server lists, page by page."""
        out: list[dict] = []
        cursor = None
        for _page in range(100):
            got = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=timeout)
            out.extend(
                t for t in got.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("name"), str)
            )
            cursor = got.get("nextCursor")
            if not cursor:
                break
        return out

    def call(
        self, name: str, arguments: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict:
        """Call the tool ``name``; its result (``content``, ``isError``) as the server gave it."""
        return self.request("tools/call", {"name": name, "arguments": dict(arguments or {})}, timeout=timeout)


def _version() -> str:
    try:
        from solidseas import __version__

        return __version__
    except ImportError:  # pragma: no cover
        return "0"


__all__ = [
    "MCP_VERSIONS",
    "Helper",
    "HelperError",
    "HelperExitedError",
    "HelperRequestError",
    "HelperTimeoutError",
    "McpHelper",
]
