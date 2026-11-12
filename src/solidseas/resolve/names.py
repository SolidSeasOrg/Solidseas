"""Names and paths for reference resolution, as strings only.

Nothing in this module touches the filesystem: every filesystem call that
resolution makes goes through :mod:`solidseas.resolve.gateway`.

**Stored paths are Windows strings on every operating system.** A path stored
in a document (``swPath``, a ``Header2`` path, ``SW-Folder Name``) is parsed
here with forward slashes turned into backslashes, and is never handed to the
host's ``os.path``. Its anchor is classified into a closed set
(``docs/API.md`` C2):

* ``drive``: ``X:\\...``;
* ``unc``: ``\\\\host\\share\\...``;
* ``bare``: a file name with no folder at all.

Everything else is ``refused``, with a reason: ``device_path`` (``\\\\?\\`` or
``\\\\.\\``), ``drive_relative`` (``C:name``), ``rooted`` (a single leading
backslash), ``relative`` (folders without an anchor), ``malformed_unc``,
``empty``, ``too_long`` (over 1,024 characters) or ``control_character``.

A drive or UNC path is a usable filesystem target only when every component
passes the checks of the ``windows-path-confinement`` rules: no component made
only of dots and spaces (so no ``..``), no ``:`` (an alternate data stream), no
control character, no reserved device name (``CON``, ``NUL``, ``COM1``...,
with any extension), at most 255 characters, and a file name with a
SOLIDWORKS document extension or the extension of a file a part can be imported
from (:data:`IMPORT_EXTENSIONS`). A path that fails can still be found by name
when its file name passes.

**Names are compared the way NTFS compares them**: per character, by simple
uppercase (:func:`fold`). Python's ``str.upper`` maps "ß" to "SS" and "ﬁ" to
"FI"; a character whose uppercase is more than one character is kept as it is,
so "Straße" and "STRASSE" stay different names, as they are on NTFS. Two names
that are equal only after NFC normalisation (a decomposed "é" against a
composed one) are a second, weaker match (:func:`nfc_fold`), which resolution
reports with the warning ``normalization_differs``.
"""

import ntpath
import os
import posixpath
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..errors import InvalidArgumentError

MAX_STORED_PATH = 1024
MAX_COMPONENT = 255
DOCUMENT_EXTENSIONS = (".sldprt", ".sldasm", ".slddrw")
# Files a part can be imported from, its import source (a part's swFile names the file
# it was opened from): STEP, IGES, Parasolid, ACIS, STL, 3MF, VRML, IFC, JT, Rhino,
# DXF and DWG, and the native files of Inventor, Creo and NX, CATIA and Solid Edge.
IMPORT_EXTENSIONS = (
    ".step", ".stp", ".igs", ".iges", ".x_t", ".x_b", ".xmt_txt", ".xmt_bin", ".sat", ".sab",
    ".stl", ".3mf", ".wrl", ".vrml", ".ifc", ".jt", ".3dm", ".dxf", ".dwg", ".ipt", ".iam",
    ".prt", ".asm", ".catpart", ".catproduct", ".par", ".psm",
)  # fmt: skip
REFERENCE_EXTENSIONS = DOCUMENT_EXTENSIONS + IMPORT_EXTENSIONS
STORED_KINDS = ("drive", "unc", "bare", "refused")

_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"{p}{n}" for p in ("COM", "LPT") for n in "0123456789"]
    + [f"{p}{n}" for p in ("COM", "LPT") for n in "\u00b9\u00b2\u00b3"]
)
_FOLD_CACHE: dict[str, str] = {}

# The host's own path rules, for paths on this machine (never for stored paths).
HOST_WINDOWS = os.name == "nt"
_host = ntpath if HOST_WINDOWS else posixpath


# --------------------------------------------------------------------------- folding
def _upper1(c: str) -> str:
    u = _FOLD_CACHE.get(c)
    if u is None:
        u = c.upper()
        if len(u) != 1:
            u = c  # no single-character uppercase: NTFS keeps the character
        if len(_FOLD_CACHE) < 65536:
            _FOLD_CACHE[c] = u
    return u


