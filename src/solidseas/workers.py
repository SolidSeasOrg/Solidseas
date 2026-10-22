"""Isolated worker processes for reading documents nobody vetted (provisional API).

A hostile or merely broken file can make a parser hang, run out of memory or
crash the process. The REST service (``solidseas serve``) reads every document
in a :class:`WorkerPool`, and so can any integrator that reads files from other
people: a fixed set of spawn worker processes, each with its own pipe, as the
``windows-worker-job-object`` skill describes.

* **JSON only.** A job travels to a worker as JSON, and its result comes back as
  one JSON frame read with ``recv_bytes(maxlength)``, plus at most one raw
  binary frame (a preview image). Nothing a worker sends is ever unpickled:
  ``Connection.recv()`` would run whatever a compromised parser packed into its
  reply. A test reads this module's source and fails if it calls ``recv(`` or
  uses ``pickle``.
* **A deadline per job.** When a job has no answer by its deadline, its worker
  is killed and joined, and only then is a replacement started, so the Job
  Object's active-process limit never terminates the replacement (critique
  3.15). The call raises :class:`~solidseas.errors.WorkerTimeoutError`; the
  other workers carry on. Time spent waiting for a free worker counts toward the
  deadline.
* **A crash is an answer.** A worker that dies (``os._exit``, a native crash) is
  joined and replaced, and the call raises
  :class:`~solidseas.errors.WorkerCrashedError`.
* **A lost worker is replaced for as long as the pool is open.** A replacement
  that fails to start is tried again with a growing wait (up to
  ``RETRY_MAX_S``), and a killed worker that has not ended yet (stuck in a read
  from a share) is waited for first, so the pool never shrinks for good.
  :meth:`WorkerPool.alive` counts the workers running; with ``log`` each start,
  failure and replacement is logged.
* **Started with spawn on every operating system,** which runs the main
  module again in each worker: a script that creates a pool at its top level,
  without ``if __name__ == "__main__":``, makes every worker fail as it
  starts, and the error says so.
* **A memory cap.** On Windows every worker is assigned, as soon as it starts,
  to one Job Object with ``KILL_ON_JOB_CLOSE`` (closing the pool, or the parent
  dying, ends every worker), ``ACTIVE_PROCESS`` equal to the worker count (a
  worker cannot start another process; a pool made with ``helpers_per_worker``
  lets each worker start that many, such as the OCCT backend's helper, which
  stays inside this Job Object and is capped like a worker), ``PROCESS_MEMORY`` and
  ``DIE_ON_UNHANDLED_EXCEPTION``, and the worker calls ``SetErrorMode`` so a
  crash never opens a dialog. On Linux the worker sets ``RLIMIT_AS`` and asks
  for ``SIGKILL`` when its parent dies (``prctl(PR_SET_PDEATHSIG)``). An
  allocation over the cap fails inside the worker with ``MemoryError``, which
  comes back as the error code ``limit_exceeded``.
* **Priority.** ``priority="below_normal"`` runs every worker below normal priority
  (the Job Object's priority class on Windows, ``nice`` 10 on Linux and macOS), so a
  background job such as a catalog scan never competes with the person at the
  computer.
* **A fixed job table.** A worker runs only the jobs in its table, imported by
  dotted name from :mod:`solidseas.jobs`. The ``jobs`` argument (provisional,
  ``docs/API.md`` 3.13) adds or replaces entries from Python only (the viewer's
  own jobs, and the tests' slow and crashing ones); no request and no
  configuration file can.

A worker caps resources; it is not a sandbox. It runs with the caller's own
account and network access, which is why its replies are treated as data.
"""

import collections
import itertools
import json
import logging
import multiprocessing
import os
import queue
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import InvalidArgumentError, WorkerCrashedError, WorkerJobError, WorkerTimeoutError
from .roots import Root

