"""Putting back the registry values SolidSeas' own SOLIDWORKS changed (Windows).

SOLIDWORKS keeps its settings and its layout under ``HKEY_CURRENT_USER\\Software\\SolidWorks``,
shared by every SOLIDWORKS of the Windows account. The instance the bridge starts for batch work
writes there although the bridge sets nothing (the swapi README's side effects, and
``docs/SOLIDWORKS_API_TRAPS.md``): ``General\\Last Splash Id`` and toolbar values under ``User
Interface\\Custom API Toolbars`` when it starts (measured 2026-10-05), and, while it is the only
SOLIDWORKS running, the CommandManager context tabs under ``User Interface`` (148 values, measured
2026-10-14, SolidSeas-l4mk). The user chose to have them put back once the instance has ended
(SolidSeas-1k3).

:class:`RegistryRestore` reads the values in :data:`SCOPE` before the instance starts, watches
for other SOLIDWORKS processes while it runs, reads the values again once it has ended, and puts
back each one that changed, under these rules:

* Only when no other SOLIDWORKS ran at any moment of the instance's life. A SOLIDWORKS the user
  runs writes the same values, and putting them back would undo the user's own changes. The
  processes named ``SLDWORKS.exe`` are looked at every :data:`WATCH_S` seconds; when they cannot
  be listed, nothing is put back.
* Only the values in :data:`SCOPE`, under each ``SOLIDWORKS <year>`` key, and only under a key
  that was there before the instance started, so what the first start of a new version makes is
  left alone.
* Each value only if it still holds what it held once the instance had ended, read again just
  before it is written, and only a value of a type that reads and writes back unchanged
  (strings, numbers and binary data).
* Writes go only under ``Software\\SolidWorks``: :class:`WinRegistry` refuses any other key.

The recent documents list, which every document the instance opens joins, is not in the scope:
where SOLIDWORKS keeps it has not been measured yet.
"""

from __future__ import annotations

import re
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

ROOT = r"Software\SolidWorks"
_VERSION = re.compile(r"SOLIDWORKS \d{4}")
# What is put back, under each SOLIDWORKS <year> key: a key and the one value named, or every
# value in and below the key (None).
SCOPE: tuple[tuple[str, str | None], ...] = (
    ("User Interface", None),  # the toolbars, and the CommandManager tabs (SolidSeas-l4mk)
    ("General", "Last Splash Id"),
)
WATCH_S = 2.0  # how often the processes are looked at while the instance runs
MAX_VALUES = 50_000  # a reading larger than this is refused, and nothing is put back
# Registry value types that winreg reads and writes back unchanged.
REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD = 1, 2, 3, 4, 7, 11
ROUND_TRIP = frozenset({REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD})

Value = tuple[int, Any]  # (registry type, data), as winreg gives them


class Registry(Protocol):
    """What the restore needs from ``HKEY_CURRENT_USER``, with winreg's semantics: each call
    raises ``FileNotFoundError`` when the key or value is absent and another ``OSError`` when it
    cannot be read or written. Paths are key paths under the hive, such as ``Software\\SolidWorks``."""

    def subkeys(self, path: str) -> list[str]: ...

    def values(self, path: str) -> dict[str, Value]: ...

    def value(self, path: str, name: str) -> Value: ...

    def set_value(self, path: str, name: str, value: Value) -> None: ...

    def delete_value(self, path: str, name: str) -> None: ...


@dataclass(frozen=True)
class Reading:
    """The values in the scope at one moment, by (key path, value name), and the scope's keys
    that were there then: (key path, the value name, or None for the whole key)."""

    values: dict[tuple[str, str], Value]
    roots: frozenset[tuple[str, str | None]]

    def covers(self, path: str, name: str) -> bool:
        """Whether a value lies in a part of the scope that was there in this reading."""
        for root, only in self.roots:
            if only is None and (path == root or path.startswith(root + "\\")):
                return True
            if only is not None and path == root and name == only:
                return True
        return False


def _exists(registry: Registry, path: str) -> bool:
    try:
        registry.subkeys(path)
    except FileNotFoundError:
        return False
    return True


def read(registry: Registry, scope: Iterable[tuple[str, str | None]] = SCOPE) -> Reading:
    """The values in ``scope`` now. Raises ``OSError`` when they cannot all be read."""
    values: dict[tuple[str, str], Value] = {}
    roots: set[tuple[str, str | None]] = set()
    try:
        versions = registry.subkeys(ROOT)
    except FileNotFoundError:
        versions = []
    for version in sorted(versions):
        if not _VERSION.fullmatch(version):
            continue
        for key, only in scope:
            path = f"{ROOT}\\{version}\\{key}"
            if not _exists(registry, path):
                continue
            roots.add((path, only))
            if only is not None:
                try:
                    values[(path, only)] = registry.value(path, only)
                except FileNotFoundError:
                    pass
                continue
            stack = [path]
            while stack:
                here = stack.pop()
                try:
                    for name, value in registry.values(here).items():
                        values[(here, name)] = value
                    stack.extend(f"{here}\\{sub}" for sub in registry.subkeys(here))
                except FileNotFoundError:
                    continue  # removed while it was read
                if len(values) > MAX_VALUES:
                    raise OSError(f"more than {MAX_VALUES:,} values under {path}")
    return Reading(values, frozenset(roots))


