"""``SolidSeasViewer.exe --set-policy``: write the machine policy as an administrator, and
exit (from source, ``python -m solidseas_app --set-policy``).

The machine policy is the registry key ``HKLM\\SOFTWARE\\Policies\\SolidSeas`` with which an
administrator restricts SolidSeas on a PC (``docs/ASSISTANT.md``, "Machine policy");
:mod:`solidseas.policy` reads it, fail-closed. Group Policy or Intune is the usual way to
deploy it. This is the way to set it on one PC from SolidSeas itself, and the only code in
SolidSeas that writes the key::

    --set-policy NAME=VALUE ... [--remove NAME] ...
    --set-policy --remove-all

* **A process of its own.** It runs elevated for this one step, from a prompt started with
  Run as administrator or through the ``runas`` verb, so the program that reads part files
  never runs elevated: this path imports no Qt, opens no document and reads no settings file.
* **Elevation is asked, never tried.** ``IsUserAnAdmin`` must say this process is elevated;
  a check that cannot say counts as no. Off Windows there is no key to write.
* **Every argument is checked before anything is written.** Only the six policy values, a
  DWORD as 0 or 1, and hosts and extension ids as the reader takes them, no more of either
  than it uses. A mistake anywhere writes nothing. Values not named stay as they are.
* **Who and when.** Each change also writes ``SetBy`` (the account, ``DOMAIN\\name``) and
  ``SetAt`` (UTC), for the next administrator who looks at the key.
* **Restrictions first.** What only adds a restriction (DWORDs set to 1, and
  ``AllowedProviderHosts`` removed) is written before anything else, and DWORDs set to 0
  and the other removals last, so a write that stops part way has not turned a
  restriction off before turning the others on.
* **Read back.** The policy is then read with the reader SolidSeas uses, and must say what
  was asked, with no problem in any value; otherwise the run has failed, and its output
  says how the policy reads now.

Exit codes: 0 written and read back as asked; 1 not written, or not read back as asked;
2 a usage error, nothing written; 3 refused, nothing written: not an administrator, or no
registry on this system. The packaged executable has no console of its own, so its output
shows only when it is piped (``| more``), and a prompt does not wait for it: its exit code is
read by waiting for the process (``Start-Process ... -Wait -PassThru``), not from
``%ERRORLEVEL%`` after a pipe, which is the pipe's.
"""

from __future__ import annotations

import datetime
import getpass
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TextIO

from solidseas import policy
from solidseas.policy import (
    ALLOWED_EXTENSIONS,
    ALLOWED_HOSTS,
    DISABLE_AUTOMATIC,
    DISABLE_EXTENSIONS,
    DISABLE_IMAGES,
    KEY_DISPLAY,
    KEY_PATH,
    LOCAL_ONLY,
    MAX_ALLOWED_EXTENSIONS,
    MAX_ALLOWED_HOSTS,
    NO_POLICY,
    REG_DWORD,
    REG_MULTI_SZ,
    Policy,
)

FLAG = "--set-policy"
REMOVE = "--remove"
REMOVE_ALL = "--remove-all"
SET_BY = "SetBy"
SET_AT = "SetAt"
REG_SZ = 1
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3
MAX_ACCOUNT = 256

NAMES = (DISABLE_AUTOMATIC, LOCAL_ONLY, ALLOWED_HOSTS, DISABLE_IMAGES, DISABLE_EXTENSIONS, ALLOWED_EXTENSIONS)
DWORDS = (DISABLE_AUTOMATIC, LOCAL_ONLY, DISABLE_IMAGES, DISABLE_EXTENSIONS)
FIELDS = {  # each value: the field of :class:`solidseas.policy.Policy` it is read into
    DISABLE_AUTOMATIC: "automatic_disabled",
    LOCAL_ONLY: "local_only",
    ALLOWED_HOSTS: "allowed_hosts",
    DISABLE_IMAGES: "images_disabled",
    DISABLE_EXTENSIONS: "extensions_disabled",
    ALLOWED_EXTENSIONS: "allowed_extensions",
}

