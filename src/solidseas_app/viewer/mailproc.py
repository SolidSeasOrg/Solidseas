"""Email PDF's attach route: Simple MAPI in a process of its own (``docs/DRAWINGS.md``
15.5, step 3).

A mail program's Simple MAPI library is loaded into the process that calls it, and
can crash it or hang it; the packaged viewer would also search its own bundle's
libraries first. So the call runs in a child process started for it alone
(:func:`send_in_process`), and the window only waits on a pipe, from a worker
thread, since the call blocks while the compose window is open:

* The child restores the default library search order (``SetDllDirectoryW(NULL)``),
  loads ``mapi32.dll`` from the system folder by its full path, and calls
  ``MAPISendMailW`` with ``MAPI_DIALOG | MAPI_LOGON_UI``: the mail program's compose
  window opens with the PDF attached (a ``MapiFileDescW`` with ``nPosition`` -1, the
  PDF's full path and its name), no recipient (the user types it), the subject the
  drawing number and title, and no body. When the wide function is missing or
  fails, it calls ``MAPISendMail`` with a copy of the PDF under a plain ASCII name in
  a temporary folder of its own, removed when the call returns. It writes the return
  code to its pipe and exits (:func:`mapi_send`).
* The window gets an :class:`AttachResult`: code 0 (the message went to the mail
  program to send), 1 (the user closed the compose window), another code with the
  reason in words (:func:`code_text`), or no code and the reason: the child ended
  without answering (a crash), the time limit passed (:data:`TIME_LIMIT`; the child
  is then ended), or Simple MAPI is not there (any system but Windows says so).
  Anything but 0 and 1 sends Email PDF to webmail with that reason.
* What crosses the pipe is JSON both ways, a few hundred bytes, never a pickle.
  Nothing here holds a password or opens a connection: the mail program does
  whatever it does with the message, after the user presses its Send.

The child is not put in a job object, unlike the mesh reader's: a mail program the
call starts (Outlook or Thunderbird when it is not running) would join the job and be
ended with it. Tests stand in for the library call with ``send`` (the real call is a
Windows check on the PC with the user present, ``docs/DRAWINGS.md`` 24, item 7).
"""

import ctypes
import json
import multiprocessing
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

TIME_LIMIT = 3600.0  # seconds: the compose window may stay open while the user writes
POLL_SECONDS = 0.1
MAX_MESSAGE_BYTES = 64 << 10
MAX_TEXT = 1024  # characters of the path, the name and the subject a request may hold

# Simple MAPI (MAPI.H)
MAPI_LOGON_UI = 0x00000001
MAPI_DIALOG = 0x00000008
SUCCESS_SUCCESS = 0
MAPI_USER_ABORT = 1
FLAGS = MAPI_DIALOG | MAPI_LOGON_UI
ATTACH_AT_END = 0xFFFFFFFF  # nPosition -1: the attachment is not placed in the body's text

CODES = {
    2: "the mail program reported a failure",
    3: "signing in to the mail program failed",
    4: "the disk is full",
    5: "there was not enough memory",
    6: "access was denied",
    8: "the mail program had too many sessions open",
    9: "too many files were attached",
    11: "the PDF was not found",
    12: "the PDF could not be opened",
    13: "the PDF could not be written into the message",
    17: "the message was not valid",
    19: "the mail program's session was not valid",
    20: "the attachment's type is not supported",
    22: "the message is in use",
    23: "the network failed",
    26: "the mail program does not support this",
    27: "the mail program does not take Unicode names",
    28: "the PDF is too large for it",
}
STOPPED = "the mail program stopped the process that called it before it answered"
TIMED_OUT = "the mail program did not answer within {limit}, and the call was ended"
UNAVAILABLE = "Simple MAPI is available only on Windows"
NO_ANSWER = "the process that called the mail program gave no answer SolidSeas reads"


def code_text(code: int) -> str:
    """A Simple MAPI return code in words."""
    return CODES.get(code, f"Simple MAPI error {code}")


