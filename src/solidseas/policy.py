"""Machine policy: what an administrator allows SolidSeas to do on this PC.

An administrator restricts SolidSeas with values under
``HKLM\\SOFTWARE\\Policies\\SolidSeas`` (``docs/ASSISTANT.md``, "Machine policy"):

``DisableAutomaticMode`` (DWORD)
    1 makes Automatic mode unavailable.
``LocalProviderOnly`` (DWORD)
    1 restricts the AI connector to an Ollama server on this machine.
``AllowedProviderHosts`` (REG_MULTI_SZ)
    Host names that also count as local, for an approved internal Ollama server.
``DisableImages`` (DWORD)
    1 stops pictures of the part being sent to any provider, the person's choice
    to send one notwithstanding.
``DisableExtensions`` (DWORD)
    1 switches every extension off (``docs/EXTENSIONS.md``).
``AllowedExtensions`` (REG_MULTI_SZ)
    Extension ids that may be switched on; any other stays off. Not set: every
    extension may be. Of the wrong type, or unreadable: none may. An extension's
    former id (:data:`RENAMED_EXTENSIONS`) still names it, so a list written before
    a rename keeps its meaning.

The key is read fail-closed. ``FileNotFoundError`` is the only error that means
"absent": from opening the key it means no policy and no restriction, and from
reading a value it means that value is not set. Any other error opening the key,
access denied included, turns every restriction on. A value of the wrong
registry type, or a DWORD other than 0 or 1, turns that restriction on; an
``AllowedProviderHosts`` of the wrong type counts as empty. The reader never
checks whether the key exists before opening it.

:func:`current` reads the registry on every call, so a policy that Group
Policy pushes while the app is open applies to the next model call and the
next Automatic run. Enforcement lives in two places and nowhere else: the
provider factory (:mod:`solidseas.ai.factory`), behind which each provider
also applies ``LocalProviderOnly`` itself before every call, and
``solidseas_app.assistant.automatic.start_run``. Tests substitute the reader
with :func:`set_reader`; the real one is never pointed at a test registry.

On a platform without a registry (anything but Windows) there is no machine
policy, as when the key is absent: there is no place an administrator could
have set one.
"""

from __future__ import annotations

import ipaddress
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

KEY_PATH = r"SOFTWARE\Policies\SolidSeas"
KEY_DISPLAY = r"HKLM\SOFTWARE\Policies\SolidSeas"

DISABLE_AUTOMATIC = "DisableAutomaticMode"
LOCAL_ONLY = "LocalProviderOnly"
ALLOWED_HOSTS = "AllowedProviderHosts"
DISABLE_IMAGES = "DisableImages"
DISABLE_EXTENSIONS = "DisableExtensions"
ALLOWED_EXTENSIONS = "AllowedExtensions"
_EXTENSION_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")
# Extensions that were renamed: former id -> current id. "solidworks" became "cad-bridge"
# so that no SolidSeas name is made of another company's trademark.
RENAMED_EXTENSIONS = {"solidworks": "cad-bridge"}

REG_DWORD = 4
REG_MULTI_SZ = 7

MAX_ALLOWED_HOSTS = 32
_HOST_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\Z")


@dataclass(frozen=True)
class Policy:
    """One reading of the machine policy.

    ``locked`` is true when an administrator manages these settings: the key
    exists, or could not be read. The settings page then shows the affected
    controls disabled with "Set by your administrator". ``error`` says what was
    wrong with the key or a value when a restriction was turned on because of
    it; the settings page shows it with :data:`KEY_DISPLAY`.
    """

    automatic_disabled: bool = False
    local_only: bool = False
    allowed_hosts: tuple[str, ...] = ()
    images_disabled: bool = False
    extensions_disabled: bool = False
    allowed_extensions: tuple[str, ...] | None = None  # None: not restricted
    locked: bool = False
    error: str | None = None


NO_POLICY = Policy()


def restricted(error: str) -> Policy:
    """Every restriction on and no extra hosts: what a key that cannot be read means."""
    return Policy(
        automatic_disabled=True,
        local_only=True,
        allowed_hosts=(),
        images_disabled=True,
        extensions_disabled=True,
        allowed_extensions=(),
        locked=True,
        error=error,
    )