USAGE = f"""usage: SolidSeasViewer.exe {FLAG} NAME=VALUE ... [{REMOVE} NAME] ...
       SolidSeasViewer.exe {FLAG} {REMOVE_ALL}

Writes the machine policy at {KEY_DISPLAY}. Run it as administrator.
Values not named stay as they are.

  DisableAutomaticMode=0|1       1 makes Automatic mode unavailable
  LocalProviderOnly=0|1          1 lets the AI use only an Ollama server on this PC
  AllowedProviderHosts=HOST,...  hosts that also count as local, at most {MAX_ALLOWED_HOSTS}
  DisableImages=0|1              1 stops pictures of a part going to any model
  DisableExtensions=0|1          1 switches every extension off
  AllowedExtensions=ID,...       the only extensions that may be on, at most {MAX_ALLOWED_EXTENSIONS}
  {REMOVE} NAME                  removes that value, which is then not set
  {REMOVE_ALL}                   removes the key: SolidSeas is not restricted

Exit codes: 0 written and read back as asked, 1 failed, 2 a usage error, 3 refused
(not an administrator, or no registry). Nothing is written after a usage error or a
refusal."""

NOT_ADMIN = (
    "Writing the machine policy needs an administrator: run it from a prompt started with "
    "Run as administrator. Nothing was written."
)
NO_REGISTRY = (
    f"The machine policy is the Windows registry key {KEY_DISPLAY}, and this system has no "
    "registry. Nothing was written."
)


class UsageError(ValueError):
    """Arguments ``--set-policy`` does not take: nothing is written."""


@dataclass(frozen=True)
class Change:
    """What one run asks for: values to write as ``{name: (registry type, value)}``, values
    to remove, or the whole key removed."""

    values: dict[str, tuple[int, Any]] = field(default_factory=dict)
    remove: tuple[str, ...] = ()
    remove_all: bool = False

    def steps(self) -> list[tuple[str, int | None, Any]]:
        """The writes in the order they are made, ``(name, registry type, value)``, with a
        type of None for a value to remove: what only adds a restriction first (DWORDs set
        to 1, and ``AllowedProviderHosts`` removed, which leaves no extra host allowed), then
        the lists, then DWORDs set to 0, then the other removals, each group in the policy's
        own order."""

        def ordered(items: list[tuple[str, int | None, Any]]) -> list[tuple[str, int | None, Any]]:
            return sorted(items, key=lambda item: NAMES.index(item[0]))

        writes = [(name, kind, value) for name, (kind, value) in self.values.items()]
        on = [w for w in writes if w[1] == REG_DWORD and w[2] == 1]
        lists = [w for w in writes if w[1] == REG_MULTI_SZ]
        off = [w for w in writes if w[1] == REG_DWORD and w[2] == 0]
        removals: list[tuple[str, int | None, Any]] = [(name, None, None) for name in self.remove]
        narrowing = [r for r in removals if r[0] == ALLOWED_HOSTS]
        removals = [r for r in removals if r[0] != ALLOWED_HOSTS]
        return ordered(on + narrowing) + ordered(lists) + ordered(off) + ordered(removals)


# --------------------------------------------------------------------------- the arguments
def value_name(text: str) -> str:
    """The policy value ``text`` names, in the policy's spelling (registry names ignore case)."""
    wanted = text.strip().lower()
    for name in NAMES:
        if name.lower() == wanted:
            return name
    if wanted in (SET_BY.lower(), SET_AT.lower()):
        raise UsageError(f"{SET_BY} and {SET_AT} are written by {FLAG} itself")
    raise UsageError(f"{text[:40]!r} is not a policy value: the values are {', '.join(NAMES)}")