def fold(s: str) -> str:
    """``s`` folded for comparison as NTFS compares names: each character by its
    simple uppercase. "ß" and "ss" stay different."""
    if s.isascii():
        return s.upper()
    return "".join(_upper1(c) for c in s)


def nfc_fold(s: str) -> str:
    """:func:`fold` after NFC normalisation: the weaker match."""
    return fold(unicodedata.normalize("NFC", s))


def fold_parts(parts: Iterable[str]) -> tuple[str, ...]:
    return tuple(fold(p) for p in parts)


# --------------------------------------------------------------------------- components
def component_problem(c: str) -> str | None:
    """Why one path component is no filesystem target, or None when it is fine."""
    if not c:
        return "empty_component"
    if len(c) > MAX_COMPONENT:
        return "component_too_long"
    if c.rstrip(". ") == "":
        return "dots_and_spaces"
    if ":" in c:
        return "colon"
    if any(ord(ch) < 32 or ch == "\x7f" for ch in c):
        return "control_character"
    if c.split(".", 1)[0].rstrip(" ").upper() in _RESERVED:
        return "device_name"
    return None


def is_document_name(name: str) -> bool:
    return name.lower().endswith(DOCUMENT_EXTENSIONS)


def is_reference_name(name: str) -> bool:
    """A SOLIDWORKS document's name, or an import source's: a name resolution looks up."""
    return name.lower().endswith(REFERENCE_EXTENSIONS)


def name_problem(name: str | None) -> str | None:
    """Why a file name cannot be looked up, or None."""
    if not name:
        return "empty_name"
    problem = component_problem(name)
    if problem is not None:
        return problem
    if not is_reference_name(name):
        return "not_a_document_name"
    return None


# --------------------------------------------------------------------------- stored paths
@dataclass(frozen=True)
class StoredPath:
    """A path as a document stores it, parsed as a Windows path.

    ``anchor`` is ``"C:"`` (upper case) or ``"\\\\host\\share"`` as stored, and
    empty for a bare name or a refused path. ``folder`` holds the folder
    components after the anchor and ``name`` the file name. ``usable`` says
    whether the whole path may be used as a filesystem target; ``name_ok``
    whether the name may be looked up by itself. ``problem`` names the first
    check that failed (a refusal reason, or a component problem)."""

    raw: str
    kind: str
    anchor: str
    folder: tuple[str, ...]
    name: str | None
    usable: bool
    name_ok: bool
    problem: str | None

    @property
    def folder_key(self) -> tuple[str, ...]:
        return fold_parts(self.folder)


def _refused(raw: str, reason: str, name: str | None = None) -> StoredPath:
    ok = name is not None and name_problem(name) is None
    return StoredPath(raw, "refused", "", (), name, False, ok, reason)


def _split_anchor(text: str) -> tuple[str, str, str] | tuple[None, str, None]:
    """``(kind, anchor, rest)`` of a Windows path whose slashes are backslashes, or
    ``(None, reason, None)`` when its anchor is refused."""
    if text.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        return None, "device_path", None
    if text.startswith("\\\\"):
        parts = text[2:].split("\\")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return None, "malformed_unc", None
        return "unc", "\\\\" + parts[0] + "\\" + parts[1], "\\".join(parts[2:])
    if len(text) >= 2 and text[1] == ":" and text[0].isascii() and text[0].isalpha():
        if len(text) == 2 or text[2] != "\\":
            return None, "drive_relative", None
        return "drive", text[0].upper() + ":", text[3:]
    if text.startswith("\\"):
        return None, "rooted", None
    return "", "", text