@dataclass(frozen=True)
class AttachResult:
    """What the attach route came to: Simple MAPI's return ``code`` (None when there is
    none), the ``reason`` it did not attach in words (None on 0 and 1), and whether the
    window ``cancelled`` the wait."""

    code: int | None
    reason: str | None = None
    cancelled: bool = False


class Unavailable(Exception):
    """Simple MAPI cannot be called here: not Windows, or no ``mapi32.dll``."""


# --------------------------------------------------------------------------- the structures (MAPI.H)
_ULONG = ctypes.c_uint32  # Windows' ULONG and FLAGS are 32 bits on every Windows


class MapiFileDescW(ctypes.Structure):
    _fields_ = [
        ("ulReserved", _ULONG),
        ("flFlags", _ULONG),
        ("nPosition", _ULONG),
        ("lpszPathName", ctypes.c_wchar_p),
        ("lpszFileName", ctypes.c_wchar_p),
        ("lpFileType", ctypes.c_void_p),
    ]


class MapiMessageW(ctypes.Structure):
    _fields_ = [
        ("ulReserved", _ULONG),
        ("lpszSubject", ctypes.c_wchar_p),
        ("lpszNoteText", ctypes.c_wchar_p),
        ("lpszMessageType", ctypes.c_wchar_p),
        ("lpszDateReceived", ctypes.c_wchar_p),
        ("lpszConversationID", ctypes.c_wchar_p),
        ("flFlags", _ULONG),
        ("lpOriginator", ctypes.c_void_p),
        ("nRecipCount", _ULONG),
        ("lpRecips", ctypes.c_void_p),
        ("nFileCount", _ULONG),
        ("lpFiles", ctypes.POINTER(MapiFileDescW)),
    ]


class MapiFileDesc(ctypes.Structure):
    _fields_ = [
        ("ulReserved", _ULONG),
        ("flFlags", _ULONG),
        ("nPosition", _ULONG),
        ("lpszPathName", ctypes.c_char_p),
        ("lpszFileName", ctypes.c_char_p),
        ("lpFileType", ctypes.c_void_p),
    ]


class MapiMessage(ctypes.Structure):
    _fields_ = [
        ("ulReserved", _ULONG),
        ("lpszSubject", ctypes.c_char_p),
        ("lpszNoteText", ctypes.c_char_p),
        ("lpszMessageType", ctypes.c_char_p),
        ("lpszDateReceived", ctypes.c_char_p),
        ("lpszConversationID", ctypes.c_char_p),
        ("flFlags", _ULONG),
        ("lpOriginator", ctypes.c_void_p),
        ("nRecipCount", _ULONG),
        ("lpRecips", ctypes.c_void_p),
        ("nFileCount", _ULONG),
        ("lpFiles", ctypes.POINTER(MapiFileDesc)),
    ]


def build_message(path: str, name: str, subject: str = "", *, wide: bool = True):
    """The message ``MAPISendMail(W)`` is given: one attachment, ``path`` shown as
    ``name``, at the end (``nPosition`` -1); the subject when there is one; no body,
    no recipient, no originator. Returns the message and its attachment, which must
    stay alive while the call runs. Without ``wide`` the texts are in the system's
    ANSI code page (``mbcs``; UTF-8 elsewhere, where it is only built for tests)."""
    if wide:
        attachment = MapiFileDescW(0, 0, ATTACH_AT_END, path, name, None)
        message = MapiMessageW()
        message.lpszSubject = subject or None
        message.lpFiles = ctypes.pointer(attachment)
    else:
        codec = "mbcs" if os.name == "nt" else "utf-8"
        attachment = MapiFileDesc(0, 0, ATTACH_AT_END, path.encode(codec), name.encode(codec), None)
        message = MapiMessage()
        message.lpszSubject = subject.encode(codec, "replace") if subject else None
        message.lpFiles = ctypes.pointer(attachment)
    message.nFileCount = 1
    return message, attachment


def _ascii_name(name: str) -> str:
    """``name`` with every character but letters, digits, spaces and ``-_.()`` of ASCII
    replaced by ``_``, ending ``.pdf``."""
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = "".join(c if c.isascii() and (c.isalnum() or c in " -_.()") else "_" for c in stem).strip(" .")
    return (stem[:80] or "drawing") + ".pdf"


