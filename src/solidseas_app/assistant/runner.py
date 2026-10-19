"""The one module that starts an interpreter for code a person approved: Review mode's
scripts (and, later, the CadQuery workspace's).

The script runs in a child Python process (:mod:`.child`), never in the app:

* **Contained.** On Windows the child is put in a Job Object with kill-on-close, a
  process memory cap and a bound on the processes it may start, before it is sent
  the code; closing the job ends it and anything it started, and the job closes by
  itself if the app dies. On Linux and macOS it has its own process group, which is
  killed, and ``RLIMIT_AS`` caps its memory. An allocation over the cap is a
  ``MemoryError`` in the script, reported as such.
* **Bounded in time.** A script still running when its time is up is killed, and so
  is one the person stops. Either way the app carries on, and the next script gets a
  new child.
* **Its only way to SOLIDWORKS is the app.** The script's
  :mod:`solidseas.swapi.live` requests come here as JSON lines; only the operations
  of :func:`allowed_operations` are passed to ``forward`` (the session the person
  picked), which runs on this module's own thread, never on the Qt thread.
* **Its output is data.** What it prints arrives as text through ``on_output``, cut
  off past :data:`MAX_OUTPUT_CHARS` with a count of what was left out, and the window
  shows it as plain text.

It caps resources and keeps the window alive. It is not a sandbox: the script runs
with the person's own rights, and their approval is the control
(``docs/ASSISTANT.md``, Review mode).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_SECONDS = 300.0
DEFAULT_MEMORY_MB = 2048
MAX_LINE = 4 * 1024 * 1024
MAX_OUTPUT_CHARS = 200_000
MAX_CALLS = 10_000
CHILD_PROCESSES = 16  # a script may start a helper or two, never a fork bomb
CHILD_FLAG = "--assistant-child"
READY_SECONDS = 30.0


@dataclass(frozen=True)
class RunResult:
    """How a script ended: ``status`` is ``done``, ``error`` (it raised; ``message`` is
    its traceback), ``memory``, ``timeout``, ``stopped``, ``crashed`` (the child ended
    without saying why) or ``failed`` (it could not be started)."""

    status: str
    message: str
    seconds: float
    calls: int
    output_dropped: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "done"


def allowed_operations() -> frozenset[str]:
    """What a script may ask for: the read-only queries and the vocabulary's operations."""
    from solidseas.ai.prompts import OPERATIONS
    from solidseas.swapi.live import QUERIES

    return frozenset(QUERIES) | frozenset(OPERATIONS)


def child_command(python: str | None = None) -> list[str]:
    """How the child is started: this Python, isolated from the environment's Python
    settings, running :mod:`.child`; in the packaged app, the app itself with
    :data:`CHILD_FLAG`."""
    if getattr(sys, "frozen", False) and python is None:
        return [sys.executable, CHILD_FLAG]
    import solidseas_app

    root = os.path.dirname(os.path.dirname(os.path.abspath(solidseas_app.__file__)))
    boot = f"import sys; sys.path.insert(0, {root!r}); from solidseas_app.assistant.child import main; main()"
    return [python or sys.executable, "-I", "-X", "utf8", "-u", "-c", boot]


def _posix_limits(memory_bytes: int):  # pragma: no cover - runs in the child before exec
    def limit() -> None:
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ValueError, OSError):
            pass
        if sys.platform.startswith("linux"):
            try:
                import ctypes

                ctypes.CDLL(None).prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL: end with the app
            except Exception:
                pass

    return limit


