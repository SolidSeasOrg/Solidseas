"""Extensions: optional modules each person adds and switches on (``docs/EXTENSIONS.md``).

The core knows every first-party extension (:data:`CATALOG`): its manifest (section 3),
whether it is built in or comes as a package, and, for a packaged one, the SHA-256s of
the package files this core accepts (:data:`ACCEPTED`, written by the release build;
empty in a source checkout, where packages are not used). This module holds what the
Extensions page, the viewer and the MCP server ask, and nothing here imports Qt:

* :func:`statuses` says, for each extension, whether it is built in, added (with its
  version) or not added, whether it is on, and why it cannot be when it cannot.
* :func:`is_on` is the one test a front uses before it adds anything: switched on in
  ``Extensions.json`` (:class:`ExtensionState`), allowed by the machine policy
  (``DisableExtensions``, ``AllowedExtensions``), and, for a packaged extension, its
  package added.
* :func:`check_package` checks a downloaded package before anything is unpacked: its
  SHA-256 is one this core accepts; every entry is a plain file whose name stays
  inside the extension's folder (no ``..``, no absolute or drive path, no link, no
  name twice without regard to case); sizes and the compression ratio are bounded;
  its ``extension.json`` is the core's own manifest for that extension; and every
  file the manifest names is there with its SHA-256.
* :func:`add_package` unpacks a checked package into a new temporary folder beside
  the others under :func:`extensions_root` and renames it into place; an older
  version there is kept until the new one is in place, then removed.
  :func:`remove_package` deletes that extension's own folder and nothing else.

A package's code never runs in this process: a packaged extension's helper is a
child program the core starts (section 6).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from solidseas import __version__, policy

STATE_VERSION = 1
STATE_FILE = "Extensions.json"
MANIFEST = "extension.json"
MAX_STATE_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_NOTICE = 200_000  # a licence's whole text
MAX_PACKAGE_BYTES = 2 * 1024**3  # unpacked, a whole package
MAX_ENTRY_BYTES = 1024**3
MAX_ENTRIES = 20_000
MAX_RATIO = 200  # unpacked to packed, an entry: more than this is a zip bomb
_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")
_SEGMENT = re.compile(r"[A-Za-z0-9 ._+()\-]{1,128}")
_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
NETWORK = ("none", "loopback", "ssh")
KINDS = ("built_in", "packaged")
RELEASES_URL = "https://github.com/SolidSeas/SolidSeas/releases"
# What is on before the person has chosen: the extensions that were part of SolidSeas
# before extensions existed, so an update does not take away what someone already uses.
DEFAULT_ON = frozenset({"gridfinity"})
# The extension that reaches the person's own SOLIDWORKS. Its id was "solidworks" until it
# was renamed so that no SolidSeas name is made of another company's trademark; the former
# id still names it everywhere (:func:`current_id`).
BRIDGE = "cad-bridge"


def current_id(extension_id: str) -> str:
    """``extension_id`` under its current name: a former id (``policy.RENAMED_EXTENSIONS``)
    is the id it became, so the state, packages and policies written before a rename work."""
    return policy.RENAMED_EXTENSIONS.get(extension_id, extension_id)


def former_ids(extension_id: str) -> tuple[str, ...]:
    """The ids ``extension_id`` had before it was renamed, oldest first."""
    return tuple(old for old, new in policy.RENAMED_EXTENSIONS.items() if new == extension_id)


class ExtensionError(ValueError):
    """A manifest, a package or the state that SolidSeas refuses, with the reason in words."""


# --------------------------------------------------------------------------- manifests
@dataclass(frozen=True)
class Manifest:
    """An extension's manifest (``docs/EXTENSIONS.md`` section 3), checked."""

    id: str
    name: str
    version: str
    publisher: str
    description: str
    kind: str
    core: str
    adds: tuple[str, ...]
    needs: tuple[dict[str, str], ...]
    network: str
    folders: tuple[str, ...]
    helper: dict[str, Any] | None
    notices: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "description": self.description,
            "kind": self.kind,
            "core": self.core,
            "adds": list(self.adds),
            "needs": [dict(n) for n in self.needs],
            "reaches": {"network": self.network, "folders": list(self.folders)},
            "helper": None if self.helper is None else dict(self.helper),
            "notices": list(self.notices),
        }


