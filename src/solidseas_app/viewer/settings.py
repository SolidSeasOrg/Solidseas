"""The viewer's settings: what they are, their defaults, and where they are kept.

Settings live in one INI file, ``SolidSeas\\Viewer.ini`` in the roaming
application-data folder (``%APPDATA%`` on Windows), never next to a document
or in a folder the viewer reads. The window reads the file once when it starts
and writes it whenever a setting changes or, when the last folder and layout
are remembered, when it closes.

The file is read and written here, in Python, never by ``QSettings``: QSettings
decodes a value written ``@Variant(...)`` with ``QDataStream``, and a forged
list length in one made Qt reserve tens of gigabytes, or abort the process,
before any check could run. Here every value is text. The two binary values,
the window's geometry and splitter state, are stored as base64 and kept to a
few kilobytes, and a value starting with ``@`` (how QSettings marks its own
types) is not valid.

Every value read back is checked against its setting: a wrong type, an unknown
choice, a number out of range or a damaged file gives that setting's default,
so a hand-edited file never stops the viewer. A store made with no path keeps
its settings in memory and never writes anything; tests use one, and the
self-test uses a file of its own so it never changes yours.
"""

import base64
import binascii
import json
import os
import re
import tempfile
from dataclasses import dataclass, fields, replace
from typing import Any

from PySide6.QtCore import QStandardPaths

from .filetypes import format_keys, parse_keys
from .mesh3d import DEFAULT_TRIANGLE_CAP, MAX_TRIANGLE_CAP, MIN_TRIANGLE_CAP
from .viewmath import FREE, MOUSE_STYLES, ROTATION_MODES, STANDARD

FILE_NAME = os.path.join("SolidSeas", "Viewer.ini")
MAX_FILE_BYTES = 64 * 1024  # the file is under a kilobyte; a much larger one is not ours
MAX_STATE_BYTES = 4096  # the geometry and splitter states are under a hundred bytes
MAX_RECENT = 20  # the most recent folders remembered
THUMBNAIL_SIZES = {  # name: (width, height) in pixels
    "small": (96, 72),
    "medium": (128, 96),
    "large": (192, 144),
    "extra_large": (256, 192),
}
THUMBNAIL_LABELS = {
    "small": "Small (96 x 72)",
    "medium": "Medium (128 x 96)",
    "large": "Large (192 x 144)",
    "extra_large": "Extra large (256 x 192)",
}
LIST_VIEWS = {"details": "Details", "icons": "Icons"}
DRAWING_MODE_LABELS = {"ask": "Ask each time", "express": "Express", "expert": "Expert"}
_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")
_GROUPED = re.compile(r"\d{1,3}(,\d{3})+")  # "1,000,000"
_HEADER = "; SolidSeas Viewer settings. A value that is not valid goes back to its default.\n"


@dataclass(frozen=True)
class Settings:
    """The user's choices. ``Settings()`` is every default."""

    view_3d: bool = False
    draw_boxes: bool = True  # a box where an assembly's instance has no mesh drawn
    mouse_style: str = STANDARD
    invert_wheel: bool = False
    rotation_mode: str = FREE
    view_cube: bool = True  # the 3D view's view cube, over its top-right corner
    turn_about_pointer: bool = True  # a turn drag turns about the surface under the pointer
    triangle_cap: int = DEFAULT_TRIANGLE_CAP
    thumbnail_size: str = "medium"
    list_view: str = "details"
    show_lock_files: bool = False
    remember_session: bool = True
    print_next_to_model: bool = True  # 3D Print saves its file in the model's folder, else in Temp
    show_all_formats: bool = True  # list every 3D file SolidSeas knows, not only SOLIDWORKS documents
    show_unreadable: bool = False  # list the files of formats SolidSeas recognises but cannot read
    # 3D Print hands the program the 3MF or STL file itself when it is sent that format. Off by default:
    # the program then has the user's own file open and may save over it (AGENTS.md, safety rules).
    print_as_is: bool = False
    # Each folder's index (its listing) is kept and shown again at once when it is next
    # opened (:mod:`.savedindex`); it is read again when older than ``reindex_after_hours``
    # (0: only by hand, Reload).
    keep_index: bool = True
    reindex_after_hours: int = 24
    recent_count: int = 10  # folders remembered under File > Recent Folders (0: none)
    # Drawings (File > New Drawing, Open Drawing, Make Drawing): experimental, on unless the
    # user switched them off; a file saved before this setting existed has them on.
    drawings: bool = True
    # What the Drawing button starts: "ask" shows the choice of Express or Expert each time;
    # "express" or "expert" starts that one, chosen with "Remember my choice" or here
    drawing_mode: str = "ask"

    def but(self, **changes: Any) -> "Settings":
        return replace(self, **changes)

    @property
    def thumbnail_pixels(self) -> tuple[int, int]:
        return THUMBNAIL_SIZES[self.thumbnail_size]


