"""API keys: kept in Windows Credential Manager, handled as :class:`Secret`.

Each provider's key is one generic credential named ``SolidSeas/<provider>``
(:func:`target_name`), read with ``CredReadW`` and written with ``CredWriteW``
through ctypes, so no package is needed. It is stored with
``CRED_PERSIST_LOCAL_MACHINE``: it belongs to this Windows account on this PC
and does not roam with a roaming profile. Keys are never kept in a settings
file, the repository, the environment or the registry.

A key read from the store is a :class:`Secret`, whose ``repr`` and ``str`` hide
it, so a log line, an exception or a debugger view of a provider never shows
it. Only :meth:`Secret.reveal` returns the text, and only a provider's request
headers call it. The settings page asks :meth:`CredentialStore.is_set` and shows
"set" or "not set".

:class:`MemoryCredentialStore` keeps keys in memory, for tests and for a
platform without Credential Manager; tests never write the real store.
"""

from __future__ import annotations

import ctypes
import re
import sys
import threading
from typing import Any, Protocol

from .errors import CredentialStoreError, InvalidSettingError

TARGET_PREFIX = "SolidSeas/"
MIN_KEY_CHARS = 8
MAX_KEY_CHARS = 1024  # Credential Manager holds at most 2,560 bytes, 1,280 UTF-16 characters
_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_KEY_CHARS = re.compile(r"[\x21-\x7e]+\Z")  # printable ASCII, no spaces

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class Secret:
    """A key that hides itself: ``repr`` and ``str`` never show it, and it does not pickle."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if isinstance(value, Secret):
            value = value.reveal()
        if not isinstance(value, str):
            raise InvalidSettingError("An API key must be text.")
        value = value.strip()
        if not (MIN_KEY_CHARS <= len(value) <= MAX_KEY_CHARS) or not _KEY_CHARS.match(value):
            raise InvalidSettingError(
                f"An API key is {MIN_KEY_CHARS} to {MAX_KEY_CHARS} printable characters without spaces."
            )
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(<hidden>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        import hmac

        return hmac.compare_digest(self._value.encode(), other._value.encode())

    def __hash__(self) -> int:
        return hash(("Secret", len(self._value)))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a Secret cannot be changed")

    def __reduce__(self):
        raise TypeError("a Secret cannot be pickled")


def target_name(provider: str) -> str:
    """The Credential Manager entry for ``provider``: ``SolidSeas/<provider>``."""
    if not isinstance(provider, str) or not _PROVIDER.match(provider):
        raise InvalidSettingError("A provider name is a short lower-case word.")
    return TARGET_PREFIX + provider


class CredentialStore(Protocol):
    def get(self, provider: str) -> Secret | None: ...

    def set(self, provider: str, key: Secret | str) -> None: ...

    def clear(self, provider: str) -> bool: ...

    def is_set(self, provider: str) -> bool: ...


class MemoryCredentialStore:
    """Keys in memory only. Nothing is written anywhere."""

    def __init__(self, keys: dict[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, Secret] = {}
        for provider, key in (keys or {}).items():
            self.set(provider, key)

    def get(self, provider: str) -> Secret | None:
        name = target_name(provider)
        with self._lock:
            return self._keys.get(name)

    def set(self, provider: str, key: Secret | str) -> None:
        name, secret = target_name(provider), Secret(key)
        with self._lock:
            self._keys[name] = secret

    def clear(self, provider: str) -> bool:
        name = target_name(provider)
        with self._lock:
            return self._keys.pop(name, None) is not None

    def is_set(self, provider: str) -> bool:
        return self.get(provider) is not None

    def __repr__(self) -> str:
        return f"MemoryCredentialStore({len(self._keys)} keys)"


class UnavailableCredentialStore:
    """Where there is no Credential Manager: no key is ever found, and storing one fails."""

    def get(self, provider: str) -> Secret | None:
        target_name(provider)
        return None

    def set(self, provider: str, key: Secret | str) -> None:
        raise CredentialStoreError("API keys can be stored only in Windows Credential Manager, on Windows.")

    def clear(self, provider: str) -> bool:
        target_name(provider)
        return False

    def is_set(self, provider: str) -> bool:
        return False


# --------------------------------------------------------------------------- Credential Manager
class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class CREDENTIALW(ctypes.Structure):
    """``CREDENTIALW`` from wincred.h."""

    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


class _Advapi:
    """The four Credential Manager functions from advapi32, with their prototypes."""

    def __init__(self) -> None:
        dll = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
        BOOL, DWORD = ctypes.c_int, ctypes.c_uint32
        self.CredReadW = dll.CredReadW
        self.CredReadW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.POINTER(PCREDENTIALW)]
        self.CredReadW.restype = BOOL
        self.CredWriteW = dll.CredWriteW
        self.CredWriteW.argtypes = [PCREDENTIALW, DWORD]
        self.CredWriteW.restype = BOOL
        self.CredDeleteW = dll.CredDeleteW
        self.CredDeleteW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD]
        self.CredDeleteW.restype = BOOL
        self.CredFree = dll.CredFree
        self.CredFree.argtypes = [ctypes.c_void_p]
        self.CredFree.restype = None

    @staticmethod
    def get_last_error() -> int:
        return ctypes.get_last_error()  # type: ignore[attr-defined]


class WindowsCredentialStore:
    """Keys in Windows Credential Manager, through ``CredReadW``, ``CredWriteW`` and
    ``CredDeleteW``. ``api`` replaces the advapi32 functions, for tests."""

    def __init__(self, api: Any = None) -> None:
        self._api = api if api is not None else _Advapi()

    def get(self, provider: str) -> Secret | None:
        name = target_name(provider)
        pcred = PCREDENTIALW()
        if not self._api.CredReadW(name, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            error = self._api.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError(
                f"Windows Credential Manager could not read {name} (error {error}).", detail={"value": error}
            )
        try:
            cred = pcred.contents
            size = int(cred.CredentialBlobSize)
            if size == 0 or not cred.CredentialBlob:
                return None
            blob = ctypes.string_at(cred.CredentialBlob, size)
        finally:
            self._api.CredFree(pcred)
        try:
            return Secret(blob.decode("utf-16-le"))
        except (UnicodeDecodeError, InvalidSettingError):
            raise CredentialStoreError(
                f"The key stored as {name} is not a valid API key. Enter it again in settings."
            ) from None

    def set(self, provider: str, key: Secret | str) -> None:
        name, secret = target_name(provider), Secret(key)
        blob = secret.reveal().encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIALW()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = name
        cred.Comment = "API key for the SolidSeas AI connector"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "SolidSeas"
        try:
            ok = self._api.CredWriteW(ctypes.byref(cred), 0)
        finally:
            ctypes.memset(buffer, 0, len(blob))
        if not ok:
            error = self._api.get_last_error()
            raise CredentialStoreError(
                f"Windows Credential Manager could not store {name} (error {error}).", detail={"value": error}
            )

    def clear(self, provider: str) -> bool:
        name = target_name(provider)
        if self._api.CredDeleteW(name, CRED_TYPE_GENERIC, 0):
            return True
        error = self._api.get_last_error()
        if error == ERROR_NOT_FOUND:
            return False
        raise CredentialStoreError(
            f"Windows Credential Manager could not remove {name} (error {error}).", detail={"value": error}
        )

    def is_set(self, provider: str) -> bool:
        try:
            return self.get(provider) is not None
        except CredentialStoreError:
            return False


def default_store() -> CredentialStore:
    """Windows Credential Manager on Windows; elsewhere a store that holds nothing."""
    if sys.platform == "win32":
        return WindowsCredentialStore()
    return UnavailableCredentialStore()


__all__ = [
    "CREDENTIALW",
    "CredentialStore",
    "MemoryCredentialStore",
    "Secret",
    "TARGET_PREFIX",
    "UnavailableCredentialStore",
    "WindowsCredentialStore",
    "default_store",
    "target_name",
]