def _text(raw: Mapping[str, Any], key: str, limit: int = 200, *, lines: bool = False) -> str:
    """``raw[key]``, text of at most ``limit`` characters with no control character; with
    ``lines`` (a notice: a licence's whole text) line breaks and tabs are text too."""
    value = raw.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 and not (lines and c in "\n\r\t") for c in value)
    ):
        shape = "" if lines else " on one line"
        raise ExtensionError(f"the manifest's {key} is not text of at most {limit} characters{shape}")
    return value


def _texts(raw: Any, what: str, limit: int = 200, *, lines: bool = False) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > 64:
        raise ExtensionError(f"the manifest's {what} is not a list")
    return tuple(_text({what: v}, what, limit, lines=lines) for v in raw)


def manifest(raw: Any) -> Manifest:
    """The :class:`Manifest` in ``raw`` (parsed ``extension.json``), checked."""
    if not isinstance(raw, dict):
        raise ExtensionError("the manifest is not an object")
    mid = _text(raw, "id", 32)
    if not _ID.fullmatch(mid):
        raise ExtensionError(f"{mid!r} is not an extension id")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ExtensionError("the manifest's kind is built_in or packaged")
    reaches = raw.get("reaches")
    if not isinstance(reaches, dict) or reaches.get("network") not in NETWORK:
        raise ExtensionError(f"the manifest's reaches.network is one of {', '.join(NETWORK)}")
    needs_raw = raw.get("needs", [])
    if not isinstance(needs_raw, list) or len(needs_raw) > 16:
        raise ExtensionError("the manifest's needs is not a list")
    needs = tuple(
        {"what": _text(n, "what"), "missing": _text(n, "missing", 400)}
        for n in needs_raw
        if isinstance(n, dict)
    )
    if len(needs) != len(needs_raw):
        raise ExtensionError("each of the manifest's needs is an object")
    helper = raw.get("helper")
    if kind == "packaged":
        if not isinstance(helper, dict):
            raise ExtensionError("a packaged extension's manifest names its helper")
        _package_path(_text(helper, "program"))
        files = helper.get("files")
        if not isinstance(files, dict) or not files or len(files) > MAX_ENTRIES:
            raise ExtensionError("the manifest's helper.files lists the package's files with their SHA-256s")
        for name, digest in files.items():
            _package_path(name)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ExtensionError(f"the SHA-256 of {name} in the manifest is not one")
        for key in ("protocol", "memory_mb", "seconds"):
            if not isinstance(helper.get(key), int) or isinstance(helper.get(key), bool) or helper[key] <= 0:
                raise ExtensionError(f"the manifest's helper.{key} is a whole number above 0")
        helper = dict(helper)
    elif helper is not None:
        raise ExtensionError("a built-in extension has no helper")
    publisher = _text(raw, "publisher", 64)
    if publisher != "SolidSeas":
        raise ExtensionError("only SolidSeas' own extensions are taken")
    return Manifest(
        mid,
        _text(raw, "name", 64),
        _text(raw, "version", 32),
        publisher,
        _text(raw, "description", 400),
        kind,
        _text(raw, "core", 64),
        _texts(raw.get("adds", []), "adds"),
        needs,
        reaches["network"],
        _texts(reaches.get("folders", []), "reaches.folders"),
        helper,
        _texts(raw.get("notices", []), "notices", MAX_NOTICE, lines=True),
    )


def _builtin(mid: str, name: str, description: str, adds, needs, network: str, folders=()) -> Manifest:
    return manifest(
        {
            "id": mid,
            "name": name,
            "version": __version__,
            "publisher": "SolidSeas",
            "description": description,
            "kind": "built_in",
            "core": __version__,
            "adds": list(adds),
            "needs": list(needs),
            "reaches": {"network": network, "folders": list(folders)},
            "helper": None,
            "notices": [],
        }
    )