def checked_value(name: str, raw: str) -> tuple[int, Any]:
    """``raw`` as the registry type and value ``name`` takes, checked as the reader checks it:
    a DWORD is 0 or 1; a list holds host names or IP addresses (``AllowedProviderHosts``) or
    extension ids (``AllowedExtensions``), separated by commas, each once, in the form the
    reader compares, and no more of them than it uses."""
    text = raw.strip()
    if name in DWORDS:
        if text not in ("0", "1"):
            raise UsageError(f"{name} is 0 or 1")
        return REG_DWORD, int(text)
    if not text:
        raise UsageError(f"{name} needs at least one entry; {REMOVE} {name} removes it")
    hosts = name == ALLOWED_HOSTS
    normal = policy.normalize_host if hosts else policy.normalize_extension_id
    most = MAX_ALLOWED_HOSTS if hosts else MAX_ALLOWED_EXTENSIONS
    what = "a host name or an IP address" if hosts else "an extension id"
    kept: list[str] = []
    for entry in (e.strip() for e in text.split(",")):
        if not entry:
            raise UsageError(f"{name} has an empty entry")
        found = normal(entry)
        if found is None:
            raise UsageError(f"{name}: {entry[:40]!r} is not {what}")
        if found not in kept:
            kept.append(found)
    if len(kept) > most:
        raise UsageError(f"{name} holds at most {most} entries")
    return REG_MULTI_SZ, kept


def parse(args: Sequence[str]) -> Change:
    """The change ``args`` ask for; raises :class:`UsageError` for anything else."""
    values: dict[str, tuple[int, Any]] = {}
    remove: list[str] = []
    remove_all = False
    named: set[str] = set()

    def once(name: str) -> str:
        if name in named:
            raise UsageError(f"{name} is named more than once")
        named.add(name)
        return name

    items = list(args)
    at = 0
    while at < len(items):
        arg = items[at]
        if arg == REMOVE_ALL:
            remove_all = True
        elif arg == REMOVE:
            if at + 1 == len(items):
                raise UsageError(f"{REMOVE} takes the name of a value")
            at += 1
            remove.append(once(value_name(items[at])))
        elif arg.startswith("-"):
            raise UsageError(f"there is no option {arg[:40]!r}")
        else:
            text, equals, raw = arg.partition("=")
            if not equals:
                raise UsageError(f"{arg[:40]!r} is not NAME=VALUE")
            name = once(value_name(text))
            values[name] = checked_value(name, raw)
        at += 1
    if remove_all and (values or remove):
        raise UsageError(f"{REMOVE_ALL} removes the whole key, so it goes alone")
    if not (values or remove or remove_all):
        raise UsageError(f"give NAME=VALUE, {REMOVE} NAME or {REMOVE_ALL}")
    return Change(values, tuple(remove), remove_all)


# --------------------------------------------------------------------------- the machine
class PolicyKey(Protocol):
    """What the writer needs from the registry, with ``winreg``'s semantics: a call raises
    ``FileNotFoundError`` when the value or key is absent and another ``OSError`` when it
    cannot be changed."""

    def create(self) -> Any: ...

    def set(self, key: Any, name: str, kind: int, value: Any) -> None: ...

    def remove(self, key: Any, name: str) -> None: ...

    def close(self, key: Any) -> None: ...

    def delete(self) -> None: ...


class WindowsPolicyKey:
    """The policy key in the 64-bit registry view, the one :class:`solidseas.policy.WindowsRegistry`
    reads, whatever the build of Python."""

    def __init__(self) -> None:
        import winreg

        self._winreg = winreg

    def create(self) -> Any:
        """Open the key to change its values, making it when it is not there."""
        w = self._winreg
        access = w.KEY_SET_VALUE | w.KEY_QUERY_VALUE | w.KEY_WOW64_64KEY
        return w.CreateKeyEx(w.HKEY_LOCAL_MACHINE, KEY_PATH, 0, access)

    def set(self, key: Any, name: str, kind: int, value: Any) -> None:
        self._winreg.SetValueEx(key, name, 0, kind, value)

    def remove(self, key: Any, name: str) -> None:
        self._winreg.DeleteValue(key, name)

    def close(self, key: Any) -> None:
        self._winreg.CloseKey(key)

    def delete(self) -> None:
        w = self._winreg
        w.DeleteKeyEx(w.HKEY_LOCAL_MACHINE, KEY_PATH, w.KEY_WOW64_64KEY, 0)