class Runner:
    """Runs one script at a time. ``forward(op, args)`` answers the script's requests
    (it may raise; its message goes back to the script as a refusal)."""

    def __init__(
        self,
        forward: Callable[[str, dict], Any] | None = None,
        *,
        seconds: float = DEFAULT_SECONDS,
        memory_mb: int = DEFAULT_MEMORY_MB,
        python: str | None = None,
    ) -> None:
        if not 0 < seconds <= 86_400:
            raise ValueError("a script's time limit is more than 0 and at most a day")
        if not 64 <= memory_mb <= 64 * 1024:
            raise ValueError("a script's memory cap is from 64 MB to 64 GB")
        self.forward = forward
        self.seconds = float(seconds)
        self.memory_bytes = int(memory_mb) * 1024 * 1024
        self.python = python
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._job: Any = None
        self._ending: str | None = None  # why the app ended the child: stopped or timeout
        self._thread: threading.Thread | None = None
        self.allowed = allowed_operations()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def run(
        self,
        code: str,
        *,
        language: str = "python",
        on_output: Callable[[str, str], None] | None = None,
        on_done: Callable[[RunResult], None] | None = None,
    ) -> None:
        """Start ``code`` and return at once; ``on_output(kind, text)`` and ``on_done``
        are called from the runner's thread."""
        if not isinstance(code, str) or not code.strip():
            raise ValueError("there is no code to run")
        if language not in ("python", "cadquery"):
            raise ValueError("a script is python or cadquery")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a script is already running")
            self._ending = None
            t = threading.Thread(
                target=self._main,
                args=(code, language, on_output, on_done),
                name="assistant-runner",
                daemon=True,
            )
            self._thread = t
        t.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the script to end; True when it has."""
        with self._lock:
            t = self._thread
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    def stop(self) -> None:
        """End the script now (Stop)."""
        self._end("stopped")

    def _end(self, why: str) -> None:
        with self._lock:
            if self._ending is None:
                self._ending = why
            proc, job = self._proc, self._job
        if proc is None:
            return
        try:
            if job is not None:
                job.close()  # kill-on-close: the child and anything it started
            elif sys.platform != "win32":
                import signal

                os.killpg(proc.pid, signal.SIGKILL)
            else:  # pragma: no cover - a child the job could not take
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass

    # ----------------------------------------------------------------- the runner's thread
    def _start(self) -> subprocess.Popen:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "close_fds": True,
        }
        if sys.platform == "win32":  # pragma: no cover - Windows
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
            kwargs["preexec_fn"] = _posix_limits(self.memory_bytes)
        proc = subprocess.Popen(child_command(self.python), **kwargs)
        if sys.platform == "win32":  # pragma: no cover - Windows
            from solidseas.workers import _JobObject  # type: ignore[attr-defined]

            job = _JobObject(CHILD_PROCESSES, self.memory_bytes)
            try:
                job.assign(proc.pid)
            except OSError:
                job.close()
                proc.kill()
                raise
            self._job = job
        return proc

    def _main(self, code, language, on_output, on_done) -> None:
        t0 = time.monotonic()
        calls = 0
        dropped = 0
        shown = 0
        stderr_tail: list[str] = []

        def output(kind: str, text: str) -> None:
            nonlocal dropped, shown
            if shown >= MAX_OUTPUT_CHARS:
                dropped += len(text)
                return
            keep = text[: MAX_OUTPUT_CHARS - shown]
            dropped += len(text) - len(keep)
            shown += len(keep)
            if on_output is not None and keep:
                try:
                    on_output(kind, keep)
                except Exception:
                    pass

        def finish(status: str, message: str) -> None:
            with self._lock:
                job, self._job, self._proc = self._job, None, None
            if job is not None:
                job.close()
            result = RunResult(status, message, time.monotonic() - t0, calls, dropped)
            if on_done is not None:
                try:
                    on_done(result)
                except Exception:
                    pass

        try:
            proc = self._start()
        except Exception as exc:
            finish("failed", f"the script could not be started: {exc}")
            return
        with self._lock:
            self._proc = proc
            early = self._ending
        if early is not None:  # Stop pressed while it started
            self._end(early)

        def read_stderr() -> None:
            for line in proc.stderr:
                stderr_tail.append(line.rstrip()[:500])
                del stderr_tail[:-20]

        threading.Thread(target=read_stderr, name="assistant-runner-stderr", daemon=True).start()
        timer = threading.Timer(self.seconds, self._end, args=("timeout",))
        timer.daemon = True
        timer.start()
        status, message = "crashed", ""
        try:
            first = proc.stdout.readline(MAX_LINE)
            if not first or json.loads(first).get("ready") is not True:
                raise EOFError
            proc.stdin.write(json.dumps({"code": code, "language": language, "name": "<script>"}) + "\n")
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline(MAX_LINE)
                if not line:
                    break
                if not line.endswith("\n"):
                    raise ValueError("a line from the script's process is too long")
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    raise ValueError("the script's process sent something that is not a message")
                if "out" in msg or "err" in msg:
                    kind = "out" if "out" in msg else "err"
                    output(kind, str(msg[kind]))
                elif "call" in msg:
                    calls += 1
                    reply = self._answer(msg, calls)
                    proc.stdin.write(json.dumps(reply, allow_nan=False) + "\n")
                    proc.stdin.flush()
                elif "done" in msg:
                    if msg["done"] is True:
                        status, message = "done", ""
                    else:
                        status = "memory" if msg.get("kind") == "memory" else "error"
                        message = str(msg.get("error", ""))[:20_000]
                    break
        except (OSError, ValueError, EOFError):
            pass  # the child ended or broke the protocol: why is decided below
        finally:
            timer.cancel()
        with self._lock:
            ending = self._ending
        if status not in ("done", "error", "memory") or ending is not None:
            if ending is None:
                # its output closed because it is ending by itself: let it, so it keeps
                # its own exit code rather than the one ending the job gives it
                try:
                    proc.wait(2)
                except subprocess.TimeoutExpired:
                    pass
            self._end(ending or "crashed")
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a child that would not end
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        if ending == "stopped":
            status, message = "stopped", "you stopped the script"
        elif ending == "timeout":
            status, message = "timeout", f"the script ran longer than {self.seconds:g} s and was ended"
        elif status == "crashed":
            tail = "\n".join(stderr_tail[-5:])
            message = f"the script's process ended without finishing (exit code {proc.returncode})"
            if tail:
                message += f":\n{tail}"
        finish(status, message)

    def _answer(self, msg: dict, n: int) -> dict:
        rid = msg.get("call")
        op, args = msg.get("op"), msg.get("args")
        if n > MAX_CALLS:
            return {"reply": rid, "ok": False, "error": {"code": "refused", "message": "too many requests"}}
        if not isinstance(op, str) or op not in self.allowed:
            return {
                "reply": rid,
                "ok": False,
                "error": {
                    "code": "unknown_operation",
                    "message": f"{str(op)[:64]!r} is not an operation a script may use",
                },
            }
        if not isinstance(args, dict):
            return {
                "reply": rid,
                "ok": False,
                "error": {"code": "refused", "message": "arguments are an object"},
            }
        if self.forward is None:
            return {
                "reply": rid,
                "ok": False,
                "error": {"code": "no_document", "message": "no SOLIDWORKS document is picked"},
            }
        try:
            result = self.forward(op, args)
            json.dumps(result, allow_nan=False)
        except Exception as exc:
            code = getattr(exc, "code", "failed")
            return {"reply": rid, "ok": False, "error": {"code": str(code), "message": str(exc)[:2000]}}
        return {"reply": rid, "ok": True, "result": result}


__all__ = [
    "CHILD_FLAG",
    "DEFAULT_MEMORY_MB",
    "DEFAULT_SECONDS",
    "MAX_OUTPUT_CHARS",
    "RunResult",
    "Runner",
    "allowed_operations",
    "child_command",
]