@dataclass(frozen=True)
class Change:
    """One value the instance changed: what it was before (None: it was not there, so it is
    deleted) and what the instance left (None: the instance deleted it)."""

    path: str
    name: str
    before: Value | None
    written: Value | None


def changes(before: Reading, after: Reading) -> list[Change]:
    """The values that differ between the two readings, in a part of the scope that was there
    before."""
    found = []
    for path, name in sorted(before.values.keys() | after.values.keys()):
        old, new = before.values.get((path, name)), after.values.get((path, name))
        if old != new and before.covers(path, name):
            found.append(Change(path, name, old, new))
    return found


@dataclass
class PutBack:
    """What :func:`put_back` did: the values put back, those changed again since (left as they
    are), and those not written, each with the reason."""

    restored: list[Change] = field(default_factory=list)
    changed_since: list[Change] = field(default_factory=list)
    not_written: list[tuple[Change, str]] = field(default_factory=list)


def put_back(registry: Registry, found: Iterable[Change]) -> PutBack:
    """Put each value back as it was before, if it still holds what the instance left."""
    done = PutBack()
    for c in found:
        if c.before is not None and c.before[0] not in ROUND_TRIP:
            done.not_written.append((c, f"it is of registry type {c.before[0]}"))
            continue
        try:
            try:
                now = registry.value(c.path, c.name)
            except FileNotFoundError:
                now = None
            if now != c.written:
                done.changed_since.append(c)
                continue
            if c.before is None:
                registry.delete_value(c.path, c.name)
            else:
                registry.set_value(c.path, c.name, c.before)
        except OSError as exc:
            done.not_written.append((c, str(exc) or type(exc).__name__))
            continue
        done.restored.append(c)
    return done


def solidworks_pids() -> set[int]:
    """The ids of the processes named ``SLDWORKS.exe`` on this machine, in any session (Windows;
    elsewhere none). Raises ``OSError`` when they cannot be listed."""
    if sys.platform != "win32":
        return set()
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    snapshot = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        pids = set()
        more = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not more:
            raise ctypes.WinError(ctypes.get_last_error())
        while more:
            if entry.szExeFile.lower() == "sldworks.exe":
                pids.add(int(entry.th32ProcessID))
            more = k32.Process32NextW(snapshot, ctypes.byref(entry))
        return pids
    finally:
        k32.CloseHandle(snapshot)


