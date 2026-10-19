"""The catalog of the opened folder, kept up to date in a process of its own.

The viewer's own process parses documents in its threads (the listing, the
details, the 3D view), so it never writes a catalog: the catalog's writer may
hold no parser (``docs/API.md`` 3.18). After a folder's listing finishes, the
window starts an indexer process (:class:`Indexer`) that opens the folder's
catalog in the user's cache folder (:mod:`solidseas.catalog`), takes its
writer lock and scans it with a :class:`~solidseas.workers.WorkerPool` of two
workers below normal priority. Its progress comes back as JSON frames on a
pipe (phase, done, total), never pickles, and so does the scan's result.

* On Windows the process runs in a job object, as the mesh reader does
  (:mod:`.meshproc`): below-normal priority, a memory limit, and ended with the
  viewer however the viewer ends. Its workers sit in a job object of their own
  inside that one.
* Opening another folder or closing the window asks it to stop; the scan stops
  between files and keeps what it committed. One that does not answer within
  :data:`STOP_WAIT_S` is ended: SQLite rolls back the open batch, and the next
  scan carries on from the rows still waiting.
* The catalog is the opened folder's own, in the cache folder. When the command
  line made it with library folders too (``solidseas index FOLDER --library ...``),
  those roots are kept.
* It indexes what the list shows: every 3D format SolidSeas reads while View >
  Show > All 3D Files is on, SOLIDWORKS documents alone while it is off (the
  catalog's ``formats`` setting, so files of a format turned off leave it).
* The listing has just read every file, so the indexer's reads come mostly from
  the disk cache; opening the same folder again costs a rescan, which reads
  only what changed.

Nothing here imports Qt.
"""

import json
import multiprocessing
import os
import threading
import time
from collections.abc import Callable
from typing import Any

SECTION = "Index"  # the settings file's section for indexing
KEY = "index_opened_folders"
DEFAULT_ON = True  # the tests switch it off for every window but the ones that test it
STOP_WAIT_S = 3.0
PROGRESS_EVERY_S = 0.2
MEMORY_LIMIT = 3 << 30  # each process of the indexer's tree; its workers cap themselves at 2 GiB
WORKERS = 2


def load_enabled(store) -> bool:
    """Whether opened folders are indexed: Settings > Index Opened Folders, on unless the
    settings file's ``[Index]`` section says otherwise."""
    raw = store.load_section(SECTION).get(KEY)
    if raw is None:
        return DEFAULT_ON
    return raw.strip().lower() not in ("false", "0", "no", "off")


def save_enabled(store, on: bool) -> None:
    store.save_section(SECTION, {KEY: "true" if on else "false"})


def _send(conn, message: dict[str, Any]) -> None:
    from solidseas import model

    conn.send_bytes(model.dumps(message).encode("ascii"))


def _serve(  # pragma: no cover - a child
    commands, results, folder: str, cache_dir: str | None, formats: str | None = None
) -> None:
    """The indexer: scan the catalog of ``folder`` (indexing ``formats`` when given) and
    report on ``results`` until done or told to stop on ``commands``."""
    if hasattr(os, "nice"):
        try:
            os.nice(10)
        except OSError:
            pass
    from solidseas import catalog, model

    cancel = threading.Event()

    def listen() -> None:
        try:
            while not cancel.is_set():
                if commands.poll(0.2):
                    commands.recv_bytes(64)
                    cancel.set()
        except (EOFError, OSError):
            cancel.set()

    threading.Thread(target=listen, name="solidseas-indexer-commands", daemon=True).start()
    last = [0.0]

    def progress(phase: str, done: int, total: int) -> None:
        now = time.monotonic()
        if now - last[0] >= PROGRESS_EVERY_S:
            last[0] = now
            _send(results, {"progress": {"phase": phase, "done": done, "total": total}})

    try:
        path, _location, name = catalog.locate(folder, cache_dir=cache_dir)
        roots = folder
        if os.path.isfile(path):  # one the command line made may have library roots too: keep them
            try:
                with catalog.Catalog(path, location="cache", name=name, roots=None, mode="r") as old:
                    if folder_in(old.roots, folder):
                        roots = None
            except Exception:  # damaged or too new: opening it for writing says why
                pass
        from solidseas.errors import BusyError

        for attempt in range(5):
            try:
                cat = catalog.open(roots, name=name, cache_dir=cache_dir)
                break
            except BusyError:  # a reader may hold the lock for an instant to see whether a writer lives
                if attempt == 4 or cancel.is_set():
                    raise
                time.sleep(0.2)
        with cat:
            if formats is not None:
                cat.configure(formats=formats)
            _send(results, {"started": {"db": cat.path}})
            data = cat.scan(workers=WORKERS, progress=progress, cancel=cancel)
            _send(results, {"done": {"db": cat.path, "data": data}})
    except Exception as exc:
        _send(results, {"error": model.error_info(exc, reader_message=False)})