def mapi_send(path: str, name: str, subject: str = "") -> int:  # pragma: no cover - Windows
    """The child's call (see the module notes): Simple MAPI's return code. Raises
    :class:`Unavailable` where it cannot be called."""
    if os.name != "nt":
        raise Unavailable(UNAVAILABLE)
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.SetDllDirectoryW.argtypes = (wintypes.LPCWSTR,)
    k32.SetDllDirectoryW(None)  # the default search order, without the packaged viewer's folder
    k32.GetSystemDirectoryW.argtypes = (wintypes.LPWSTR, wintypes.UINT)
    k32.GetSystemDirectoryW.restype = wintypes.UINT
    buf = ctypes.create_unicode_buffer(260)
    n = k32.GetSystemDirectoryW(buf, 260)
    if not 0 < n < 260:
        raise Unavailable("the system folder was not found")
    try:
        mapi = ctypes.WinDLL(os.path.join(buf.value, "mapi32.dll"))
    except OSError:
        raise Unavailable("mapi32.dll could not be loaded") from None
    try:  # the mail program's window may come to the front
        ctypes.WinDLL("user32").AllowSetForegroundWindow(wintypes.DWORD(0xFFFFFFFF))
    except (OSError, AttributeError):
        pass
    code = None
    wide = getattr(mapi, "MAPISendMailW", None)
    if wide is not None:
        wide.argtypes = (ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(MapiMessageW), _ULONG, _ULONG)
        wide.restype = _ULONG
        message, _attachment = build_message(path, name, subject)
        code = int(wide(0, 0, ctypes.byref(message), FLAGS, 0))
        if code in (SUCCESS_SUCCESS, MAPI_USER_ABORT):
            return code
    narrow = getattr(mapi, "MAPISendMail", None)
    if narrow is None:
        if code is None:
            raise Unavailable("mapi32.dll has no MAPISendMail")
        return code
    return _send_narrow(narrow, path, name, subject, code)


def _send_narrow(narrow, path: str, name: str, subject: str, code: int | None) -> int:  # pragma: no cover
    """``MAPISendMail`` with a copy of the PDF under an ASCII name in a temporary folder
    of its own, removed when the call returns; ``code`` (the wide call's) when no such
    copy can be made."""
    import shutil
    import tempfile

    folder = tempfile.mkdtemp(prefix="solidseas-mail-")
    try:
        copy = os.path.join(folder, _ascii_name(name))
        if not copy.isascii():  # a temporary folder under a profile with a name outside ASCII
            return code if code is not None else 11
        shutil.copyfile(path, copy)
        narrow.argtypes = (ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(MapiMessage), _ULONG, _ULONG)
        narrow.restype = _ULONG
        message, _attachment = build_message(copy, os.path.basename(copy), subject, wide=False)
        return int(narrow(0, 0, ctypes.byref(message), FLAGS, 0))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- the child
def _request_problem(request: Any) -> str | None:
    if not isinstance(request, dict):
        return "the request is not an object"
    for key in ("path", "name", "subject"):
        value = request.get(key)
        if not isinstance(value, str) or len(value) > MAX_TEXT or "\x00" in value:
            return f"the request's {key} is not valid"
    if not os.path.isabs(request["path"]) or not request["path"].lower().endswith(".pdf"):
        return "the request's path is not a PDF's"
    return None


def _serve(conn, send: Callable[[str, str, str], int] | None = None) -> None:
    """The child: one JSON request (the PDF's path, its name, the subject), the call
    (``send``, :func:`mapi_send` unless a test stands in for it), and its return code
    sent back as JSON."""
    try:
        request = json.loads(conn.recv_bytes(MAX_MESSAGE_BYTES))
    except (EOFError, OSError, ValueError):
        return
    problem = _request_problem(request)
    if problem is not None:
        answer: dict[str, Any] = {"error": problem}
    else:
        try:
            code = (send or mapi_send)(request["path"], request["name"], request["subject"])
            answer = {"code": int(code)}
        except Unavailable as exc:
            answer = {"unavailable": str(exc)[:MAX_TEXT]}
        except Exception as exc:
            answer = {"error": f"the call failed ({type(exc).__name__})"}
    try:
        conn.send_bytes(json.dumps(answer).encode("utf-8"))
    except (EOFError, OSError, ValueError):
        pass


