"""The AI settings file, ``AI.json``, and what the AI settings page and the assistant window
share. Importing this module imports no Qt.

``AI.json`` holds the fields of :class:`solidseas.ai.factory.AISettings`: the provider, the
model, the Ollama address, the budgets and the Automatic mode limits. It never holds an API
key: keys live in Windows Credential Manager (:mod:`solidseas.ai.credentials`). It sits beside
the viewer's ``Viewer.ini``, in the roaming SolidSeas folder (``%APPDATA%\\SolidSeas`` on
Windows), and is a file of its own rather than a section of ``Viewer.ini``: the viewer
rewrites ``Viewer.ini`` from its own copy whenever one of its settings changes, and an
assistant window in another SolidSeas process would then undo a change the other made.

The file follows the rules of ``Viewer.ini`` and the drawing settings:

* At most :data:`MAX_BYTES`, read as strict JSON: a repeated key, ``NaN``, ``Infinity``, a
  number too large to be finite or nesting deeper than :data:`MAX_DEPTH` makes the whole file
  invalid, and the defaults are used.
* Each value is checked on its own (by :class:`AISettings` itself): one that is not valid
  falls back to its default and the reason is listed in the problems :func:`load` returns. A
  member that is not an AI setting is ignored and listed.
* It is written through a temporary file beside it and a rename, never through a link: a
  link or a folder at its path is refused.
* :meth:`AISettingsStore.update` reads the file again and changes only the fields it is
  given, so two windows that each change something do not undo each other's change.

:data:`SUGGESTED_MODELS` is the one table of the model the settings page offers for each
provider. :class:`AIConfig` is where one app's AI settings, keys and usage live; the viewer,
the assistant window and the settings page share one, and it builds providers only through
:func:`solidseas.ai.factory.get_provider`.
"""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import Any

from solidseas.ai import credentials as _credentials
from solidseas.ai import factory
from solidseas.ai.errors import InvalidSettingError
from solidseas.ai.factory import AISettings
from solidseas.ai.usage import UsageLedger

FILE_NAME = "AI.json"
SCHEMA = "solidseas.ai-settings/1"
MAX_BYTES = 64 * 1024  # the file is under a kilobyte; a much larger one is not ours
MAX_DEPTH = 8
ADMIN = "Set by your administrator"

# The model the settings page fills in when a provider is chosen. These are defaults the
# person can change, not a choice SolidSeas makes for them: providers add and retire models,
# and each account sees its own list, so the page says to check it. Each passes
# AISettings' model check (check_model_name), which tests/test_assistant_settings.py checks.
SUGGESTED_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
    "ollama": "qwen2.5-coder:7b",
}
CLOUD = ("anthropic", "openai", "gemini")  # the providers that need an API key

# Read in this order; the two prices are set together, because a price alone is not valid.
_PAIRS = (("price_input_per_mtok", "price_output_per_mtok"),)


class AISettingsFileError(Exception):
    """``AI.json`` could not be written; the message is for the person."""


def path_beside(viewer_ini: str) -> str:
    """``AI.json`` in the folder of the viewer's settings file ``viewer_ini``."""
    return os.path.join(os.path.dirname(os.path.abspath(viewer_ini)), FILE_NAME)


# --------------------------------------------------------------------------- reading
def _strict(raw: bytes) -> Any:
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"the key {k!r} appears twice")
            out[k] = v
        return out

    def constant(name):
        raise ValueError(f"{name} is not a number AI.json accepts")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    _depth(value, 0)
    return value