def _packaged(mid: str, name: str, description: str, adds, needs, network: str, program: str) -> Manifest:
    """A packaged extension as the core knows it before its package is built: the
    helper's files are filled in from the package's own manifest, which must agree
    with everything else here (:func:`check_package`)."""
    return Manifest(
        mid,
        name,
        __version__,
        "SolidSeas",
        description,
        "packaged",
        __version__,
        tuple(adds),
        tuple(needs),
        network,
        (),
        {"program": program},
        (),
    )


CATALOG: dict[str, Manifest] = {
    m.id: m
    for m in (
        _builtin(
            "gridfinity",
            "Gridfinity bins",
            "Bins for your tools from photos of them, traced by Tracefinity, as STL files to print.",
            ("the gridfinity_* chat tools", "Gridfinity settings"),
            (
                {
                    "what": "Tracefinity",
                    "missing": "Run Tracefinity on this PC or a server of yours (docs/GRIDFINITY.md).",
                },
            ),
            "ssh",
            ("Pictures\\Gridfinity", "Documents\\Gridfinity bins"),
        ),
        _packaged(
            BRIDGE,
            "CAD Bridge",
            "Connects SolidSeas to your own SOLIDWORKS installation on this PC through its published "
            "API: the assistant's live mode and Automatic mode, and the chat tools for parts open there.",
            ("the assistant's session picker and Automatic mode", "the chat tools for SOLIDWORKS parts"),
            (
                {
                    "what": "SOLIDWORKS 2024 or later",
                    "missing": "Install SOLIDWORKS 2024 or later on this PC.",
                },
            ),
            "none",
            "SolidSeas.SwBridge.exe",
        ),
        _packaged(
            "video",
            "Video export",
            "Save Animation in the 3D view: the model turning, exploding and collapsing, "
            "as an animated GIF or MP4.",
            ("Save Animation in the 3D view",),
            (),
            "none",
            "solidseas-video.exe",
        ),
        _packaged(
            "solidcraft",
            "SolidCraft",
            "SolidCraft, a free parametric CAD program, in the chat: the assistant models new parts in it, "
            "measures them, takes screenshots and exports STEP, 3MF or STL, without SOLIDWORKS.",
            ("the solidcraft_* chat tools",),
            (),
            "none",
            "solidcraft-cli.exe",
        ),
        _packaged(
            "occt",
            "OCCT backend",
            "Opens IGES and BREP files in the viewer and the command line, and writes IGES, BREP and "
            "STEP with File > Convert and solidseas convert, through Open CASCADE.",
            (
                "IGES and BREP files in the viewer and the command line",
                "File > Convert in the viewer",
                "IGES, BREP and STEP from solidseas convert",
            ),
            (),
            "none",
            "solidseas-occt.exe",
        ),
    )
}