_CHOICES: dict[str, tuple[str, ...]] = {
    "mouse_style": tuple(MOUSE_STYLES),
    "rotation_mode": tuple(ROTATION_MODES),
    "thumbnail_size": tuple(THUMBNAIL_SIZES),
    "list_view": tuple(LIST_VIEWS),
    "drawing_mode": ("ask", "express", "expert"),
}
_RANGES: dict[str, tuple[int, int]] = {
    "triangle_cap": (MIN_TRIANGLE_CAP, MAX_TRIANGLE_CAP),
    "reindex_after_hours": (0, 24 * 365),
    "recent_count": (0, MAX_RECENT),
}
REINDEX_CHOICES = {
    0: "Never (Reload re-indexes)",
    1: "1 hour",
    4: "4 hours",
    12: "12 hours",
    24: "1 day",
    168: "7 days",
}


@dataclass
class Session:
    """What is remembered between runs when ``remember_session`` is on."""

    folder: str | None = None
    geometry: bytes | None = None
    splitter: bytes | None = None
    quick_filter: tuple[str, ...] = ()  # the list's quick filter types on (.filetypes keys)
    recent: tuple[str, ...] = ()  # the folders opened last, newest first (File > Recent Folders)


def _bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return None


def _int(raw: Any) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return None
    if isinstance(raw, int):
        return raw
    text = raw.strip().replace("_", "")
    if _GROUPED.fullmatch(text):  # "1,000,000" typed into the file
        text = text.replace(",", "")
    if text[:1] in "+-":
        sign, text = text[0], text[1:]
    else:
        sign = ""
    if text.isascii() and text.isdigit() and len(text) <= 12:
        return int(sign + text)
    return None


def parse(name: str, raw: Any) -> Any:
    """``raw``, as read from the file, as a value of setting ``name``, or None when
    it is not a valid one."""
    default = getattr(Settings(), name)
    if isinstance(default, bool):
        return _bool(raw)
    if isinstance(default, int):
        value = _int(raw)
        lo, hi = _RANGES[name]
        return value if value is not None and lo <= value <= hi else None
    if isinstance(raw, str) and raw.strip().lower() in _CHOICES[name]:
        return raw.strip().lower()
    return None


def coerce(name: str, raw: Any) -> Any:
    """``raw`` as the value of setting ``name``; the setting's default when it is
    missing (None) or not valid."""
    value = parse(name, raw) if raw is not None else None
    return getattr(Settings(), name) if value is None else value


def default_path() -> str:
    """``SolidSeas\\Viewer.ini`` in the roaming application-data folder."""
    base = os.environ.get("APPDATA") if os.name == "nt" else None
    if not base or not os.path.isabs(base):
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    return os.path.join(base, FILE_NAME)


# --------------------------------------------------------------------------- the file
Sections = dict[str, dict[str, str]]


