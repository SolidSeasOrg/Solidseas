"""The runner's child process: it runs one script a person approved, and speaks JSON
lines with the app (:mod:`.runner`). Nothing else starts it.

From the app, on standard input: first ``{"code", "language", "name"}``, then one
``{"reply": n, "ok": true, "result": ...}`` or ``{"reply": n, "ok": false, "error":
{"code", "message"}}`` for each request the script made. To the app, on standard
output: ``{"ready": true}`` once it has started, ``{"out": text}`` and ``{"err":
text}`` for what the script prints, ``{"call": n, "op", "args"}`` for each
:mod:`solidseas.swapi.live` request, and last ``{"done": true}`` or ``{"done": false,
"kind", "error"}``.

The script's own ``print`` goes through the ``out`` lines, so nothing it writes can
pass for a protocol line, and it reads an empty standard input. The app has set the
memory cap before it sends the code (on Linux and macOS through ``RLIMIT_AS``, which
this process inherits; on Windows through the Job Object it was put in), so an
allocation over the cap is a ``MemoryError`` here, reported as ``memory``.
"""

import builtins
import io
import json
import os
import sys
import threading
import traceback

MAX_LINE = 4 * 1024 * 1024
FLUSH_AT = 4096


class _Stream(io.TextIOBase):
    """``print`` for the script: whole lines, or 4 KB at a time, as ``out`` or ``err``."""

    def __init__(self, kind: str, send) -> None:
        self.kind, self.send = kind, send
        self.buffer_text = ""
        self.lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text) -> int:
        if not isinstance(text, str):
            text = str(text)
        with self.lock:
            self.buffer_text += text
            if "\n" in self.buffer_text or len(self.buffer_text) >= FLUSH_AT:
                cut = self.buffer_text.rfind("\n") + 1 or len(self.buffer_text)
                out, self.buffer_text = self.buffer_text[:cut], self.buffer_text[cut:]
                self.send({self.kind: out})
        return len(text)

    def flush(self) -> None:
        with self.lock:
            if self.buffer_text:
                out, self.buffer_text = self.buffer_text, ""
                self.send({self.kind: out})


def main() -> None:  # pragma: no cover - runs in the child; tests drive it through the runner
    real_in, real_out = sys.stdin, sys.stdout
    out_lock = threading.Lock()

    def send(obj) -> None:
        line = json.dumps(obj, ensure_ascii=True) + "\n"
        with out_lock:
            real_out.write(line)
            real_out.flush()

    def read() -> dict | None:
        line = real_in.readline(MAX_LINE)
        if not line:
            return None
        return json.loads(line)

    send({"ready": True})
    job = read()
    if not isinstance(job, dict) or not isinstance(job.get("code"), str):
        send({"done": False, "kind": "error", "error": "no script was sent"})
        os._exit(2)

    from solidseas.swapi import live

    call_lock = threading.Lock()
    counter = [0]

    def transport(op: str, args: dict):
        with call_lock:  # one request at a time, even from the script's own threads
            counter[0] += 1
            n = counter[0]
            send({"call": n, "op": op, "args": args})
            reply = read()
        if not isinstance(reply, dict) or reply.get("reply") != n:
            raise live.LiveError("the app did not answer the request", "failed")
        if reply.get("ok"):
            return reply.get("result")
        error = reply.get("error") or {}
        raise live.LiveError(
            str(error.get("message", "the operation failed")), str(error.get("code", "failed"))
        )

    live._connect(transport)
    out, err = _Stream("out", send), _Stream("err", send)
    sys.stdout, sys.stderr, sys.stdin = out, err, io.StringIO("")
    result: dict = {"done": True}
    try:
        code = compile(job["code"], str(job.get("name") or "<script>"), "exec")
        exec(code, {"__name__": "__main__", "__builtins__": builtins})
    except MemoryError:
        result = {"done": False, "kind": "memory", "error": "the script ran out of the memory it may use"}
    except SystemExit as exc:
        if exc.code not in (None, 0):
            result = {"done": False, "kind": "error", "error": f"the script exited with {exc.code!r}"}
    except BaseException:
        kind, value, tb = sys.exc_info()
        frames = traceback.extract_tb(tb)
        # Leave out this module's own frame: the person reads only their script's.
        frames = [f for f in frames if f.filename != __file__]
        text = "".join(traceback.format_list(frames)) + "".join(traceback.format_exception_only(kind, value))
        result = {"done": False, "kind": "error", "error": "Traceback (most recent call last):\n" + text}
    try:
        out.flush()
        err.flush()
    except Exception:
        pass
    send(result)
    real_out.flush()
    os._exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