DEFAULT_WORKERS = 2
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MEMORY_MB = 2048
DEFAULT_MAX_RESULT_BYTES = 64 << 20
MAX_REQUEST_BYTES = 4 << 20
START_TIMEOUT_S = 60.0
JOIN_TIMEOUT_S = 10.0
RETRY_FIRST_S = 0.5  # the wait before a failed replacement is tried again; it doubles each time
RETRY_MAX_S = 30.0
MAIN_GUARD_HINT = (
    "Worker processes are started with spawn, which runs the main module again in each "
    "worker: if the code that creates the WorkerPool (or scans with a pool) is at the top "
    'level of a script, put it under if __name__ == "__main__":'
)

# The jobs every worker can run: name -> "module:function".
JOB_NAMES = (
    "document_summary",
    "properties",
    "configurations",
    "components",
    "references",
    "resolution_input",
    "bom",
    "preview",
    "path_report",
    "listing_entry",
    "identities",
    "catalog_document",
    "content_hash",
    "model_summary",
    "model_entry",
    "model_properties",
    "model_preview",
)
DEFAULT_JOBS: dict[str, str] = {name: f"solidseas.jobs:{name}" for name in JOB_NAMES}
# Kinds whose job returns that kind's data, for WorkerPool.run.
PRIORITIES = ("normal", "below_normal")
DOCUMENT_KINDS = (
    "document_summary",
    "properties",
    "configurations",
    "components",
    "references",
    "path_report",
    "model_summary",
)

_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class WorkerResult:
    """What a job returned: its JSON ``data`` and, for an image, the raw ``payload``."""

    data: Any
    payload: bytes | None = None


class _Late(Exception):
    """No answer before the deadline."""


class _Gone(Exception):
    """The worker died or broke the protocol."""


class _TooLarge(Exception):
    """The answer was longer than ``max_result_bytes``."""


def _refuse_constant(name: str) -> None:
    raise ValueError(f"{name} is not strict JSON")


def _loads(raw: bytes) -> Any:
    return json.loads(raw, parse_constant=_refuse_constant)


# --------------------------------------------------------------------------- the Windows Job Object
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

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
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
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _k32.IsProcessInJob.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    _KILL_ON_JOB_CLOSE = 0x2000
    _ACTIVE_PROCESS = 0x8
    _PROCESS_MEMORY = 0x100
    _DIE_ON_UNHANDLED_EXCEPTION = 0x400
    _PRIORITY_CLASS = 0x20
    _BELOW_NORMAL_PRIORITY_CLASS = 0x4000
    _EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def _winerror(what: str) -> OSError:
        err = ctypes.get_last_error()
        return OSError(err, f"{what} failed: {ctypes.FormatError(err).strip()}")

    class _JobObject:
        """One Job Object for every worker of a pool."""

        def __init__(
            self, active_processes: int, memory_bytes: int | None, *, below_normal: bool = False
        ) -> None:
            handle = _k32.CreateJobObjectW(None, None)
            if not handle:
                raise _winerror("CreateJobObjectW")
            self.handle = handle
            info = _ExtendedLimits()
            flags = _KILL_ON_JOB_CLOSE | _ACTIVE_PROCESS | _DIE_ON_UNHANDLED_EXCEPTION
            info.BasicLimitInformation.ActiveProcessLimit = active_processes
            if memory_bytes:
                flags |= _PROCESS_MEMORY
                info.ProcessMemoryLimit = memory_bytes
            if below_normal:
                flags |= _PRIORITY_CLASS
                info.BasicLimitInformation.PriorityClass = _BELOW_NORMAL_PRIORITY_CLASS
            info.BasicLimitInformation.LimitFlags = flags
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
            proc = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not proc:
                return False
            try:
                result = wintypes.BOOL(False)
                if not _k32.IsProcessInJob(proc, self.handle, ctypes.byref(result)):
                    return False
                return bool(result.value)
            finally:
                _k32.CloseHandle(proc)

        def close(self) -> None:
            if self.handle:
                _k32.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE ends any worker still in it
                self.handle = None