def _depth(value: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValueError(f"it is nested more than {MAX_DEPTH} levels deep")
    if isinstance(value, dict):
        for v in value.values():
            _depth(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _depth(v, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("it holds a number too large to be finite")


def from_dict(data: Any) -> tuple[AISettings, list[str]]:
    """Settings from the file's JSON object and the problems found: each value checked on its
    own, a bad one replaced by its default."""
    if not isinstance(data, dict):
        return AISettings(), ["AI.json is not an object; the defaults are used"]
    problems: list[str] = []
    schema = data.get("schema")
    if schema != SCHEMA:
        prefix = SCHEMA.rsplit("/", 1)[0] + "/"
        major = schema[len(prefix) :] if isinstance(schema, str) and schema.startswith(prefix) else ""
        if not (major.isdigit() and int(major) > 1):
            return AISettings(), [f"AI.json is not SolidSeas AI settings ({schema!r}); the defaults are used"]
        problems.append(f"AI.json was written by a newer SolidSeas ({schema}); what this one knows is read")
    known = [f.name for f in fields(AISettings)]
    for name in data:
        if name != "schema" and name not in known:
            problems.append(f"{str(name)[:40]!r} is not an AI setting; it is ignored")
    paired = {name for pair in _PAIRS for name in pair}
    groups: list[tuple[str, ...]] = [(n,) for n in known if n not in paired] + list(_PAIRS)
    settings = AISettings()
    for group in groups:
        values = {n: data[n] for n in group if n in data}
        if not values:
            continue
        if isinstance(values.get("protected_properties"), list):
            values["protected_properties"] = tuple(values["protected_properties"])
        try:
            settings = replace(settings, **values)
        except (InvalidSettingError, TypeError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, InvalidSettingError) else "it is not a valid value"
            problems.append(f"{' and '.join(group)}: {reason}; the default is used")
    return settings, problems


def parse(raw: bytes) -> tuple[AISettings, list[str]]:
    """The settings in the bytes of an ``AI.json`` and the problems found."""
    if len(raw) > MAX_BYTES:
        return AISettings(), [f"AI.json is larger than {MAX_BYTES // 1024} KiB; the defaults are used"]
    try:
        data = _strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return AISettings(), [f"AI.json is not valid ({exc}); the defaults are used"]
    return from_dict(data)


def load(path: str) -> tuple[AISettings, list[str]]:
    """The settings in ``path`` and the problems found. A missing file gives the defaults with
    no problem. Never raises and never writes."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return AISettings(), []
    except OSError as exc:
        return AISettings(), [f"AI.json could not be read ({exc.strerror or type(exc).__name__})"]
    return parse(raw)


# --------------------------------------------------------------------------- writing
def dumps(settings: AISettings) -> bytes:
    """The file's bytes: ASCII JSON, two-space indented, a newline at the end."""
    if not isinstance(settings, AISettings):
        raise InvalidSettingError("AI.json holds AISettings.")
    data = {"schema": SCHEMA, **settings.to_dict()}
    return (json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("ascii")


def _is_link(path: str) -> bool:
    """A symbolic link, a junction or another name-surrogate reparse point at ``path``."""
    from solidseas.walk import reparse_link

    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    tag = int(getattr(st, "st_reparse_tag", 0) or 0)
    return stat.S_ISLNK(st.st_mode) or reparse_link(attrs, tag) is not None


def save(settings: AISettings, path: str) -> None:
    """Write ``settings`` to ``path`` through a temporary file beside it and a rename. Raises
    :class:`AISettingsFileError` when it cannot, or when ``path`` is a link or a folder."""
    data = dumps(settings)
    target = os.path.abspath(path)
    if _is_link(target):
        raise AISettingsFileError(f"{target} is a link; SolidSeas does not write through it.")
    if os.path.isdir(target):
        raise AISettingsFileError(f"{target} is a folder.")
    folder = os.path.dirname(target)
    tmp = None
    try:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="AI.", suffix=".tmp", dir=folder)  # O_EXCL, never a link
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(20):  # a reader or a virus scanner can hold the file a moment
            try:
                os.replace(tmp, target)
                tmp = None
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.02)
    except OSError as exc:
        raise AISettingsFileError(
            f"The AI settings could not be saved in {target} ({exc.strerror or type(exc).__name__})."
        ) from None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


class AISettingsStore:
    """``AI.json`` at ``path``, or settings kept in memory when ``path`` is None (tests, and a
    viewer whose own settings are in memory)."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.problems: list[str] = []
        self._memory = AISettings()

    def load(self) -> AISettings:
        """The settings now. ``problems`` lists what was wrong with the file."""
        if self.path is None:
            self.problems = []
            return self._memory
        settings, self.problems = load(self.path)
        return settings

    def update(self, **changes: Any) -> AISettings:
        """Read the settings again, change only ``changes`` and save; returns the result.
        Raises :class:`InvalidSettingError` for a value that is not valid (nothing is
        written) and :class:`AISettingsFileError` when the file cannot be written."""
        current = self.load()
        try:
            new = replace(current, **changes)
        except TypeError:
            raise InvalidSettingError("That is not an AI setting.") from None
        if self.path is None:
            self._memory = new
        else:
            save(new, self.path)
        return new


# --------------------------------------------------------------------------- one app's AI
@dataclass
class AIConfig:
    """Where one app's AI settings, keys and usage live.

    ``credentials`` None means :func:`solidseas.ai.credentials.default_store`, looked up each
    time (Windows Credential Manager on Windows). ``ledger`` None means the factory's own
    usage file. ``build`` replaces :func:`solidseas.ai.factory.get_provider` in tests, so the
    settings page can be tried against the scripted provider; the app never sets it."""

    settings: AISettingsStore
    credentials: Any = None
    ledger: UsageLedger | None = None
    build: Callable[..., Any] | None = None

    def key_store(self) -> Any:
        return self.credentials if self.credentials is not None else _credentials.default_store()

    def provider(self, settings: AISettings | None = None, *, credentials: Any = None) -> Any:
        """The provider ``settings`` (the saved ones by default) name, from the factory: a
        NoopProvider with the reason when it cannot be used."""
        if settings is None:
            settings = self.settings.load()
        build = self.build if self.build is not None else factory.get_provider
        return build(
            settings,
            credentials=credentials if credentials is not None else self.credentials,
            ledger=self.ledger,
        )

    def usage_ledger(self, settings: AISettings) -> UsageLedger:
        """The usage file, for this month's use."""
        return self.ledger if self.ledger is not None else UsageLedger(budget=settings.budget())


__all__ = [
    "ADMIN",
    "CLOUD",
    "FILE_NAME",
    "MAX_BYTES",
    "SCHEMA",
    "SUGGESTED_MODELS",
    "AIConfig",
    "AISettingsFileError",
    "AISettingsStore",
    "dumps",
    "from_dict",
    "load",
    "parse",
    "path_beside",
    "save",
]