def parse_ini(data: bytes) -> Sections | None:
    """The sections of an INI file, names and keys in lower case, values as text;
    None when it is not one. Blank lines and lines starting with ``;`` or ``#``
    are skipped; any other line must be ``[section]`` or ``key=value``. Nothing
    in a value is interpreted: no escapes, no lists, no types."""
    if len(data) > MAX_FILE_BYTES:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.removeprefix("﻿")
    sections: Sections = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("["):
            name = line[1:-1].strip().lower() if line.endswith("]") else ""
            if not name or "[" in name or "]" in name:
                return None
            current = sections.setdefault(name, {})
            continue
        key, sep, value = line.partition("=")
        key = key.strip().lower()
        if not sep or not key or any(ord(ch) < 32 and ch != "\t" for ch in line):
            return None
        if current is not None:  # a key before any section belongs to none of ours
            current[key] = value.strip()
    return sections


_TITLES = {"preferences": "Preferences", "session": "Session", "print": "Print"}


def format_ini(sections: Sections) -> str:
    out = [_HEADER]
    for name, values in sections.items():
        out.append(f"\n[{_TITLES.get(name, name)}]\n")
        out.extend(f"{key}={value}\n" for key, value in values.items())
    return "".join(out)


# JSON leaves these three as they are, and parse_ini (str.splitlines) ends a line at each.
_LINE_BREAKS = {c: f"\\u{c:04x}" for c in (0x85, 0x2028, 0x2029)}


def _folder_text(folder: str) -> str:
    return json.dumps(folder, ensure_ascii=False).translate(_LINE_BREAKS)


def _recent(raw: str | None) -> tuple[str, ...]:
    """The recent folders: a JSON list of folders, each checked as the remembered folder
    is; anything else, none."""
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value[:MAX_RECENT]:
        folder = _folder(json.dumps(item)) if isinstance(item, str) else None
        if folder and folder not in out:
            out.append(folder)
    return tuple(out)


def remember_folder(recent: tuple[str, ...], folder: str, keep: int) -> tuple[str, ...]:
    """``recent`` with ``folder`` first (once, compared as the platform compares paths),
    at most ``keep`` long."""
    key = os.path.normcase(os.path.abspath(folder))
    rest = [f for f in recent if os.path.normcase(os.path.abspath(f)) != key]
    return tuple([folder, *rest][: max(0, keep)])


def _folder(raw: str | None) -> str | None:
    """The remembered folder: written as a JSON string, so any character survives;
    a hand-typed path without quotes is taken as it is."""
    if not raw:
        return None
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(value, str):
            return None
        raw = value
    if raw.startswith("@") or not raw.strip() or "\x00" in raw:
        return None
    return os.path.normpath(raw)


def _state(raw: str | None) -> bytes | None:
    """A window or splitter state, written as base64."""
    if not raw or raw.startswith("@") or len(raw) > MAX_STATE_BYTES * 4 // 3 + 4:
        return None
    try:
        value = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return value or None


