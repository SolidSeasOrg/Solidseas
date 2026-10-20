"""The window's worker processes for 3D files of other formats.

SOLIDWORKS documents are read in the window's own threads, as they always were.
A file of any other format (STEP, STL, 3MF, Alibre Design...) is read only in a
:class:`solidseas.workers.WorkerPool` of the window's own: the listing's entries
(the job ``model_entry``), the details panel's sections and the rendered
thumbnails (:mod:`.modeljobs`, ``model_preview``). Each worker is a spawned
process below normal priority with a memory cap of :data:`MEMORY_MB` (on Windows
in a job object that ends it with the viewer, and that lets each worker start one
helper: the OCCT backend's, for IGES and BREP files), and a job past its deadline is
ended with its worker; what comes back is JSON and PNG images SolidSeas wrote,
never a pickle.

:class:`ModelPool` starts the pool the first time a file of another format is
read, in the thread that asks (starting two workers takes a second or two), and
closes it with the window. A listing of SOLIDWORKS documents alone never starts
it. Whether its workers may start the OCCT helper is decided when it starts
(:func:`_helpers`), so when the Extensions page switches the OCCT backend on or off
the window asks :meth:`ModelPool.stale` and :meth:`ModelPool.restart`s it: the next
file read starts a pool that decides again. Nothing here imports Qt.
"""

import threading
import time
from typing import Any

from solidseas.errors import WorkerCrashedError

from .modeljobs import JOBS

WORKERS = 2
MEMORY_MB = 2048
TIMEOUT_S = 60.0  # a job's deadline: a large B-rep's geometry takes up to 30 s, then its picture
RETRY_AFTER_S = 30.0  # a pool that would not start is tried again after this long, not for every file


def _helpers() -> int:
    """Processes each worker may start: one while the OCCT backend can run (its helper
    reads IGES and BREP), else none. Decided when a pool starts; a switch changed later
    reaches the workers through :meth:`ModelPool.restart`."""
    try:
        from solidseas.convert import backend

        return 1 if backend("occt").unavailable() is None else 0
    except Exception:
        return 0


class ModelPool:
    """A :class:`~solidseas.workers.WorkerPool` started on first use (see the module notes).
    :meth:`call` is safe from any thread; :meth:`restart` ends the workers and lets the
    next call start new ones; :meth:`close` ends them for good, and a call after it raises
    :class:`~solidseas.errors.WorkerCrashedError`."""

    def __init__(self, *, workers: int = WORKERS, memory_mb: int = MEMORY_MB, timeout_s: float = TIMEOUT_S):
        self.workers, self.memory_mb, self.timeout_s = workers, memory_mb, timeout_s
        self._lock = threading.Lock()
        self._pool: Any = None
        self._closed = False
        self._failed: tuple[float, BaseException] | None = None
        self.helpers: int | None = None  # what the running pool's workers may start
        self.started = 0  # pools started, for tests and the self-test's report

    @property
    def running(self) -> bool:
        with self._lock:
            return self._pool is not None

    def _get(self):
        with self._lock:
            if self._closed:
                raise WorkerCrashedError("the viewer is closing: its worker processes have ended")
            if self._pool is None:
                if self._failed is not None and time.monotonic() - self._failed[0] < RETRY_AFTER_S:
                    raise self._failed[1]  # said once a file, not waited for once a file
                from solidseas.workers import WorkerPool

                try:
                    self._pool = WorkerPool(
                        self.workers,
                        timeout_s=self.timeout_s,
                        memory_mb=self.memory_mb,
                        jobs=JOBS,
                        priority="below_normal",
                        # an IGES or BREP file's worker starts the OCCT backend's helper,
                        # which runs in a Job Object of its own inside the pool's; only
                        # while that backend is there, so a pool without it keeps its
                        # workers from starting any process
                        helpers_per_worker=_helpers(),
                    )
                except Exception as exc:
                    self._failed = (time.monotonic(), exc)
                    raise
                self._failed = None
                self.helpers = getattr(self._pool, "helpers_per_worker", 0)
                self.started += 1
            return self._pool

    def call(self, job: str, params: dict[str, Any], *, timeout: float | None = None):
        """Run ``job`` with ``params`` in a worker (:meth:`solidseas.workers.WorkerPool.call`).
        A job whose pool was restarted under it runs once more on the new pool, so a switch
        changed meanwhile costs it time, not its result."""
        pool = self._get()
        try:
            return pool.call(job, params, timeout=timeout)
        except WorkerCrashedError:
            with self._lock:
                replaced = not self._closed and self._pool is not pool
            if not replaced:
                raise
        return self._get().call(job, params, timeout=timeout)

    def alive(self) -> int:
        with self._lock:
            return self._pool.alive() if self._pool is not None else 0

    def worker_pids(self) -> list[int]:
        with self._lock:
            if self._pool is None:
                return []
            return [w["pid"] for w in self._pool.worker_info() if w.get("pid")]

    def stale(self) -> bool:
        """Whether a pool runs whose workers may start another number of processes than a
        pool started now would: the OCCT backend was switched on or off since it started."""
        with self._lock:
            running, helpers = self._pool is not None, self.helpers
        return running and helpers != _helpers()

    def restart(self) -> bool:
        """End the running workers, if any, so the next call starts a new pool, which
        decides again what its workers may start (:func:`_helpers`). Unlike :meth:`close`
        the pool stays usable: a call waiting on an old worker runs again on the new pool
        (:meth:`call`). Returns whether a pool was running."""
        with self._lock:
            if self._closed:
                return False
            pool, self._pool = self._pool, None
            self._failed = None
            self.helpers = None
        if pool is not None:
            pool.close()
        return pool is not None

    def close(self) -> None:
        """End the workers; no call starts them again."""
        with self._lock:
            self._closed = True
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()


__all__ = ["MEMORY_MB", "TIMEOUT_S", "WORKERS", "ModelPool"]