def parse_stored(raw: str | None) -> StoredPath:
    """Classify a stored reference path (see the module notes)."""
    if not isinstance(raw, str) or not raw:
        return _refused(raw or "", "empty")
    if len(raw) > MAX_STORED_PATH:
        return _refused(raw, "too_long")
    if "\x00" in raw:
        return _refused(raw, "control_character")
    text = raw.replace("/", "\\")
    tail = text.rsplit("\\", 1)[-1]
    kind, anchor, rest = _split_anchor(text)
    if kind is None:
        return _refused(raw, anchor, tail or None)
    parts = [p for p in rest.split("\\") if p not in ("", ".")]
    if not kind:  # no anchor at all
        if len(parts) == 1:
            name = parts[0]
            problem = name_problem(name)
            return StoredPath(raw, "bare", "", (), name, False, problem is None, problem)
        return _refused(raw, "relative" if parts else "empty", parts[-1] if parts else None)
    if not parts:
        return _refused(raw, "malformed_unc" if kind == "unc" else "empty", tail or None)
    name, folder = parts[-1], tuple(parts[:-1])
    problem = name_problem(name)
    name_ok = problem is None
    if problem is None:
        for c in folder:
            problem = component_problem(c)
            if problem is not None:
                break
    return StoredPath(raw, kind, anchor, folder, name, problem is None, name_ok, problem)


@dataclass(frozen=True)
class StoredFolder:
    """A folder as a document stores it (``SW-Folder Name``) or as a path map names
    it: a drive or UNC anchor and its components."""

    kind: str
    anchor: str
    parts: tuple[str, ...]

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return fold(self.anchor), fold_parts(self.parts)