def _read_accepted() -> dict[str, frozenset[str]]:
    """``accepted.json`` beside this module, which the release build writes
    (:mod:`.package`); nothing when there is none, as in a source checkout."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accepted.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    listed = raw.get("accepted") if isinstance(raw, dict) and raw.get("version") == 1 else None
    if not isinstance(listed, dict):
        return {}
    out: dict[str, frozenset[str]] = {}
    for k, v in listed.items():
        if isinstance(k, str) and current_id(k) in CATALOG and isinstance(v, list):
            hashes = frozenset(h for h in v if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h))
            out[current_id(k)] = out.get(current_id(k), frozenset()) | hashes
    return out


# What this core accepts: extension id -> the SHA-256s of its package files, from the
# release build's accepted.json; a source checkout has none, so accepts no package.
ACCEPTED: dict[str, frozenset[str]] = _read_accepted()


# --------------------------------------------------------------------------- where
def data_dir() -> str:
    """``%LOCALAPPDATA%\\SolidSeas`` (``~/.cache/solidseas`` elsewhere), as the rest of
    SolidSeas keeps its files; ``SOLIDSEAS_CACHE_DIR`` overrides it."""
    env = os.environ.get("SOLIDSEAS_CACHE_DIR")
    if env:
        return os.path.abspath(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "SolidSeas")
    return os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "solidseas"
    )


def extensions_root() -> str:
    return os.path.join(data_dir(), "extensions")


def installed_dir(extension_id: str, root: str | None = None) -> str:
    """The folder a package of ``extension_id`` is added to (named by its current id)."""
    return os.path.join(root or extensions_root(), _known(extension_id).id)


def _known(extension_id: str) -> Manifest:
    found = CATALOG.get(current_id(extension_id))
    if found is None:
        raise ExtensionError(f"there is no extension {extension_id!r}")
    return found


# --------------------------------------------------------------------------- state
@dataclass(frozen=True)
class ExtensionState:
    """Which extensions the person switched on, and each extension's settings
    (:data:`SETTINGS`), from ``Extensions.json`` beside ``Viewer.ini``."""

    on: frozenset[str] = field(default_factory=frozenset)
    settings: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": STATE_VERSION, "on": sorted(self.on)}
        kept = {i: dict(v) for i, v in sorted(self.settings.items()) if v}
        if kept:
            out["settings"] = kept
        return out


# Each extension's settings, kept on the Extensions page: key -> the environment variable
# that still overrides it (so a chat's own configuration keeps working).
SETTINGS: dict[str, dict[str, str]] = {
    "gridfinity": {
        "photos": "SOLIDSEAS_GRIDFINITY_PHOTOS",
        "bins": "SOLIDSEAS_GRIDFINITY_BINS",
        "tracefinity_url": "SOLIDSEAS_TRACEFINITY_URL",
        "ssh": "SOLIDSEAS_TRACEFINITY_SSH",
        "ssh_key": "SOLIDSEAS_TRACEFINITY_SSH_KEY",
    }
}
MAX_SETTING = 1000


def _setting_value(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_SETTING or any(ord(c) < 32 for c in value):
        return None
    return value.strip() or None


def _settings_in(raw: Any) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for mid, keys in SETTINGS.items():
        given = raw.get(mid)
        if not isinstance(given, dict):
            continue
        kept = {k: v for k in keys if (v := _setting_value(given.get(k))) is not None}
        if kept:
            out[mid] = kept
    return out


def with_setting(state: ExtensionState, extension_id: str, key: str, value: str | None) -> ExtensionState:
    """``state`` with ``extension_id``'s setting ``key`` set to ``value`` (None or blank: back
    to its default)."""
    if key not in SETTINGS.get(extension_id, {}):
        raise ExtensionError(f"{extension_id} has no setting {key!r}")
    settings = {i: dict(v) for i, v in state.settings.items()}
    mine = settings.setdefault(extension_id, {})
    clean = _setting_value(value) if value is not None else None
    if value is not None and value.strip() and clean is None:
        raise ExtensionError(f"a setting is text of at most {MAX_SETTING} characters on one line")
    if clean is None:
        mine.pop(key, None)
    else:
        mine[key] = clean
    return ExtensionState(state.on, {i: v for i, v in settings.items() if v})


def setting(extension_id: str, key: str, state: ExtensionState | None = None) -> str | None:
    """An extension's setting: its environment variable when that is set, else what the
    Extensions page saved, else None (the extension's own default)."""
    env = SETTINGS[extension_id][key]
    chosen = os.environ.get(env)
    if chosen and chosen.strip():
        return chosen
    state = state if state is not None else read_state()
    return state.settings.get(extension_id, {}).get(key)


def state_path() -> str:
    """``SolidSeas\\Extensions.json`` beside ``Viewer.ini``: the roaming application-data
    folder on Windows, ``~/.config`` elsewhere (``XDG_CONFIG_HOME``)."""
    override = os.environ.get("SOLIDSEAS_EXTENSIONS_FILE")  # for tests and portable setups
    if override:
        return os.path.abspath(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "SolidSeas", STATE_FILE)


def read_state(path: str | None = None) -> ExtensionState:
    """The state in ``path`` (:func:`state_path` by default); :data:`DEFAULT_ON` when the
    file is missing, damaged or of another version (it is written afresh on the next
    change)."""
    path = path or state_path()
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_STATE_BYTES + 1)
        raw = json.loads(data.decode("utf-8")) if len(data) <= MAX_STATE_BYTES else None
    except (OSError, ValueError, UnicodeDecodeError):
        return ExtensionState(DEFAULT_ON)
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("on"), list)
    ):
        return ExtensionState(DEFAULT_ON)
    # a former id is read as the one it became; the next write stores the current id
    on = frozenset(current_id(i) for i in raw["on"] if isinstance(i, str) and current_id(i) in CATALOG)
    return ExtensionState(on, _settings_in(raw.get("settings")))