class Registry(Protocol):
    """What the reader needs from the registry, with ``winreg``'s semantics: each call
    raises ``FileNotFoundError`` when the key or value is absent and another ``OSError``
    when it cannot be read; :meth:`query` returns ``(value, registry type)``."""

    def open(self) -> Any: ...

    def query(self, key: Any, name: str) -> tuple[Any, int]: ...

    def close(self, key: Any) -> None: ...


class WindowsRegistry:
    """The policy key in the 64-bit registry view, whatever the build of Python."""

    def __init__(self) -> None:
        import winreg

        self._winreg = winreg

    def open(self) -> Any:
        w = self._winreg
        return w.OpenKey(w.HKEY_LOCAL_MACHINE, KEY_PATH, 0, w.KEY_READ | w.KEY_WOW64_64KEY)

    def query(self, key: Any, name: str) -> tuple[Any, int]:
        return self._winreg.QueryValueEx(key, name)

    def close(self, key: Any) -> None:
        self._winreg.CloseKey(key)


def _flag(registry: Registry, key: Any, name: str, problems: list[str]) -> bool:
    """One DWORD restriction: False when the value is not set or is 0, True when it is 1,
    and True, with the reason in ``problems``, for anything else."""
    try:
        value, kind = registry.query(key, name)
    except FileNotFoundError:
        return False
    except OSError as exc:
        problems.append(f"{name} could not be read ({_os_error(exc)}), so it is on")
        return True
    if kind != REG_DWORD:
        problems.append(f"{name} is not a DWORD, so it is on")
        return True
    if type(value) is not int or value not in (0, 1):
        problems.append(f"{name} is not 0 or 1, so it is on")
        return True
    return value == 1


def normalize_host(text: Any) -> str | None:
    """A host name or IP address in the form the policy compares, or None when ``text``
    is not one: lower case, no trailing dot, IPv6 without brackets."""
    if not isinstance(text, str):
        return None
    host = text.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.endswith("."):
        host = host[:-1]
    if not host or len(host) > 253:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if all(_HOST_LABEL.match(label) for label in host.split(".")):
        return host
    return None


def _hosts(registry: Registry, key: Any, problems: list[str]) -> tuple[str, ...]:
    try:
        value, kind = registry.query(key, ALLOWED_HOSTS)
    except FileNotFoundError:
        return ()
    except OSError as exc:
        problems.append(f"{ALLOWED_HOSTS} could not be read ({_os_error(exc)}), so no extra host is allowed")
        return ()
    if kind != REG_MULTI_SZ or not isinstance(value, (list, tuple)):
        problems.append(f"{ALLOWED_HOSTS} is not a REG_MULTI_SZ, so no extra host is allowed")
        return ()
    hosts: list[str] = []
    skipped = 0
    for item in value:
        host = normalize_host(item)
        if host is None:
            if isinstance(item, str) and item.strip():
                skipped += 1
            continue
        if host not in hosts:
            hosts.append(host)
    if skipped:
        problems.append(f"{ALLOWED_HOSTS} holds {skipped} entries that are not host names; they are ignored")
    if len(hosts) > MAX_ALLOWED_HOSTS:
        problems.append(f"{ALLOWED_HOSTS} holds more than {MAX_ALLOWED_HOSTS} hosts; only the first are used")
        hosts = hosts[:MAX_ALLOWED_HOSTS]
    return tuple(hosts)


def _extension_ids(registry: Registry, key: Any, problems: list[str]) -> tuple[str, ...] | None:
    """``AllowedExtensions``: None when it is not set (no restriction), the ids it
    lists (lower case, each once), or none at all when it cannot be read or is not a
    REG_MULTI_SZ, fail-closed."""
    try:
        value, kind = registry.query(key, ALLOWED_EXTENSIONS)
    except FileNotFoundError:
        return None
    except OSError as exc:
        problems.append(
            f"{ALLOWED_EXTENSIONS} could not be read ({_os_error(exc)}), so no extension may be on"
        )
        return ()
    if kind != REG_MULTI_SZ or not isinstance(value, (list, tuple)):
        problems.append(f"{ALLOWED_EXTENSIONS} is not a REG_MULTI_SZ, so no extension may be on")
        return ()
    ids: list[str] = []
    for item in value:
        text = item.strip().lower() if isinstance(item, str) else ""
        if _EXTENSION_ID.fullmatch(text) and text not in ids:
            ids.append(text)
        elif text and text not in ids:
            problems.append(f"{ALLOWED_EXTENSIONS} holds {text[:40]!r}, which is not an extension id")
    return tuple(ids[:64])


