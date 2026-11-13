"""A library's settings: ``.solidseas/vault/vault.json``, format 1 (``docs/PDM.md`` 3).

The file is plain JSON a person may edit, and it sits in a folder others may write to,
so every field is checked before it is used. A field that does not hold up is an
``invalid_argument`` error (rule ``vault_settings``) that names the field; fields this
version does not know are kept out of the way and ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidArgumentError
from ..resolve.names import component_problem

FORMAT = 1
DEFAULT_LIBRARY = "Library"
MAX_SETTINGS_BYTES = 1 << 20
MAX_DEPTH = 4
MAX_ENTRIES = 1000
MAX_PATTERN = 260
MAX_WHO = 100
_FORBIDDEN = set('/\\<>"|?*')

# Folders that tools keep for themselves, never tracked and never a section or project:
# SolidSeas' own, version control, editors, sync programs and the operating systems'
# bookkeeping. Compared ignoring case. Any other name, dot or not, is the user's.
TOOL_FOLDERS = frozenset(
    name.casefold()
    for name in (
        ".solidseas",
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        ".jj",
        ".beads",
        ".vs",
        ".vscode",
        ".idea",
        ".venv",
        ".cache",
        ".Trash",
        ".Trashes",
        ".fseventsd",
        ".Spotlight-V100",
        ".TemporaryItems",
        ".DocumentRevisions-V100",
        ".AppleDouble",
        ".stfolder",
        ".stversions",
        ".dropbox.cache",
    )
)


def tool_name(name: str) -> bool:
    """Whether a file or folder of this name belongs to a tool, not the user: a folder in
    :data:`TOOL_FOLDERS`, or a macOS resource-fork file (``._name``)."""
    return name.casefold() in TOOL_FOLDERS or name.startswith("._")


@dataclass(frozen=True)
class Section:
    """A top-level folder of the library that holds projects ``depth`` folders down: 1
    when each folder directly under it is a project, 2 when projects sit one folder
    further down (``Customers/Acme/Job 12``)."""

    folder: str
    depth: int = 1

    def to_json(self) -> dict[str, Any]:
        return {"folder": self.folder, "depth": self.depth}


@dataclass(frozen=True)
class Settings:
    """``vault.json``. ``sections`` empty means every top-level folder is a section of
    depth 1. ``library`` is the section of common parts, ``archive`` the sections whose
    projects are history, ``tracked`` extra extensions to track (``.ext``), ``ignore``
    glob patterns never tracked (matched against the path below the library and the
    file name, ignoring case), ``who`` the name check-ins carry unless one is given and
    ``skip_hidden`` whether hidden files and folders are left out too: names that start
    with a dot, and on Windows those with the hidden attribute. Off by default, so a
    project folder or file whose name starts with a dot is tracked like any other; the
    tool folders (:data:`TOOL_FOLDERS`) are always left out."""

    sections: tuple[Section, ...] = ()
    library: str = DEFAULT_LIBRARY
    archive: tuple[str, ...] = ()
    tracked: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    who: str = ""
    skip_hidden: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "sections": [s.to_json() for s in self.sections],
            "library": self.library,
            "archive": list(self.archive),
            "tracked": list(self.tracked),
            "ignore": list(self.ignore),
            "who": self.who,
            "skip_hidden": self.skip_hidden,
        }

    def dumps(self) -> bytes:
        return (json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def from_json(cls, obj: Any) -> Settings:
        if not isinstance(obj, dict):
            raise _bad("the settings are not a JSON object", "format")
        if obj.get("format") != FORMAT:
            raise _bad(
                f"vault.json is not format {FORMAT}: this SolidSeas reads format {FORMAT} only", "format"
            )
        sections_raw = obj.get("sections", [])
        if not isinstance(sections_raw, list) or len(sections_raw) > MAX_ENTRIES:
            raise _bad("sections is a list of {folder, depth} objects", "sections")
        sections = []
        for item in sections_raw:
            if not isinstance(item, dict):
                raise _bad("each section is an object with folder and depth", "sections")
            folder = _folder_name(item.get("folder"), "sections")
            depth = item.get("depth", 1)
            if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= MAX_DEPTH:
                raise _bad(f"a section's depth is a whole number from 1 to {MAX_DEPTH}", "sections")
            sections.append(Section(folder, depth))
        if len({s.folder.casefold() for s in sections}) != len(sections):
            raise _bad("a section is listed twice", "sections")
        library = _folder_name(obj.get("library", DEFAULT_LIBRARY), "library")
        archive = tuple(_folder_name(a, "archive") for a in _list(obj.get("archive", []), "archive"))
        tracked = []
        for ext in _list(obj.get("tracked", []), "tracked"):
            if (
                not isinstance(ext, str)
                or not ext.startswith(".")
                or not 2 <= len(ext) <= 32
                or ext.count(".") != 1
                or any(c in _FORBIDDEN or c.isspace() or ord(c) < 32 for c in ext)
            ):
                raise _bad("tracked lists extensions such as .ext", "tracked")
            tracked.append(ext.lower())
        ignore = []
        for pattern in _list(obj.get("ignore", []), "ignore"):
            if not isinstance(pattern, str) or not 0 < len(pattern) <= MAX_PATTERN or "\0" in pattern:
                raise _bad(f"ignore lists glob patterns of at most {MAX_PATTERN} characters", "ignore")
            ignore.append(pattern)
        who = obj.get("who", "")
        if not isinstance(who, str) or len(who) > MAX_WHO or any(ord(c) < 32 for c in who):
            raise _bad(f"who is a name of at most {MAX_WHO} characters", "who")
        skip_hidden = obj.get("skip_hidden", False)
        if not isinstance(skip_hidden, bool):
            raise _bad("skip_hidden is true or false", "skip_hidden")
        return cls(tuple(sections), library, archive, tuple(tracked), tuple(ignore), who, skip_hidden)

    @classmethod
    def loads(cls, data: bytes) -> Settings:
        if len(data) > MAX_SETTINGS_BYTES:
            raise _bad("vault.json is larger than 1 MiB", "format")
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _bad("vault.json is not valid JSON", "format") from None
        return cls.from_json(obj)


def _bad(message: str, field: str) -> InvalidArgumentError:
    return InvalidArgumentError(
        f"vault.json: {message}", detail={"rule": "vault_settings", "parameter": field}
    )


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        raise _bad(f"{field} is a list of at most {MAX_ENTRIES} entries", field)
    return value


def _folder_name(value: Any, field: str) -> str:
    """One folder name directly in the library: no separator, not a tool's folder."""
    if (
        not isinstance(value, str)
        or component_problem(value) is not None
        or tool_name(value)
        or any(c in _FORBIDDEN for c in value)
    ):
        raise _bad(f"{value!r} is not the name of a folder in the library", field)
    return value


__all__ = ["DEFAULT_LIBRARY", "FORMAT", "TOOL_FOLDERS", "Section", "Settings", "tool_name"]