def write_state(path: str, state: ExtensionState) -> None:
    """Write ``state`` to ``path`` through a temporary file and a rename."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.urandom(4).hex()}.tmp"
    with open(tmp, "x", encoding="utf-8") as fh:
        json.dump(state.to_json(), fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def switched(state: ExtensionState, extension_id: str, on: bool) -> ExtensionState:
    mid = _known(extension_id).id
    return ExtensionState(state.on | {mid} if on else state.on - {mid}, state.settings)


# --------------------------------------------------------------------------- status
@dataclass(frozen=True)
class Status:
    """One extension on the Extensions page: its manifest, whether its package is added
    (always for a built-in one) and its version, whether it is on, and why it cannot be
    switched on when it cannot (an administrator, or no package)."""

    manifest: Manifest
    added: bool
    added_version: str | None
    on: bool
    blocked: str | None


def _read_manifest(folder: str) -> Manifest | None:
    try:
        with open(os.path.join(folder, MANIFEST), "rb") as fh:
            return manifest(json.loads(fh.read(MAX_MANIFEST_BYTES).decode("utf-8")))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _added(extension_id: str, root: str | None = None) -> tuple[str, Manifest] | None:
    """The folder and manifest of the package added for ``extension_id``: in its own
    folder, or, for a package added before the extension was renamed and not replaced
    since, in the folder of a former id whose manifest still says that id."""
    m = _known(extension_id)
    base = root or extensions_root()
    folder = os.path.join(base, m.id)
    found = _read_manifest(folder)
    if found is not None and found.id == m.id:
        return folder, found
    for old in former_ids(m.id):
        folder = os.path.join(base, old)
        if os.path.islink(folder):
            continue
        found = _read_manifest(folder)
        if found is not None and found.id == old:
            return folder, found
    return None


def added_manifest(extension_id: str, root: str | None = None) -> Manifest | None:
    """The manifest of the package added for ``extension_id``, None when none is (or
    what is there is damaged)."""
    added = _added(extension_id, root)
    return added[1] if added else None


def statuses(
    state: ExtensionState, *, pol: policy.Policy | None = None, root: str | None = None
) -> list[Status]:
    pol = pol if pol is not None else policy.current()
    out = []
    for m in CATALOG.values():
        package = added_manifest(m.id, root) if m.kind == "packaged" else None
        added = m.kind == "built_in" or package is not None
        blocked = None
        if not policy.extension_allowed(pol, m.id):
            blocked = "Set by your administrator"
        elif not added:
            blocked = "Add its package first"
        out.append(
            Status(
                m, added, package.version if package else None, m.id in state.on and blocked is None, blocked
            )
        )
    return out


def is_on(
    extension_id: str, state: ExtensionState, *, pol: policy.Policy | None = None, root: str | None = None
) -> bool:
    """Whether ``extension_id`` is on (see the module notes): what a front asks before it
    adds anything."""
    m = _known(extension_id)
    pol = pol if pol is not None else policy.current()
    if m.id not in state.on or not policy.extension_allowed(pol, m.id):
        return False
    return m.kind == "built_in" or _added(m.id, root) is not None


def on_ids(
    state: ExtensionState, *, pol: policy.Policy | None = None, root: str | None = None
) -> frozenset[str]:
    pol = pol if pol is not None else policy.current()
    return frozenset(i for i in CATALOG if is_on(i, state, pol=pol, root=root))


# --------------------------------------------------------------------------- packages
def _package_path(name: Any) -> str:
    """A path inside a package, checked: relative, ``/``-separated, each part a plain
    name (no ``..``, no drive, no Windows device name)."""
    if not isinstance(name, str) or not name or len(name) > 400 or name.startswith(("/", "\\")):
        raise ExtensionError(f"{str(name)[:60]!r} is not a path inside the package")
    parts = name.split("/")
    for part in parts:
        if (
            not _SEGMENT.fullmatch(part)
            or part in (".", "..")
            or part.endswith((" ", "."))
            or part.split(".")[0].lower() in _WINDOWS_NAMES
        ):
            raise ExtensionError(f"{name[:60]!r} is not a path inside the package")
    return name


@dataclass(frozen=True)
class CheckedPackage:
    """A package that passed :func:`check_package`: its manifest, its SHA-256, and its
    files (path -> size)."""

    path: str
    sha256: str
    manifest: Manifest
    files: dict[str, int]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_package(path: str, *, accepted: Mapping[str, Iterable[str]] | None = None) -> CheckedPackage:
    """Check the package at ``path`` (see the module notes); :class:`ExtensionError` with
    the reason when it is refused. Nothing is unpacked."""
    accepted = ACCEPTED if accepted is None else accepted
    digest = _sha256(path)
    owner = next((i for i, hashes in accepted.items() if digest in set(hashes)), None)
    if owner is None:
        raise ExtensionError(
            "This package is not one this version of SolidSeas accepts. Download the package made "
            "for this version from the releases page."
        )
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise ExtensionError("This package is not a zip file.") from None
    with z:
        infos = z.infolist()
        if not infos or len(infos) > MAX_ENTRIES:
            raise ExtensionError("This package holds no files, or too many.")
        files: dict[str, int] = {}
        seen: set[str] = set()
        total = 0
        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ExtensionError(f"{info.filename[:60]} in the package is a link.")
            if info.is_dir():
                _package_path(info.filename.rstrip("/"))
                continue
            name = _package_path(info.filename)
            if name.casefold() in seen:
                raise ExtensionError(f"{name[:60]} is in the package twice.")
            seen.add(name.casefold())
            if (
                info.file_size > MAX_ENTRY_BYTES
                or info.file_size > MAX_RATIO * max(info.compress_size, 1) + 4096
            ):
                raise ExtensionError(f"{name[:60]} in the package is larger than SolidSeas unpacks.")
            total += info.file_size
            files[name] = info.file_size
        if total > MAX_PACKAGE_BYTES:
            raise ExtensionError("The package is larger than SolidSeas unpacks.")
        if MANIFEST not in files:
            raise ExtensionError(f"The package has no {MANIFEST}.")
        try:
            found = manifest(json.loads(z.read(MANIFEST).decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ExtensionError(f"The package's {MANIFEST} is refused: {exc}") from None
        _agrees(owner, found)
        listed = dict((found.helper or {}).get("files") or {})
        missing = [n for n in listed if n not in files]
        extra = [n for n in files if n not in listed and n != MANIFEST]
        if missing or extra:
            raise ExtensionError(
                "The package's files are not the ones its manifest lists"
                + (f": {missing[0]} is missing" if missing else f": {extra[0]} is not listed")
            )
        for name, want in listed.items():
            h = hashlib.sha256()
            with z.open(name) as fh:
                for chunk in iter(lambda fh=fh: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != want:
                raise ExtensionError(f"{name[:60]} in the package is not the file its manifest names.")
    return CheckedPackage(path, digest, found, files)


def _agrees(owner: str, found: Manifest) -> None:
    """The package's manifest must be the core's own for that extension in everything
    but the helper's files and the notices, which only the package can list."""
    core = CATALOG[owner]
    if found.id != owner:
        raise ExtensionError(f"The package says it is {found.id!r}, but its file is {owner!r}'s.")
    pairs = (
        ("kind", core.kind, found.kind),
        ("adds", core.adds, found.adds),
        ("network", core.network, found.network),
        ("helper program", (core.helper or {}).get("program"), (found.helper or {}).get("program")),
    )
    for what, want, got in pairs:
        if want != got:
            raise ExtensionError(f"The package's manifest does not match this SolidSeas ({what}).")


