"""One writer per SOLIDWORKS session.

Before an Automatic run starts, and before approved Review mode code runs,
SolidSeas takes the named mutex ``Local\\SolidSeas-Live-<SOLIDWORKS pid>`` and
holds it until the run or script ends. The mutex object is used as a token:
whoever creates it holds the session, and anyone who finds it already there
(``ERROR_ALREADY_EXISTS``), or may not open it, is refused. Because it is never
waited on, any thread may release it, and Windows removes it when the process
that holds it ends, crash included.

Elsewhere than Windows, where there is no live SOLIDWORKS, a set inside this
process stands in for it, so the same rules can be tested.
"""

from __future__ import annotations

import sys
import threading

BUSY_MESSAGE = "Another SolidSeas run is working in this SOLIDWORKS session."
ERROR_ALREADY_EXISTS = 183


class WriterBusyError(Exception):
    """Another window, process or script holds this SOLIDWORKS session."""

    def __init__(self, message: str = BUSY_MESSAGE) -> None:
        super().__init__(message)


def mutex_name(sw_pid: int) -> str:
    if type(sw_pid) is not int or not 0 < sw_pid < 2**32:
        raise ValueError("a SOLIDWORKS process id is a positive whole number")
    return f"Local\\SolidSeas-Live-{sw_pid}"


_held_here: set[int] = set()
_here_lock = threading.Lock()


class WriterHold:
    """The session, held. :meth:`release` gives it back; releasing twice does nothing."""

    def __init__(self, sw_pid: int, handle: int | None) -> None:
        self.sw_pid = sw_pid
        self._handle = handle
        self._lock = threading.Lock()
        self._released = False

    @property
    def held(self) -> bool:
        return not self._released

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        if self._handle is not None:
            _kernel32().CloseHandle(self._handle)
        else:
            with _here_lock:
                _held_here.discard(self.sw_pid)

    def __enter__(self) -> WriterHold:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


_k32 = None


def _kernel32():
    global _k32
    if _k32 is None:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _k32 = k
    return _k32


def take_writer(sw_pid: int) -> WriterHold:
    """Take the session of SOLIDWORKS process ``sw_pid``, or raise :class:`WriterBusyError`."""
    name = mutex_name(sw_pid)
    if sys.platform == "win32":
        import ctypes

        k = _kernel32()
        ctypes.set_last_error(0)  # type: ignore[attr-defined]
        handle = k.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()  # type: ignore[attr-defined]
        if not handle:
            raise WriterBusyError()  # it exists and may not be opened: someone else holds it
        if error == ERROR_ALREADY_EXISTS:
            k.CloseHandle(handle)
            raise WriterBusyError()
        return WriterHold(sw_pid, handle)
    with _here_lock:
        if sw_pid in _held_here:
            raise WriterBusyError()
        _held_here.add(sw_pid)
    return WriterHold(sw_pid, None)


__all__ = ["BUSY_MESSAGE", "WriterBusyError", "WriterHold", "mutex_name", "take_writer"]