def folder_in(roots, folder: str) -> bool:
    """Whether ``folder`` is one of ``roots`` (compared as the filesystem compares names)."""
    from solidseas.resolve.names import fold

    key = fold(os.path.normpath(folder))
    return any(fold(os.path.normpath(r.path)) == key for r in roots)


class Indexer:
    """Runs one folder's indexing at a time in a child process. :meth:`run` runs in a
    worker thread and blocks until the scan ends; :meth:`stop` comes from the UI thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Any = None
        self._commands: Any = None
        self._job: Any = None
        self._stop = threading.Event()
        self.started = 0  # processes started, for tests

    def stop(self) -> None:
        """Ask the running scan to stop (it keeps what it committed)."""
        self._stop.set()
        with self._lock:
            commands = self._commands
        if commands is not None:
            try:
                commands.send_bytes(b"stop")
            except (OSError, ValueError):
                pass

    @property
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.is_alive()

    def run(
        self,
        folder: str,
        emit: Callable[[dict[str, Any]], None],
        cancelled: Callable[[], bool] = lambda: False,
        *,
        cache_dir: str | None = None,
        formats: str | None = None,
    ) -> dict[str, Any]:
        """Index ``folder`` (the formats ``formats`` names, when given: ``solidworks`` or
        ``all``): ``emit`` gets ``{"started": {"db"}}`` and then
        ``{"progress": {"phase", "done", "total"}}`` as it goes; the result is
        ``{"ok": True, "db", "data"}`` (the ``catalog_scan`` data), or ``{"ok": False,
        "error"}``, or ``{"ok": False, "stopped": True}``."""
        from .meshproc import _Job

        self._stop.clear()
        ctx = multiprocessing.get_context("spawn")
        cmd_read, cmd_write = ctx.Pipe(duplex=False)
        res_read, res_write = ctx.Pipe(duplex=False)
        proc = ctx.Process(
            target=_serve,
            args=(cmd_read, res_write, folder, cache_dir, formats),
            name="SolidSeas indexer",
            # not a daemon: a daemon process may not start the worker processes it reads with.
            # It is ended below however the scan ends, and on Windows with the viewer too.
            daemon=False,
        )
        proc.start()
        cmd_read.close()
        res_write.close()
        job = _Job.contain(proc.pid, MEMORY_LIMIT)
        with self._lock:
            self._proc, self._commands, self._job = proc, cmd_write, job
            self.started += 1
        result: dict[str, Any] = {"ok": False, "stopped": True}
        asked = None
        try:
            while True:
                if (cancelled() or self._stop.is_set()) and asked is None:
                    asked = time.monotonic()
                    try:
                        cmd_write.send_bytes(b"stop")
                    except (OSError, ValueError):
                        pass
                if asked is not None and time.monotonic() - asked > STOP_WAIT_S:
                    break
                try:
                    ready = res_read.poll(0.1)
                except (OSError, ValueError):
                    break
                if not ready:
                    if not proc.is_alive():
                        break
                    continue
                try:
                    message = json.loads(res_read.recv_bytes(64 << 20))
                except (EOFError, OSError, ValueError):
                    break
                if not isinstance(message, dict):
                    break
                if "done" in message:
                    done = message["done"]
                    result = {"ok": True, "db": done.get("db"), "data": done.get("data")}
                    break
                if "error" in message:
                    result = {"ok": False, "error": message["error"]}
                    break
                emit(message)
        finally:
            proc.join(STOP_WAIT_S if asked is None else 0.5)
            if proc.is_alive():
                proc.kill()
                proc.join(2)
            for conn in (cmd_write, res_read):
                try:
                    conn.close()
                except OSError:
                    pass
            if job is not None:
                job.close()
            with self._lock:
                self._proc = self._commands = self._job = None
        if asked is not None and not result.get("ok"):
            result = {"ok": False, "stopped": True}
        return result


__all__ = ["DEFAULT_ON", "Indexer", "MEMORY_LIMIT", "STOP_WAIT_S", "load_enabled", "save_enabled"]