# --------------------------------------------------------------------------- the worker process
def _harden(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Limits a worker sets on itself before it imports a parser. Returns what took."""
    import signal

    applied: dict[str, Any] = {"error_mode": None, "rlimit_as": None, "pdeathsig": False, "nice": None}
    for name in ("SIGINT", "SIGBREAK"):  # Ctrl+C and Ctrl+Break reach the whole console group
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass
    if _WINDOWS:
        import ctypes as _ct

        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX: no modal boxes
        _ct.windll.kernel32.SetErrorMode(0x8003)
        applied["error_mode"] = 0x8003
        return applied
    if settings.get("priority") == "below_normal":  # Windows: the Job Object sets it
        try:
            applied["nice"] = os.nice(10)
        except OSError:
            pass
    memory_mb = settings.get("memory_mb")
    try:
        import resource

        if memory_mb:
            cap = int(memory_mb) << 20
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
            applied["rlimit_as"] = resource.getrlimit(resource.RLIMIT_AS)[0]
    except (ImportError, OSError, ValueError):  # macOS may refuse RLIMIT_AS: best effort there
        pass
    if sys.platform.startswith("linux"):
        try:
            import ctypes as _ct
            import signal as _sig

            libc = _ct.CDLL(None, use_errno=True)
            if libc.prctl(1, int(_sig.SIGKILL), 0, 0, 0) == 0:  # PR_SET_PDEATHSIG
                applied["pdeathsig"] = True
            if os.getppid() != settings.get("parent_pid"):
                os._exit(0)  # the parent died before the request took effect
        except (OSError, AttributeError):
            pass
    return applied


def _load_jobs(table: Mapping[str, str]) -> dict[str, Any]:
    import importlib

    jobs = {}
    for name, target in table.items():
        module, _, func = target.partition(":")
        jobs[name] = getattr(importlib.import_module(module), func)
    return jobs


def _child_main(conn, settings: dict[str, Any]) -> None:  # pragma: no cover - runs in the worker
    """The worker's loop: one JSON request in, one JSON reply (and an optional payload) out."""
    applied = _harden(settings)
    try:
        from . import jobs as job_module
        from .errors import SldLimitError
        from .model import dumps, error_info

        job_module.configure(settings.get("job_settings") or {})
        jobs = _load_jobs(settings["jobs"])
    except BaseException as exc:
        conn.send_bytes(json.dumps({"ready": False, "error": type(exc).__name__}).encode("ascii"))
        return
    conn.send_bytes(json.dumps({"ready": True, "pid": os.getpid(), "limits": applied}).encode("ascii"))
    reader_message = bool(settings.get("reader_message", True))

    def failure(rid: int, exc: BaseException) -> bytes:
        if isinstance(exc, MemoryError):
            exc = SldLimitError("the worker reached its memory limit", detail={"limit": "memory"})
        return dumps(
            {"id": rid, "ok": False, "error": error_info(exc, reader_message=reader_message)}
        ).encode("ascii")

    while True:
        try:
            raw = conn.recv_bytes(MAX_REQUEST_BYTES)
        except (EOFError, OSError):
            return
        try:
            req = json.loads(raw)
            rid, name, params = req["id"], req["job"], req["params"]
            limit = req.get("limit")
        except Exception:
            return  # the parent never sends this: leave, and the parent replaces the worker
        payload = None
        try:
            fn = jobs.get(name)
            if fn is None:
                raise InvalidArgumentError(f"no job named {name!r}", detail={"parameter": "job"})
            out = fn(params)
            if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], (bytes, type(None))):
                out, payload = out
            header = dumps(
                {"id": rid, "ok": True, "data": out, "payload": None if payload is None else len(payload)}
            )
            message = header.encode("ascii")
        except BaseException as exc:  # every failure is an answer; the worker lives on
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            payload = None
            try:
                message = failure(rid, exc)
            except MemoryError:
                message = b'{"id":%d,"ok":false,"error":{"code":"limit_exceeded"}}' % rid
        longest = max(len(message), len(payload) if payload is not None else 0)
        if isinstance(limit, int) and longest > limit:
            # refused here, so the worker lives on and the over-long answer never crosses the pipe
            payload = None
            error = {"code": "response_too_large", "exception": "WorkerJobError", "detail": {"limit": limit}}
            message = dumps({"id": rid, "ok": False, "error": error}).encode("ascii")
        conn.send_bytes(message)
        if payload is not None:
            conn.send_bytes(payload)