def add_package(checked: CheckedPackage, *, root: str | None = None) -> str:
    """Unpack ``checked`` into its extension's folder (see the module notes) and return it."""
    root = root or extensions_root()
    os.makedirs(root, exist_ok=True)
    target = installed_dir(checked.manifest.id, root)
    temp = os.path.join(root, f".{checked.manifest.id}.{os.urandom(4).hex()}.new")
    os.mkdir(temp)
    try:
        with zipfile.ZipFile(checked.path) as z:
            for name in checked.files:
                dest = os.path.join(temp, *name.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(name) as src, open(dest, "xb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
        old = None
        if os.path.lexists(target):
            if os.path.islink(target) or not os.path.isdir(target):
                raise ExtensionError(f"{target} is not a folder SolidSeas made; it is left alone.")
            old = os.path.join(root, f".{checked.manifest.id}.{os.urandom(4).hex()}.old")
            os.rename(target, old)
        os.rename(temp, target)
        temp = ""
        if old:
            shutil.rmtree(old, ignore_errors=True)
        # A package added before the extension was renamed sits in its former id's folder:
        # the new one replaces it, so that folder goes too (never through a link).
        for former in former_ids(checked.manifest.id):
            stale = os.path.join(root, former)
            if os.path.isdir(stale) and not os.path.islink(stale):
                shutil.rmtree(stale, ignore_errors=True)
        return target
    finally:
        if temp and os.path.isdir(temp):
            shutil.rmtree(temp, ignore_errors=True)


class HelperRefused(ExtensionError):
    """A packaged extension's helper SolidSeas will not start: the extension is off, its
    package is not added, or a file in it is not the one its manifest names."""


def start_helper(
    extension_id: str,
    state: ExtensionState,
    *,
    pol: policy.Policy | None = None,
    root: str | None = None,
    on_event=None,
    launcher=None,
    helper_class=None,
    args=(),
):
    """Start the helper of the packaged extension ``extension_id`` and return it, a
    :class:`solidseas.helpers.Helper` (section 6): only while it is on (:func:`is_on`),
    and only after every file of its package is checked again against the SHA-256 its
    manifest names, so a file changed since it was added is never run. It runs in a Job
    Object with the manifest's memory cap; each request's timeout is the manifest's
    ``seconds``. ``launcher(program)`` gives the command line (the program alone by
    default; a test runs a stand-in through Python), and ``args`` follow it.
    ``helper_class`` is the kind of helper (:class:`solidseas.helpers.McpHelper` for an
    MCP server, such as SolidCraft's)."""
    from solidseas.helpers import Helper

    helper_class = helper_class or Helper

    m = _known(extension_id)
    if m.kind != "packaged":
        raise HelperRefused(f"{m.name} is built in and has no helper")
    if not is_on(extension_id, state, pol=pol, root=root):
        raise HelperRefused(f"{m.name} is off; switch it on in Tools > Extensions")
    found = _added(m.id, root)
    if found is None or found[1].helper is None:
        raise HelperRefused(f"{m.name}'s package is not added")
    folder, added = found
    for name, want in added.helper["files"].items():
        path = os.path.join(folder, *name.split("/"))
        if os.path.islink(path) or not os.path.isfile(path) or _sha256(path) != want:
            raise HelperRefused(
                f"{name} in {m.name}'s package is not the file it was added with; remove the "
                "extension and add its package again"
            )
    program = os.path.join(folder, *added.helper["program"].split("/"))
    command = (launcher(program) if launcher is not None else [program]) + list(args)
    seconds = float(added.helper["seconds"])
    return helper_class(
        command,
        label=f"the {m.name} helper",
        protocol=int(added.helper["protocol"]),
        memory_mb=int(added.helper["memory_mb"]),
        on_event=on_event,
        hard_limit=seconds,
        thread_name=f"ext-{m.id}",
    )


BESIDE_FOLDERS = ("SolidSeas extensions", "extensions")  # beside the viewer, where a release keeps them


def beside_folders() -> list[str]:
    """Where packages that came with the viewer are: the folders :data:`BESIDE_FOLDERS`
    beside the executable (none in a source checkout)."""
    if not getattr(sys, "frozen", False):
        return []
    here = os.path.dirname(os.path.abspath(sys.executable))
    return [os.path.join(here, name) for name in BESIDE_FOLDERS]


def add_beside(
    folders: Iterable[str] | None = None,
    *,
    root: str | None = None,
    accepted: Mapping[str, Iterable[str]] | None = None,
    pol: policy.Policy | None = None,
) -> list[str]:
    """Add the packages that came with the viewer (in ``folders``, by default
    :func:`beside_folders`), so its extensions are listed as added the first time it starts:
    each zip this core accepts (:func:`check_package`) whose extension is not already added
    at that version. Switches are left as they are: an extension added this way is off
    until switched on. Nothing under an administrator's ``DisableExtensions`` or outside
    ``AllowedExtensions``; a zip refused or unreadable is skipped. The ids added."""
    pol = pol if pol is not None else policy.current()
    if pol.extensions_disabled:
        return []
    added: list[str] = []
    for folder in folders if folders is not None else beside_folders():
        try:
            names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".zip"))
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            try:
                checked = check_package(path, accepted=accepted)
            except ExtensionError:
                continue
            mid = checked.manifest.id
            if not policy.extension_allowed(pol, mid) or mid in added:
                continue
            have = added_manifest(mid, root)
            same = have is not None and have.id == mid and have.version == checked.manifest.version
            if same and have.helper == checked.manifest.helper:
                continue
            try:
                add_package(checked, root=root)
            except (OSError, ExtensionError):
                continue
            added.append(mid)
    return added