def _allow_foreground(pid: int) -> None:  # pragma: no cover - Windows
    """Let the child, and the mail program it calls, bring the compose window forward."""
    if os.name != "nt":
        return
    try:
        ctypes.WinDLL("user32").AllowSetForegroundWindow(ctypes.c_uint32(pid))
    except (OSError, AttributeError):
        pass


def _end(proc, conn, *, kill: bool) -> None:
    """Close the pipe, let the child end (at once with ``kill``) and reap it."""
    try:
        conn.close()
    except OSError:
        pass
    try:
        if proc.is_alive():
            if not kill:
                proc.join(2)
            if proc.is_alive():
                proc.kill()
        proc.join(2)
    except (OSError, ValueError, AssertionError):
        pass


def _duration(seconds: float) -> str:
    """``seconds`` in words: "90 seconds", "60 minutes"."""
    if seconds < 120:
        n = max(1, round(seconds))
        return f"{n} second" if n == 1 else f"{n} seconds"
    return f"{round(seconds / 60)} minutes"


def _result(answer: Any) -> AttachResult:
    if not isinstance(answer, dict):
        return AttachResult(None, NO_ANSWER)
    code = answer.get("code")
    if isinstance(code, int) and not isinstance(code, bool) and 0 <= code < 1 << 32:
        if code in (SUCCESS_SUCCESS, MAPI_USER_ABORT):
            return AttachResult(code)
        return AttachResult(code, f"{code_text(code)}, Simple MAPI code {code}")
    if isinstance(answer.get("unavailable"), str):
        return AttachResult(None, answer["unavailable"][:MAX_TEXT] or UNAVAILABLE)
    if isinstance(answer.get("error"), str):
        return AttachResult(None, answer["error"][:MAX_TEXT] or NO_ANSWER)
    return AttachResult(None, NO_ANSWER)


def send_in_process(
    path: str,
    name: str,
    subject: str = "",
    *,
    time_limit: float = TIME_LIMIT,
    cancelled: Callable[[], bool] | None = None,
    send: Callable[[str, str, str], int] | None = None,
) -> AttachResult:
    """Attach the PDF at ``path``, shown as ``name``, to a new message in the default
    mail program, with ``subject`` (none when empty), in a child process (see the
    module notes); waits in this thread without the interpreter lock, so the window
    calls it from a worker thread. ``cancelled()`` true ends the wait and the child;
    past ``time_limit`` seconds the child is ended and the result says so. ``send``
    stands in for :func:`mapi_send` in the child: a function the child can import."""
    cancelled = cancelled or (lambda: False)
    if cancelled():
        return AttachResult(None, cancelled=True)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=_serve, args=(child, send), name="SolidSeas Email PDF", daemon=True)
    proc.start()
    child.close()
    _allow_foreground(proc.pid)
    kill = False
    try:
        parent.send_bytes(json.dumps({"path": path, "name": name, "subject": subject}).encode("utf-8"))
        end = time.monotonic() + time_limit
        # Polled with the child's state too: a child that ended before it took its end of the
        # pipe leaves that end open here, and the pipe never breaks (see .meshproc).
        while not parent.poll(POLL_SECONDS):
            if cancelled():
                kill = True
                return AttachResult(None, cancelled=True)
            if not proc.is_alive():
                if parent.poll(0):  # it answered as it ended
                    break
                return AttachResult(None, STOPPED)
            if time.monotonic() > end:
                kill = True
                return AttachResult(None, TIMED_OUT.format(limit=_duration(time_limit)))
        return _result(json.loads(parent.recv_bytes(MAX_MESSAGE_BYTES)))
    except (EOFError, OSError, ValueError):
        return AttachResult(None, STOPPED)
    finally:
        _end(proc, parent, kill=kill)


__all__ = [
    "TIME_LIMIT",
    "AttachResult",
    "Unavailable",
    "build_message",
    "code_text",
    "mapi_send",
    "send_in_process",
]