# --------------------------------------------------------------------------- the pool
class _Spawner:
    """One thread that starts every worker of a pool and lives as long as the pool.

    On Linux ``PR_SET_PDEATHSIG`` fires when the *thread* that started a worker
    ends, not the process, so a worker started from a short-lived thread (a
    request, a replacement) would be killed as soon as that thread returned."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="solidseas-worker-spawner", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, box, done = item
            try:
                box.append((True, fn()))
            except BaseException as exc:  # handed back to the caller, which raises it
                box.append((False, exc))
            done.set()

    def run(self, fn):
        box: list = []
        done = threading.Event()
        self._queue.put((fn, box, done))
        done.wait()
        ok, value = box[0]
        if not ok:
            raise value
        return value

    def stop(self) -> None:
        self._queue.put(None)


class _Worker:
    def __init__(self, proc, conn) -> None:
        self.proc = proc
        self.conn = conn
        self.pid: int = proc.pid
        self.limits: dict[str, Any] = {}
        # A call is using the pipe: only that call's thread may close it. Closing a pipe
        # under another thread's poll leaves an overlapped read in flight on Windows.
        self.busy = False


def _check_positive(value: Any, name: str, *, allow_none: bool = False, kind=(int, float)) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, kind) or not value > 0:
        raise InvalidArgumentError(f"{name} must be a positive number", detail={"parameter": name})


class WorkerPool:
    """A fixed set of spawn worker processes that run jobs with a deadline each.

    ``workers`` processes start at once and stay up; each job gets one of them.
    ``timeout_s`` is the default deadline per job, ``memory_mb`` the cap per
    worker (None for none), ``max_result_bytes`` the longest reply accepted.
    ``roots`` (a :class:`~solidseas.Roots`, or folder paths) restricts the ``within``
    a document job may open below,
    ``reader_message`` whether error objects carry the exception text (the REST
    service turns it off), ``refuse_hard_links`` whether a file with more than one
    name is refused, and ``max_file_bytes`` the largest document a job reads.
    ``formats`` (provisional; ``"all"``, ids, or None for every format) are the only
    formats a job reads a model file as, whatever its name says, and ``limits`` (a
    :class:`~solidseas.formats.Limits`, a mapping of its fields, or None for the
    defaults) bounds every model-file read.
    ``jobs`` adds or replaces job-table entries (``{"name": "module:function"}``),
    from Python only. ``priority`` is ``"normal"`` or ``"below_normal"``.
    ``helpers_per_worker`` (0 to 4, default 0) is how many processes each worker may
    start: on Windows the Job Object's active-process limit is the worker count times
    one more than it, so with 0 no worker starts any process. ``log`` is a
    :class:`logging.Logger` for the pool's events
    (a worker started, killed, replaced, or failing to start); the REST service
    passes its own.

    Workers start with spawn, so a script must create the pool under
    ``if __name__ == "__main__":``. Use it as a context manager or call :meth:`close`.
    """

    def __init__(
        self,
        workers: int = DEFAULT_WORKERS,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        memory_mb: int | None = DEFAULT_MEMORY_MB,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        roots: "Iterable[Root | str | os.PathLike] | None" = None,
        reader_message: bool = True,
        refuse_hard_links: bool = False,
        max_file_bytes: int | None = None,
        jobs: Mapping[str, str] | None = None,
        start_timeout_s: float = START_TIMEOUT_S,
        log: logging.Logger | None = None,
        priority: str = "normal",
        helpers_per_worker: int = 0,
        formats: Any = None,
        limits: Any = None,
    ) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 64:
            raise InvalidArgumentError("workers must be 1 to 64", detail={"parameter": "workers"})
        if (
            isinstance(helpers_per_worker, bool)
            or not isinstance(helpers_per_worker, int)
            or not 0 <= helpers_per_worker <= 4
        ):
            raise InvalidArgumentError(
                "helpers_per_worker must be 0 to 4", detail={"parameter": "helpers_per_worker"}
            )
        _check_positive(timeout_s, "timeout_s")
        _check_positive(memory_mb, "memory_mb", allow_none=True, kind=int)
        _check_positive(max_result_bytes, "max_result_bytes", kind=int)
        _check_positive(max_file_bytes, "max_file_bytes", allow_none=True, kind=int)
        if priority not in PRIORITIES:
            raise InvalidArgumentError(
                "priority is normal or below_normal", detail={"parameter": "priority"}
            )
        from .formats.base import enabled_formats
        from .formats.limits import changed_limits, check_limits

        allowed = enabled_formats(formats)
        bounds = changed_limits(check_limits(limits))
        table = dict(DEFAULT_JOBS)
        for name, target in (jobs or {}).items():
            if not isinstance(name, str) or not isinstance(target, str) or ":" not in target:
                raise InvalidArgumentError(
                    "jobs maps a name to 'module:function'", detail={"parameter": "jobs"}
                )
            table[name] = target
        self.workers = workers
        self.timeout_s = float(timeout_s)
        self.memory_mb = memory_mb
        self.max_result_bytes = max_result_bytes
        self.start_timeout_s = float(start_timeout_s)
        self.log = log
        self.priority = priority
        self.helpers_per_worker = helpers_per_worker
        # What happened to the processes, newest last, for tests and diagnostics: started,
        # killed (with the reason), joined (with the exit code and whether it still ran),
        # replaced, assign_failed, replace_waiting (a killed worker had not ended yet) and
        # replace_retry (a replacement did not start; it is tried again).
        self.events: collections.deque = collections.deque(maxlen=2000)
        self._settings = {
            "jobs": table,
            "memory_mb": memory_mb,
            "parent_pid": os.getpid(),
            "priority": priority,
            "reader_message": bool(reader_message),
            "job_settings": {
                "roots": [
                    os.path.abspath(r.path if isinstance(r, Root) else os.fspath(r)) for r in roots or ()
                ],
                "refuse_hard_links": bool(refuse_hard_links),
                "max_file_bytes": max_file_bytes,
                "formats": None if allowed is None else sorted(allowed),
                "limits": bounds or None,
            },
        }
        self._ctx = multiprocessing.get_context("spawn")
        self._idle: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._all: set[_Worker] = set()
        self._closed = False
        self._closing = threading.Event()  # wakes replacement threads waiting to retry
        self._ids = itertools.count(1)
        self._job = (
            _JobObject(
                workers * (1 + helpers_per_worker),
                (memory_mb << 20) if memory_mb else None,
                below_normal=priority == "below_normal",
            )
            if _WINDOWS
            else None
        )
        self._spawner = _Spawner()
        started: list[_Worker] = []
        try:
            for _ in range(workers):
                started.append(self._spawn())
            deadline = time.monotonic() + self.start_timeout_s
            for w in started:
                self._await_ready(w, deadline)
        except BaseException:
            self.close()
            raise
        for w in started:
            w.busy = False
            self._idle.put(w)

    # ------------------------------------------------------------------ processes
    def _spawn(self) -> _Worker:
        return self._spawner.run(self._spawn_now)

    def _spawn_now(self) -> _Worker:
        parent, child = self._ctx.Pipe(duplex=True)
        proc = self._ctx.Process(
            target=_child_main, args=(child, self._settings), daemon=True, name="solidseas-worker"
        )
        proc.start()
        child.close()
        if self._job is not None:
            try:
                self._job.assign(proc.pid)
            except OSError:
                # Over the active-process limit (a replacement started before the worker it
                # replaces had ended) or a refused handle: the process cannot stay.
                self._event("assign_failed", proc.pid)
                proc.kill()  # a worker outside the job has no memory cap and outlives the pool
                proc.join(JOIN_TIMEOUT_S)
                parent.close()
                raise
        w = _Worker(proc, parent)
        w.busy = True  # until it is ready: the thread starting it owns the pipe
        with self._lock:
            self._all.add(w)
        self._event("started", w.pid)
        return w

    def _event(self, *event: Any) -> None:
        self.events.append(event)
        if self.log is not None:
            trouble = event[0] in ("assign_failed", "replace_retry", "replace_waiting")
            level = logging.WARNING if trouble else logging.INFO
            self.log.log(
                level, "pool event=%s %s workers=%d", event[0], " ".join(map(str, event[1:])), self.alive()
            )

    def _await_ready(self, w: _Worker, deadline: float) -> None:
        ended = False
        try:
            # On Windows a worker that dies before it takes its end of the pipe never closes
            # it (the parent holds the duplicate it would have taken), so the process itself
            # is watched too.
            while not w.conn.poll(max(0.0, min(deadline - time.monotonic(), 0.25))):
                if w.proc.exitcode is not None:
                    ended = True
                    raise EOFError("the worker process ended")
                if time.monotonic() >= deadline:
                    raise _Late
            hello = _loads(w.conn.recv_bytes(1 << 16))
        except (_Late, EOFError, OSError, ValueError) as exc:
            if not ended and not isinstance(exc, _Late):
                w.proc.join(0.5)  # the pipe closed: the process is ending
                ended = w.proc.exitcode is not None
            code = w.proc.exitcode
            self._kill(w, "did_not_start")
            if ended:  # it ended before it could answer: most often the main module ran again
                raise WorkerCrashedError(
                    f"a worker process ended as it started (exit code {code}). {MAIN_GUARD_HINT}"
                ) from exc
            raise WorkerCrashedError("a worker process did not start") from exc
        if not isinstance(hello, dict) or hello.get("ready") is not True:
            self._kill(w, "did_not_start")
            raise WorkerCrashedError("a worker process did not start")
        limits = hello.get("limits")
        w.limits = limits if isinstance(limits, dict) else {}

    def _kill(self, w: _Worker, reason: str, *, close_pipe: bool = True) -> None:
        """Kill ``w`` and wait for it to end (a replacement only ever starts after this).
        ``close_pipe=False`` leaves the pipe to the call using it, which sees the end
        of the pipe and closes it itself."""
        self._event("killed", w.pid, reason)
        try:
            w.proc.kill()
        except (OSError, ValueError):
            pass
        w.proc.join(JOIN_TIMEOUT_S)
        if close_pipe:
            try:
                w.conn.close()
            except OSError:
                pass
        with self._lock:
            self._all.discard(w)
        self._event("joined", w.pid, w.proc.exitcode, w.proc.is_alive())

    def _replace_later(self, old: _Worker) -> None:
        """Start a worker in ``old``'s place, in a thread of its own, and keep trying until
        one starts or the pool closes: a slot is never given up. ``old`` must have ended
        first, or the Job Object's active-process limit would end the replacement."""

        def replace() -> None:
            wait = RETRY_FIRST_S
            while not self._closed:
                if old.proc.exitcode is None:  # killed, but not ended yet (stuck in I/O)
                    self._event("replace_waiting", old.pid)
                    old.proc.join(JOIN_TIMEOUT_S)
                    continue
                try:
                    w = self._spawn()
                    self._await_ready(w, time.monotonic() + self.start_timeout_s)
                except (OSError, WorkerCrashedError) as exc:
                    self._event("replace_retry", old.pid, type(exc).__name__)
                    self._closing.wait(wait)
                    wait = min(wait * 2, RETRY_MAX_S)
                    continue
                if self._closed:
                    self._kill(w, "pool_closed")
                    return
                self._event("replaced", old.pid, w.pid)
                w.busy = False
                self._idle.put(w)
                return

        threading.Thread(target=replace, name="solidseas-worker-replace", daemon=True).start()

    def _discard(self, w: _Worker, reason: str) -> None:
        self._kill(w, reason)  # killed and joined first (critique 3.15)
        if not self._closed:
            self._replace_later(w)

    # ------------------------------------------------------------------ jobs
    def _take(self, deadline: float) -> _Worker:
        while True:
            if self._closed:
                raise WorkerCrashedError("the worker pool is closed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # no job was sent: the rule tells a caller the file itself was never tried
                raise WorkerTimeoutError(
                    "no worker became free before the deadline", detail={"rule": "no_free_worker"}
                )
            try:
                w = self._idle.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            with self._lock:
                if not self._closed:
                    w.busy = True
            if not w.busy:
                raise WorkerCrashedError("the worker pool is closed")
            if w.proc.is_alive():
                return w
            self._discard(w, "found_dead")

    def _receive(self, w: _Worker, deadline: float, limit: int) -> bytes:
        remaining = deadline - time.monotonic()
        try:
            ready = remaining > 0 and w.conn.poll(remaining)
        except (OSError, ValueError) as exc:  # the pipe was closed under us (the pool is closing)
            raise _Gone from exc
        if not ready:
            raise _Late
        try:
            return w.conn.recv_bytes(limit)
        except EOFError as exc:
            raise _Gone from exc
        except OSError as exc:
            if w.proc.is_alive() and "length" in str(exc):
                raise _TooLarge from exc
            raise _Gone from exc

    def call(
        self,
        job: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        max_result_bytes: int | None = None,
    ) -> WorkerResult:
        """Run ``job`` with ``params`` (JSON data) in a worker and return its result.

        Raises :class:`~solidseas.errors.WorkerTimeoutError` when the deadline
        (``timeout``, else the pool's) passes, :class:`~solidseas.errors.WorkerCrashedError`
        when the worker dies, and :class:`~solidseas.errors.WorkerJobError` carrying
        the error object when the job itself failed (a damaged file, a missing
        configuration...). A reply longer than ``max_result_bytes`` (this call's, when
        given and lower than the pool's) is a ``WorkerJobError`` with the code
        ``response_too_large``: the worker refuses to send it, and a worker that sends
        one anyway is not read further and is replaced.
        """
        if timeout is not None:
            _check_positive(timeout, "timeout")
        _check_positive(max_result_bytes, "max_result_bytes", allow_none=True, kind=int)
        limit = min(self.max_result_bytes, max_result_bytes or self.max_result_bytes)
        deadline = time.monotonic() + (self.timeout_s if timeout is None else float(timeout))
        rid = next(self._ids)
        request = json.dumps(
            {"id": rid, "job": job, "params": dict(params or {}), "limit": limit},
            allow_nan=False,
            ensure_ascii=True,
        ).encode("ascii")
        if len(request) > MAX_REQUEST_BYTES:
            raise InvalidArgumentError("the job's parameters are too large", detail={"parameter": "params"})
        w = self._take(deadline)
        return self._exchange(w, job, rid, request, deadline, limit)

    def _exchange(
        self, w: _Worker, job: str, rid: int, request: bytes, deadline: float, limit: int
    ) -> WorkerResult:
        try:
            try:
                w.conn.send_bytes(request)
            except OSError as exc:
                raise _Gone from exc
            header = _loads(self._receive(w, deadline, limit))
            if (
                not isinstance(header, dict)
                or header.get("id") != rid
                or not isinstance(header.get("ok"), bool)
            ):
                raise _Gone
            size = header.get("payload")
            payload = None
            if size is not None:
                if (
                    isinstance(size, bool)
                    or not isinstance(size, int)
                    or not 0 <= size <= limit
                ):
                    raise _Gone
                payload = self._receive(w, deadline, limit)
                if len(payload) != size:
                    raise _Gone
        except _Late:
            self._discard(w, "timeout")
            raise WorkerTimeoutError(
                f"the {job} job did not finish in time; its worker was replaced"
            ) from None
        except _TooLarge:
            self._discard(w, "too_large")
            raise WorkerJobError(
                {
                    "code": "response_too_large",
                    "exception": "WorkerJobError",
                    "detail": {"limit": limit},
                }
            ) from None
        except (_Gone, ValueError):
            self._discard(w, "crashed")
            raise WorkerCrashedError(f"the worker running the {job} job stopped unexpectedly") from None
        except BaseException:
            self._discard(w, "interrupted")  # the reply may still come; never reuse this pipe
            raise
        w.busy = False
        self._idle.put(w)
        if not header["ok"]:
            error = header.get("error")
            raise WorkerJobError(error if isinstance(error, dict) else {"code": "internal"})
        return WorkerResult(header.get("data"), payload)

    def run(self, kind: str, path: str | os.PathLike, *, timeout: float | None = None, **params: Any) -> dict:
        """The envelope of ``kind`` for the document at ``path``, read in a worker: an
        error envelope (``timeout``, ``worker_crashed``, ``damaged_file``...) when
        reading failed. ``kind`` is ``document_summary``, ``properties``,
        ``configurations``, ``components``, ``references``, ``path_report`` or
        (for a model file, provisional) ``model_summary``;
        ``params`` are that builder's options (``configuration``, ``view``,
        ``nested``, ``max_nodes``, ``max_depth``, ``flat``), and ``within`` and
        ``name`` are passed to ``open_document``."""
        from . import model

        if kind not in DOCUMENT_KINDS:
            raise InvalidArgumentError(
                f"run accepts {', '.join(DOCUMENT_KINDS)}", detail={"parameter": "kind"}
            )
        path = os.fspath(path)
        try:
            result = self.call(kind, {"path": path, **params}, timeout=timeout)
        except (WorkerTimeoutError, WorkerCrashedError, WorkerJobError) as exc:
            return model.error_envelope(exc)
        return model.envelope(kind, result.data)

    # ------------------------------------------------------------------ state
    def alive(self) -> int:
        """How many worker processes are running (started, and not yet killed or ended)."""
        with self._lock:
            workers = list(self._all)
        return sum(1 for w in workers if w.proc.is_alive())

    def worker_info(self) -> list[dict[str, Any]]:
        """Each live worker's pid, whether it is in the Job Object (Windows; None
        elsewhere) and the limits it reported setting on itself."""
        with self._lock:
            workers = list(self._all)
        return [
            {
                "pid": w.pid,
                "in_job": self._job.contains(w.pid) if self._job is not None else None,
                "limits": dict(w.limits),
            }
            for w in workers
        ]

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Kill every worker and wait for them. A call still waiting gets
        :class:`~solidseas.errors.WorkerCrashedError`."""
        with self._lock:
            self._closed = True
            workers = [(w, w.busy) for w in self._all]
        self._closing.set()
        for w, busy in workers:
            self._kill(w, "pool_closed", close_pipe=not busy)
        self._spawner.stop()
        if self._job is not None:
            self._job.close()

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = [
    "DEFAULT_JOBS",
    "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_MEMORY_MB",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_WORKERS",
    "DOCUMENT_KINDS",
    "JOB_NAMES",
    "MAIN_GUARD_HINT",
    "PRIORITIES",
    "WorkerPool",
    "WorkerResult",
]