ENGINE_OFF = "The CAD Bridge is switched off in Tools > Extensions."


def solidworks_bridge(
    state: ExtensionState | None = None, *, pol: policy.Policy | None = None, root: str | None = None
) -> tuple[str | None, str | None]:
    """Where the bridge program the app may use is, and why there is none when there is
    not: (path, None) or (None, reason). In order: ``SOLIDSEAS_SWBRIDGE`` (a developer's
    build); the CAD Bridge package when it is added (only while it is on); a
    bridge beside the viewer or in a source checkout's ``dist`` (the layout before the
    bridge became a package), unless an administrator switched extensions off."""
    from solidseas.swapi.bridge import ENV_BRIDGE, EXE_NAME, find_bridge

    pol = pol if pol is not None else policy.current()
    if os.environ.get(ENV_BRIDGE):
        return os.environ[ENV_BRIDGE], None
    if not policy.extension_allowed(pol, BRIDGE):
        return None, "Set by your administrator: the CAD Bridge is off."
    state = state if state is not None else read_state()
    added = _added(BRIDGE, root)
    if added is not None:
        if not is_on(BRIDGE, state, pol=pol, root=root):
            return None, ENGINE_OFF
        return os.path.join(added[0], EXE_NAME), None
    found = find_bridge()
    if found is not None and found.is_file():
        return str(found), None
    return None, (
        f"The CAD Bridge is not added: get its package and add it in Tools > Extensions "
        f"({EXE_NAME} was not found)."
    )