def is_admin() -> bool:
    """Whether this process runs elevated, as Windows says; False when it cannot say."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def account_name() -> str:
    """The account this process runs as, ``DOMAIN\\name`` where Windows can say, for ``SetBy``."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            size = wintypes.ULONG(MAX_ACCOUNT)
            buffer = ctypes.create_unicode_buffer(MAX_ACCOUNT)
            name_sam_compatible = 2
            get_user_name = ctypes.windll.secur32.GetUserNameExW  # type: ignore[attr-defined]
            get_user_name.argtypes = [ctypes.c_int, wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG)]
            get_user_name.restype = wintypes.BOOLEAN
            if get_user_name(name_sam_compatible, buffer, ctypes.byref(size)):
                return buffer.value
        except Exception:
            pass
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class Machine:
    """What a run reaches on the PC: :meth:`this_pc` is the real one, and tests give stand-ins.
    ``read`` is the registry reader itself, never :func:`solidseas.policy.current`, which
    tests replace."""

    windows: bool
    is_admin: Callable[[], bool]
    key: Callable[[], PolicyKey]
    read: Callable[[], Policy]
    account: Callable[[], str]
    now: Callable[[], datetime.datetime]

    @classmethod
    def this_pc(cls) -> Machine:
        return cls(
            windows=sys.platform == "win32",
            is_admin=is_admin,
            key=WindowsPolicyKey,
            read=policy.read_policy,
            account=account_name,
            now=lambda: datetime.datetime.now(datetime.UTC),
        )


# --------------------------------------------------------------------------- reading it back
def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if value is None:
        return "not set"
    return ", ".join(value) or "none"


def mismatches(change: Change, pol: Policy) -> list[str]:
    """How ``pol``, read after ``change`` was written, differs from what it asked: empty when
    it reads as asked, with no problem in any value."""
    if change.remove_all:
        if pol == NO_POLICY:
            return []
        return ["the key is still there" + (f" and {pol.error}" if pol.error else "")]
    found = []
    if pol.error:
        found.append(f"there is a problem in it: {pol.error}")
    elif not pol.locked:
        found.append("the key is not there")
    for name, (kind, value) in change.values.items():
        want = bool(value) if kind == REG_DWORD else tuple(value)
        got = getattr(pol, FIELDS[name])
        if got != want:
            found.append(f"{name} reads as {_shown(got)}, not {_shown(want)}")
    for name in change.remove:
        want = getattr(NO_POLICY, FIELDS[name])
        got = getattr(pol, FIELDS[name])
        if got != want:
            found.append(f"{name} reads as {_shown(got)}, not as a value that is not set")
    return found


def describe(pol: Policy) -> list[str]:
    """The policy as SolidSeas reads it, one value a line."""
    if pol == NO_POLICY:
        return [f"There is no machine policy at {KEY_DISPLAY}: SolidSeas is not restricted on this PC."]

    def flag(name: str, on: bool, meaning: str) -> str:
        return f"  {name} = {int(on)}" + (f"  ({meaning})" if on else "")

    if pol.allowed_extensions is None:
        extensions = "not set  (any extension may be on)"
    elif not pol.allowed_extensions:
        extensions = "none  (no extension may be on)"
    else:
        extensions = ", ".join(pol.allowed_extensions)
    lines = [
        f"The machine policy at {KEY_DISPLAY}, as SolidSeas reads it now:",
        flag(DISABLE_AUTOMATIC, pol.automatic_disabled, "Automatic mode is off"),
        flag(LOCAL_ONLY, pol.local_only, "the AI may use only an Ollama server here or on an allowed host"),
        f"  {ALLOWED_HOSTS} = " + (", ".join(pol.allowed_hosts) or "none"),
        flag(DISABLE_IMAGES, pol.images_disabled, "no picture of a part goes to a model"),
        flag(DISABLE_EXTENSIONS, pol.extensions_disabled, "every extension is off"),
        f"  {ALLOWED_EXTENSIONS} = {extensions}",
    ]
    if pol.error:
        lines.append(f"  Problem: {pol.error}")
    return lines


def _reason(exc: BaseException) -> str:
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    return f"{type(exc).__name__}, error {code}" if code else type(exc).__name__


def _read(machine: Machine) -> Policy:
    """The policy read again; a reader that fails means every restriction is on, as for
    :func:`solidseas.policy.current`."""
    try:
        found = machine.read()
    except Exception as exc:
        return policy.restricted(f"the policy could not be read ({_reason(exc)}), so every restriction is on")
    if not isinstance(found, Policy):
        return policy.restricted("the policy reader returned something that is not a policy")
    return found