def parse_stored_folder(raw: str | None) -> StoredFolder | None:
    """A drive or UNC folder, or None when the text is empty or not one (or a
    component is no filesystem target)."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_STORED_PATH or "\x00" in raw:
        return None
    kind, anchor, rest = _split_anchor(raw.strip().replace("/", "\\"))
    if not kind:
        return None
    parts = tuple(p for p in rest.split("\\") if p not in ("", "."))
    if any(component_problem(p) is not None for p in parts):
        return None
    return StoredFolder(kind, anchor, parts)


# --------------------------------------------------------------------------- host paths
@dataclass(frozen=True)
class HostPath:
    """A path on this machine as an anchor (``"C:"``, ``"\\\\host\\share"`` or ``"/"``)
    and its components."""

    anchor: str
    parts: tuple[str, ...]

    def join(self, *more: str) -> str:
        parts = (*self.parts, *more)
        if HOST_WINDOWS:
            return self.anchor + "\\" + "\\".join(parts)
        return "/" + "/".join(parts)

    def child(self, *more: str) -> "HostPath":
        return HostPath(self.anchor, (*self.parts, *more))

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return fold(self.anchor), fold_parts(self.parts)


def host_split(path: str) -> HostPath:
    """An absolute host path split into its anchor and components (string only)."""
    norm = _host.normpath(path)
    if HOST_WINDOWS:
        drive, rest = ntpath.splitdrive(norm)
        anchor = drive[0].upper() + drive[1:] if len(drive) == 2 and drive[1] == ":" else drive
        return HostPath(anchor, tuple(p for p in rest.split("\\") if p))
    return HostPath("/", tuple(p for p in norm.split("/") if p))


def from_stored(anchor: str, parts: Sequence[str]) -> HostPath | None:
    """A stored Windows location as a host path: itself on Windows, None elsewhere
    (drive letters and UNC anchors do not exist there; a path map is the way)."""
    if not HOST_WINDOWS or not anchor:
        return None
    return HostPath(anchor, tuple(parts))


def suffix_tails(folder: Sequence[str]) -> list[tuple[str, ...]]:
    """The tails of a stored folder that SOLIDWORKS' folder probe puts between each
    folder it searches and the name, in the order they are tried: none (the bare
    name), then the last 1, 2... components. Every search for a reference by folder
    takes its order from here. Whether SOLIDWORKS itself tries the longest tail first
    is not settled (bead SolidSeas-bx4q): the two differ only when both would find a
    file."""
    return [tuple(folder[len(folder) - n :]) if n else () for n in range(len(folder) + 1)]


def suffix_score(a: Sequence[str], b: Sequence[str]) -> int:
    """How many trailing folder components ``a`` and ``b`` share, compared folded."""
    n = 0
    for x, y in zip(reversed(a), reversed(b), strict=False):
        if fold(x) != fold(y):
            break
        n += 1
    return n


# --------------------------------------------------------------------------- path map
@dataclass(frozen=True)
class PathMapping:
    """``source`` (a stored drive or UNC prefix) maps to ``target`` (a folder on this
    machine). The target is configuration, not file content."""

    source: StoredFolder
    target: HostPath
    text: str  # "FROM=TO" as given, for messages

    def apply(self, stored: StoredPath) -> HostPath | None:
        """The stored path on this machine, or None when the mapping does not apply.
        It applies at a component boundary, compared folded."""
        if not stored.usable or stored.name is None:
            return None
        anchor, parts = self.source.key
        if fold(stored.anchor) != anchor or stored.folder_key[: len(parts)] != parts:
            return None
        return self.target.child(*stored.folder[len(parts) :], stored.name)


def parse_path_map(items: Iterable[str | tuple[str, str]] | None) -> tuple[PathMapping, ...]:
    """Path mappings from ``"FROM=TO"`` strings or ``(FROM, TO)`` pairs. ``FROM`` is a
    Windows drive or UNC prefix as documents store it; ``TO`` an absolute folder on
    this machine. A string is split at its first ``=``. Anything else, a single string
    included, raises :class:`InvalidArgumentError` naming ``path_map``."""
    if items is None:
        return ()
    if isinstance(items, (str, bytes)) or not isinstance(items, Iterable):
        raise InvalidArgumentError(
            "path_map is a list of FROM=TO strings or (FROM, TO) pairs", detail={"parameter": "path_map"}
        )
    out = []
    for item in items:
        if isinstance(item, str):
            src, sep, dst = item.partition("=")
            if not sep:
                raise InvalidArgumentError(
                    f"a path mapping is FROM=TO, not {item!r}", detail={"parameter": "path_map"}
                )
        elif isinstance(item, (tuple, list)) and len(item) == 2 and all(isinstance(x, str) for x in item):
            src, dst = item
        else:
            raise InvalidArgumentError(
                "a path mapping is a FROM=TO string or a (FROM, TO) pair of strings",
                detail={"parameter": "path_map"},
            )
        source = parse_stored_folder(src)
        if source is None:
            raise InvalidArgumentError(
                f"a path mapping starts with a drive (X:\\) or a share (\\\\host\\share), not {src!r}",
                detail={"parameter": "path_map"},
            )
        if not isinstance(dst, str) or not dst or "\x00" in dst or not _host.isabs(dst):
            raise InvalidArgumentError(
                f"a path mapping maps to an absolute folder on this machine, not {dst!r}",
                detail={"parameter": "path_map"},
            )
        target = host_split(dst)
        if HOST_WINDOWS and (target.anchor.startswith("\\\\?") or target.anchor.startswith("\\\\.")):
            raise InvalidArgumentError(
                "a path mapping cannot map to a device path", detail={"parameter": "path_map"}
            )
        if any(component_problem(p) is not None for p in target.parts):
            raise InvalidArgumentError(
                f"a path mapping target has a component that is no folder name: {dst!r}",
                detail={"parameter": "path_map"},
            )
        out.append(PathMapping(source, target, f"{src}={dst}"))
    return tuple(out)


__all__ = [
    "DOCUMENT_EXTENSIONS",
    "IMPORT_EXTENSIONS",
    "MAX_STORED_PATH",
    "REFERENCE_EXTENSIONS",
    "STORED_KINDS",
    "HostPath",
    "PathMapping",
    "StoredFolder",
    "StoredPath",
    "component_problem",
    "fold",
    "from_stored",
    "host_split",
    "is_document_name",
    "is_reference_name",
    "name_problem",
    "nfc_fold",
    "parse_path_map",
    "parse_stored",
    "parse_stored_folder",
    "suffix_score",
    "suffix_tails",
]