def extension_allowed(pol: Policy, extension_id: str) -> bool:
    """Whether ``pol`` lets the extension ``extension_id`` be on. A current id and a
    former one (:data:`RENAMED_EXTENSIONS`) name the same extension."""
    if pol.extensions_disabled:
        return False
    if pol.allowed_extensions is None:
        return True
    current = RENAMED_EXTENSIONS.get(extension_id, extension_id)
    names = {current} | {old for old, new in RENAMED_EXTENSIONS.items() if new == current}
    return any(n in pol.allowed_extensions for n in names)


def _os_error(exc: OSError) -> str:
    code = getattr(exc, "winerror", None) or exc.errno
    return f"{type(exc).__name__}, error {code}" if code else type(exc).__name__


def read_policy(registry: Registry | None = None) -> Policy:
    """Read the machine policy from ``registry`` (the real policy key by default),
    fail-closed as the module notes describe. It never raises."""
    try:
        if registry is None:
            if sys.platform != "win32":
                return NO_POLICY
            registry = WindowsRegistry()
        try:
            key = registry.open()
        except FileNotFoundError:
            return NO_POLICY
        except OSError as exc:
            return restricted(
                f"the policy key could not be read ({_os_error(exc)}), so every restriction is on"
            )
        try:
            problems: list[str] = []
            automatic_disabled = _flag(registry, key, DISABLE_AUTOMATIC, problems)
            local_only = _flag(registry, key, LOCAL_ONLY, problems)
            hosts = _hosts(registry, key, problems)
            images_disabled = _flag(registry, key, DISABLE_IMAGES, problems)
            extensions_disabled = _flag(registry, key, DISABLE_EXTENSIONS, problems)
            allowed_extensions = _extension_ids(registry, key, problems)
        finally:
            try:
                registry.close(key)
            except Exception:
                pass
        return Policy(
            automatic_disabled=automatic_disabled,
            local_only=local_only,
            allowed_hosts=hosts,
            images_disabled=images_disabled,
            extensions_disabled=extensions_disabled,
            allowed_extensions=allowed_extensions,
            locked=True,
            error="; ".join(problems) or None,
        )
    except Exception as exc:  # a reader that fails in any other way restricts everything
        return restricted(f"the policy could not be read ({type(exc).__name__}), so every restriction is on")


_lock = threading.Lock()
_reader: Callable[[], Policy] = read_policy


def set_reader(reader: Callable[[], Policy] | None) -> Callable[[], Policy]:
    """Replace the function :func:`current` calls (None restores the registry reader) and
    return the one it replaced. For tests."""
    global _reader
    with _lock:
        previous = _reader
        _reader = reader if reader is not None else read_policy
        return previous


def current() -> Policy:
    """The machine policy now, read fresh. A reader that raises, or returns something
    other than a :class:`Policy`, means every restriction is on."""
    with _lock:
        reader = _reader
    try:
        result = reader()
    except Exception as exc:
        return restricted(f"the policy could not be read ({type(exc).__name__}), so every restriction is on")
    if not isinstance(result, Policy):
        return restricted(
            "the policy reader returned something that is not a policy, so every restriction is on"
        )
    return result


__all__ = [
    "ALLOWED_HOSTS",
    "DISABLE_AUTOMATIC",
    "ALLOWED_EXTENSIONS",
    "DISABLE_EXTENSIONS",
    "DISABLE_IMAGES",
    "KEY_DISPLAY",
    "KEY_PATH",
    "LOCAL_ONLY",
    "NO_POLICY",
    "Policy",
    "RENAMED_EXTENSIONS",
    "Registry",
    "WindowsRegistry",
    "current",
    "extension_allowed",
    "normalize_host",
    "read_policy",
    "restricted",
    "set_reader",
]