class SettingsStore:
    """Reads and writes :class:`Settings` and the :class:`Session` in an INI file,
    or only in memory when ``path`` is None. Never raises: a file that cannot be
    read gives defaults, one that cannot be written is left as it is
    (``write_failed`` turns true)."""

    PREFERENCES, SESSION = "preferences", "session"

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.write_failed = False
        self.reset_keys: list[str] = []  # settings whose stored value was not valid
        self._memory: tuple[Settings, Session] = (Settings(), Session())
        self._sections: dict[str, dict[str, str]] = {}  # other sections, for a store in memory

    def _read(self) -> Sections | None:
        """The file's sections: {} when there is no file, None when it is damaged or
        cannot be read."""
        assert self.path is not None
        try:
            with open(self.path, "rb") as fh:
                data = fh.read(MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        return parse_ini(data)

    def _write(self, sections: Sections) -> bool:
        """Replace the file with ``sections``, through a temporary file beside it, so
        a failed write never leaves half a file."""
        assert self.path is not None
        tmp = None
        try:
            folder = os.path.dirname(self.path)
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="Viewer.", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n") as fh:
                fh.write(format_ini(sections))
            os.replace(tmp, self.path)
            tmp = None
            return True
        except (OSError, ValueError):
            return False
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _update(self, name: str, values: dict[str, str] | None) -> bool:
        sections = self._read() or {}  # a damaged file is replaced whole
        if values is None:
            sections.pop(name, None)
        else:
            sections[name] = values
        ok = self._write(sections)
        self.write_failed = self.write_failed or not ok
        return ok

    # -- preferences ---------------------------------------------------------------------
    def load(self) -> Settings:
        if self.path is None:
            return self._memory[0]
        self.reset_keys = []
        try:
            sections = self._read()
            if sections is None:
                self.reset_keys = ["file"]
                return Settings()
            stored = sections.get(self.PREFERENCES, {})
            values: dict[str, Any] = {}
            for f in fields(Settings):
                raw = stored.get(f.name)
                value = parse(f.name, raw) if raw is not None else None
                if value is None:
                    if raw is not None:
                        self.reset_keys.append(f.name)
                    value = getattr(Settings(), f.name)
                values[f.name] = value
            return Settings(**values)
        except Exception:  # whatever went wrong, the viewer starts with every default
            self.reset_keys = ["file"]
            return Settings()

    def save(self, settings: Settings) -> bool:
        if self.path is None:
            self._memory = (settings, self._memory[1])
            return True
        values = {}
        for f in fields(Settings):
            value = getattr(settings, f.name)
            values[f.name] = ("true" if value else "false") if isinstance(value, bool) else str(value)
        return self._update(self.PREFERENCES, values)

    # -- other sections ------------------------------------------------------------------
    def load_section(self, name: str) -> dict[str, str]:
        """The text values of another section, such as ``[Print]``
        (:mod:`.printing`): the caller checks each. Empty when absent or unreadable."""
        if self.path is None:
            return dict(self._sections.get(name, {}))
        try:
            return dict((self._read() or {}).get(name, {}))
        except Exception:
            return {}

    def save_section(self, name: str, values: dict[str, str] | None) -> bool:
        """Replace another section's values, or remove it with None."""
        if name in (self.PREFERENCES, self.SESSION):
            raise ValueError(f"the {name} section has its own methods")
        if self.path is None:
            if values is None:
                self._sections.pop(name, None)
            else:
                self._sections[name] = dict(values)
            return True
        return self._update(name, dict(values) if values is not None else None)

    # -- the session ---------------------------------------------------------------------
    def load_session(self) -> Session:
        if self.path is None:
            return self._memory[1]
        try:
            stored = (self._read() or {}).get(self.SESSION, {})
            return Session(
                folder=_folder(stored.get("folder")),
                geometry=_state(stored.get("geometry")),
                splitter=_state(stored.get("splitter")),
                quick_filter=parse_keys(stored.get("quick_filter")),
                recent=_recent(stored.get("recent")),
            )
        except Exception:
            return Session()

    def save_session(self, session: Session | None) -> bool:
        """Remember ``session``, or forget the stored one with None."""
        if self.path is None:
            self._memory = (self._memory[0], session or Session())
            return True
        values = None
        if session is not None:
            values = {}
            if session.folder:
                values["folder"] = _folder_text(session.folder)
            for key in ("geometry", "splitter"):
                state = getattr(session, key)
                if state and len(state) <= MAX_STATE_BYTES:
                    values[key] = base64.b64encode(state).decode("ascii")
            if session.quick_filter:
                values["quick_filter"] = format_keys(session.quick_filter)
            if session.recent:
                values["recent"] = json.dumps(
                    list(session.recent[:MAX_RECENT]), ensure_ascii=False
                ).translate(_LINE_BREAKS)
        return self._update(self.SESSION, values)