# --------------------------------------------------------------------------- writing it
def _write(change: Change, machine: Machine, say: Callable[[str], None]) -> int:
    try:
        who = str(machine.account())[:MAX_ACCOUNT] or "unknown"
    except Exception:
        who = "unknown"
    when = machine.now().astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        store = machine.key()
        key = store.create()
    except Exception as exc:
        say(f"The machine policy at {KEY_DISPLAY} could not be opened to write ({_reason(exc)}).")
        say("Nothing was written.")
        return EXIT_FAILED
    done: list[str] = []
    failed: tuple[str, BaseException] | None = None
    steps = [*change.steps(), (SET_BY, REG_SZ, who), (SET_AT, REG_SZ, when)]
    try:
        for name, kind, value in steps:
            try:
                if kind is None:
                    try:
                        store.remove(key, name)
                    except FileNotFoundError:
                        pass  # not set already
                else:
                    store.set(key, name, kind, value)
            except Exception as exc:
                failed = (name, exc)
                break
            done.append(name)
    finally:
        try:
            store.close(key)
        except Exception:
            pass  # the values are written or not already; closing changes neither
    now = _read(machine)
    if failed is not None:
        name, exc = failed
        written = ", ".join(done) if done else "nothing"
        say(f"{name} could not be written ({_reason(exc)}). Written before it: {written}.")
        for line in describe(now):
            say(line)
        return EXIT_FAILED
    for line in describe(now):
        say(line)
    say(f"{SET_BY} = {who}, {SET_AT} = {when}.")
    problems = mismatches(change, now)
    if problems:
        say("SolidSeas does not read the policy as it was written: " + "; ".join(problems) + ".")
        return EXIT_FAILED
    return EXIT_OK


def _remove_all(machine: Machine, say: Callable[[str], None]) -> int:
    try:
        machine.key().delete()
    except FileNotFoundError:
        pass  # there was no policy
    except Exception as exc:
        say(f"The machine policy at {KEY_DISPLAY} could not be removed ({_reason(exc)}).")
        for line in describe(_read(machine)):
            say(line)
        return EXIT_FAILED
    now = _read(machine)
    for line in describe(now):
        say(line)
    problems = mismatches(Change(remove_all=True), now)
    if problems:
        say("SolidSeas still reads a machine policy: " + "; ".join(problems) + ".")
        return EXIT_FAILED
    return EXIT_OK


def main(argv: Sequence[str], *, machine: Machine | None = None, out: TextIO | None = None) -> int:
    """``--set-policy`` with ``argv``, the arguments after the flag (see the module notes);
    its exit code."""
    stream = out if out is not None else sys.stdout

    def say(text: str) -> None:
        if stream is None:  # the packaged viewer has no console unless its output is piped
            return
        try:
            print(text, file=stream, flush=True)
        except OSError:
            pass  # a pipe closed early; the exit code still says how it went

    args = list(argv)
    if args[:1] == [FLAG]:
        args = args[1:]
    if args in (["-h"], ["--help"]):
        say(USAGE)
        return EXIT_OK
    try:
        change = parse(args)
    except UsageError as exc:
        say(f"{FLAG}: {exc}.\n")
        say(USAGE)
        return EXIT_USAGE
    machine = machine or Machine.this_pc()
    if not machine.windows:
        say(NO_REGISTRY)
        return EXIT_REFUSED
    try:
        elevated = machine.is_admin() is True
    except Exception:
        elevated = False  # a check that cannot say is a no
    if not elevated:
        say(NOT_ADMIN)
        return EXIT_REFUSED
    if change.remove_all:
        return _remove_all(machine, say)
    return _write(change, machine, say)


__all__ = [
    "EXIT_FAILED",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_USAGE",
    "FLAG",
    "NAMES",
    "Change",
    "Machine",
    "PolicyKey",
    "UsageError",
    "WindowsPolicyKey",
    "account_name",
    "checked_value",
    "describe",
    "is_admin",
    "main",
    "mismatches",
    "parse",
]