class SolidWorksWatch:
    """Every ``SLDWORKS.exe`` process seen from :meth:`start` to :meth:`stop`, looked at every
    ``interval`` seconds on a thread of its own."""

    def __init__(
        self, list_pids: Callable[[], set[int]] = solidworks_pids, interval: float = WATCH_S
    ) -> None:
        self._list = list_pids
        self.interval = interval
        self._seen: set[int] = set()
        self._blind = False  # a look failed, so a SOLIDWORKS may have run unseen
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def _look(self) -> None:
        try:
            pids = set(self._list())
        except Exception:  # a look that fails means nothing was seen, not that nothing ran
            with self._lock:
                self._blind = True
            return
        with self._lock:
            self._seen |= pids

    def _run(self) -> None:
        while not self._stopping.wait(self.interval):
            self._look()

    def start(self) -> None:
        self._look()
        self._thread = threading.Thread(target=self._run, name="swapi-sldworks-watch", daemon=True)
        self._thread.start()

    def stop(self) -> set[int] | None:
        """Stop watching: the processes seen, or None when a look failed."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(max(5.0, 2 * self.interval))
        self._look()
        with self._lock:
            return None if self._blind else set(self._seen)


@dataclass(frozen=True)
class Outcome:
    """What :meth:`RegistryRestore.finish` found and did. ``done`` is None when nothing was put
    back: another SOLIDWORKS ran (``others``), whether one ran could not be told (``unknown``),
    or SolidSeas' own did not start, so its process could not be told from others
    (``not_started``)."""

    changed: list[Change]
    done: PutBack | None
    others: tuple[int, ...] = ()
    unknown: bool = False
    not_started: bool = False

    def message(self) -> str | None:
        """A line for the log, or None when nothing in the scope changed."""
        count = len(self.changed)
        if not count:
            return None
        values = f"{count} registry value{'' if count == 1 else 's'}"
        where = r"under HKEY_CURRENT_USER\Software\SolidWorks"
        if self.done is None:
            pids = ", ".join(str(p) for p in self.others[:5])
            if self.unknown:
                why = "whether another SOLIDWORKS ran meanwhile could not be told"
            elif self.not_started:
                why = (f"SolidSeas' SOLIDWORKS did not start, so it cannot be told from the SOLIDWORKS "
                       f"that ran (PID {pids})")
            else:
                why = f"another SOLIDWORKS ran meanwhile (PID {pids})"
            left = "it is left as it is" if count == 1 else "they are left as they are"
            return f"{values} {where} changed while SolidSeas' SOLIDWORKS ran; {why}, so {left}"
        done = self.done
        text = f"put back {len(done.restored)} of the {values} SolidSeas' SOLIDWORKS changed {where}"
        if done.changed_since:
            text += f"; {len(done.changed_since)} changed again since, so left as they are"
        if done.not_written:
            text += f"; {len(done.not_written)} not written back ({done.not_written[0][1]})"
        return text


class RegistryRestore:
    """Puts back what SolidSeas' SOLIDWORKS changed in the registry (module notes): call
    :meth:`begin` just before ``start_solidworks``, and :meth:`finish` once the instance has
    ended, with its process id when it is known."""

    def __init__(
        self,
        registry: Registry,
        list_pids: Callable[[], set[int]] = solidworks_pids,
        *,
        scope: Iterable[tuple[str, str | None]] = SCOPE,
        interval: float = WATCH_S,
    ) -> None:
        self._registry = registry
        self._scope = tuple(scope)
        self._watch = SolidWorksWatch(list_pids, interval)
        self._before: Reading | None = None

    @classmethod
    def for_this_system(cls) -> RegistryRestore | None:
        """The restore on Windows; None elsewhere, where no SOLIDWORKS is started."""
        if sys.platform != "win32":
            return None
        return cls(WinRegistry())

    def begin(self) -> None:
        """Start watching for other SOLIDWORKS processes, then read the values. Raises
        ``OSError`` when they cannot be read; the watch is stopped again then."""
        self._watch.start()
        try:
            self._before = read(self._registry, self._scope)
        except BaseException:
            self._watch.stop()
            raise

    def finish(self, own_pid: int | None) -> Outcome:
        """Stop watching, read the values again and put back what changed, if no other
        SOLIDWORKS ran. ``own_pid`` is the instance's process (None when its start failed before
        it was known: then it counts as another, and nothing is put back). Raises ``OSError``
        when the values cannot be read."""
        seen = self._watch.stop()
        if self._before is None:
            raise RuntimeError("begin was not called")
        found = changes(self._before, read(self._registry, self._scope))
        if seen is None:
            return Outcome(found, None, unknown=True)
        others = tuple(sorted(seen - {own_pid}))
        if others:
            return Outcome(found, None, others=others, not_started=own_pid is None)
        return Outcome(found, put_back(self._registry, found))


class WinRegistry:
    """:class:`Registry` over ``HKEY_CURRENT_USER`` through winreg, in the registry view of the
    running Python (``Software\\SolidWorks`` is shared by both views). It writes only under
    ``root``."""

    def __init__(self, root: str = ROOT) -> None:
        import winreg

        self._winreg = winreg
        self.root = root.strip("\\")

    def _writable(self, path: str) -> bool:
        p, r = path.casefold(), self.root.casefold()
        return p == r or p.startswith(r + "\\")

    def _open(self, path: str, access: int) -> Any:
        w = self._winreg
        return w.OpenKey(w.HKEY_CURRENT_USER, path, 0, access)

    def subkeys(self, path: str) -> list[str]:
        w = self._winreg
        with self._open(path, w.KEY_READ) as key:
            count = w.QueryInfoKey(key)[0]
            return [w.EnumKey(key, i) for i in range(count)]

    def values(self, path: str) -> dict[str, Value]:
        w = self._winreg
        with self._open(path, w.KEY_READ) as key:
            count = w.QueryInfoKey(key)[1]
            out: dict[str, Value] = {}
            for i in range(count):
                name, data, kind = w.EnumValue(key, i)
                out[name] = (kind, data)
            return out

    def value(self, path: str, name: str) -> Value:
        w = self._winreg
        with self._open(path, w.KEY_READ) as key:
            data, kind = w.QueryValueEx(key, name)
            return (kind, data)

    def set_value(self, path: str, name: str, value: Value) -> None:
        if not self._writable(path):
            raise PermissionError(f"not under {self.root}: {path}")
        w = self._winreg
        kind, data = value
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, path, 0, w.KEY_SET_VALUE) as key:
            w.SetValueEx(key, name, 0, kind, data)

    def delete_value(self, path: str, name: str) -> None:
        if not self._writable(path):
            raise PermissionError(f"not under {self.root}: {path}")
        w = self._winreg
        with self._open(path, w.KEY_SET_VALUE) as key:
            w.DeleteValue(key, name)


__all__ = [
    "MAX_VALUES",
    "ROOT",
    "ROUND_TRIP",
    "SCOPE",
    "WATCH_S",
    "Change",
    "Outcome",
    "PutBack",
    "Reading",
    "Registry",
    "RegistryRestore",
    "SolidWorksWatch",
    "WinRegistry",
    "changes",
    "put_back",
    "read",
    "solidworks_pids",
]