def remove_package(extension_id: str, *, root: str | None = None) -> bool:
    """Delete ``extension_id``'s own folder (and a folder of a former id of it), and only
    that; False when there is none."""
    mid = _known(extension_id).id
    base = root or extensions_root()
    removed = False
    for name in (mid, *former_ids(mid)):
        target = os.path.join(base, name)
        if os.path.islink(target):
            raise ExtensionError(f"{target} is a link; SolidSeas does not follow it.")
        if os.path.isdir(target):
            shutil.rmtree(target)
            removed = True
    return removed


__all__ = [
    "ACCEPTED",
    "BRIDGE",
    "CATALOG",
    "DEFAULT_ON",
    "MANIFEST",
    "RELEASES_URL",
    "SETTINGS",
    "CheckedPackage",
    "ExtensionError",
    "ExtensionState",
    "HelperRefused",
    "Manifest",
    "Status",
    "add_package",
    "added_manifest",
    "check_package",
    "current_id",
    "data_dir",
    "extensions_root",
    "former_ids",
    "installed_dir",
    "is_on",
    "manifest",
    "on_ids",
    "read_state",
    "remove_package",
    "setting",
    "solidworks_bridge",
    "add_beside",
    "beside_folders",
    "start_helper",
    "state_path",
    "statuses",
    "switched",
    "with_setting",
    "write_state",
]
