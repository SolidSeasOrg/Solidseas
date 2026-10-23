"""Finding a drawing's model (``docs/DRAWINGS.md`` 13.6).

A ``.ssdrw`` can arrive by email, so the paths in it are untrusted. The model is
looked for, in this order:

1. **The relative path** joined to the drawing's folder, only when it stays inside
   that folder: every component passes the checks of ``solidseas.resolve`` (no
   ``..``, no stream, no device name, no control character), no anchor, and the
   joined path lies within the folder. On this computer no folder on the way may be
   a link.
2. **The stored path**, only on a local drive: never a UNC path, never a mapped
   network drive, and on Windows only a drive path ``resolve`` accepts as a usable
   target. Outside Windows only an absolute path of this system is looked at.
3. **The catalog**, when one is given, by SHA-256 and then by name, inside its roots.

Each candidate carries the hash of the file found and whether it matches the
drawing's. A file whose hash differs is offered ("this file has changed since the
drawing was made"), never taken: :attr:`Lookup.found` is only ever a matching one.

Everything here is a pure function over paths: the hashing, the drive kind and the
catalog are callables a caller (or a test) gives, and a Windows path can be judged
on any system with ``windows=True``. The catalog is any callable
``catalog(kind, value)`` returning paths, where ``kind`` is ``"sha256"`` or
``"name"``; :func:`catalog_lookup` adapts a mapping for tests and scripts.

:func:`model_reference` and :func:`with_model_path` write the other way: the
relative path when the model is in the drawing's folder or below it, else the
absolute path; :func:`for_sending` drops the absolute path, as Save a Copy to Send
does.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..errors import InvalidArgumentError
from ..resolve import names
from . import document, types

CHANGED = "this file has changed since the drawing was made"
MATCHES = "this is the file the drawing was made from"
MAX_CANDIDATES = 32  # catalog answers looked at, per kind
MAX_PATH = 1024
DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_RAMDISK = 2, 3, 4, 6
LOCAL_DRIVES = (DRIVE_FIXED, DRIVE_REMOVABLE, DRIVE_RAMDISK)


@dataclass(frozen=True)
class Candidate:
    """A file that may be the model: its path, how it was found (``relative``,
    ``stored``, ``catalog``), its SHA-256 (None when it could not be read), whether that
    matches the drawing's, and the words to show."""

    path: str
    how: str
    sha256: str | None
    matches: bool
    note: str


@dataclass(frozen=True)
class Lookup:
    """Every candidate in the order looked at, and each path not looked at with why."""

    candidates: tuple[Candidate, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def found(self) -> Candidate | None:
        """The first candidate whose hash matches the drawing's; never a changed one."""
        for c in self.candidates:
            if c.matches:
                return c
        return None

    @property
    def changed(self) -> tuple[Candidate, ...]:
        """Candidates that are there but changed: offered to the user, never taken."""
        return tuple(c for c in self.candidates if c.sha256 is not None and not c.matches)


def _windows_drive_type(root: str) -> int:
    return document._windows_drive_type(root)


def _parts(text: str) -> list[str] | None:
    """The components of a relative path, or None when it is not one that may be used."""
    if not text or len(text) > MAX_PATH or "\x00" in text:
        return None
    t = text.replace("\\", "/")
    if t.startswith("/") or re.match(r"[A-Za-z]:", t):
        return None
    parts = t.split("/")
    for p in parts:
        if names.component_problem(p) is not None:
            return None
    return parts


def _inside(path: str, folder: str, mod) -> bool:
    p = mod.normcase(mod.normpath(path))
    f = mod.normcase(mod.normpath(folder))
    try:
        return mod.commonpath([p, f]) == f
    except ValueError:
        return False


LINK_ON_STORED_PATH = "a folder on the stored path is a link, which SolidSeas never follows"


def _no_links(folder: str, parts: list[str]) -> bool:
    """Whether no folder from ``folder`` down to the file's folder is a link."""
    import stat

    path = folder
    for p in parts[:-1]:
        path = os.path.join(path, p)
        try:
            st = os.lstat(path)
        except OSError:
            return False
        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
        if stat.S_ISLNK(st.st_mode) or attrs & 0x400:
            return False
    return True


def _through_link(anchor: str, parts: list[str]) -> bool:
    """Whether a folder on the way from ``anchor`` down to the file's folder is a link or a
    junction, each one looked at with ``lstat`` before the next is used (a folder that is
    not there stops the walk: nothing through it can be found either)."""
    import stat

    path = anchor
    for p in parts[:-1]:
        path = os.path.join(path, p)
        try:
            st = os.lstat(path)
        except OSError:
            return False
        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
        if stat.S_ISLNK(st.st_mode) or attrs & 0x400:
            return True
    return False


def catalog_lookup(by_sha256: Mapping[str, Iterable[str]], by_name: Mapping[str, Iterable[str]]):
    """A catalog callable from two mappings: SHA-256 to paths, and name (compared as NTFS
    compares names) to paths."""
    folded = {names.fold(k): tuple(v) for k, v in by_name.items()}

    def lookup(kind: str, value: str) -> Iterable[str]:
        if kind == "sha256":
            return tuple(by_sha256.get(value, ()))
        if kind == "name":
            return folded.get(names.fold(value), ())
        return ()

    return lookup


def find_model(
    drawing_path: str | os.PathLike,
    model: Mapping[str, Any],
    *,
    catalog: Callable[[str, str], Iterable[str]] | None = None,
    windows: bool | None = None,
    drive_type: Callable[[str], int] | None = None,
    file_hash: Callable[[str], str | None] | None = None,
    limit: int = MAX_CANDIDATES,
) -> Lookup:
    """Where the model of the drawing at ``drawing_path`` may be (13.6), from its
    ``model`` member: the candidates in order and the paths not looked at. ``windows``
    judges paths by Windows' rules (the host's by default); ``drive_type`` gives a
    drive root's kind (GetDriveTypeW's numbers); ``file_hash`` gives a file's SHA-256 or
    None (by default a plain file, never through a link, is read)."""
    if not isinstance(model, Mapping):
        raise InvalidArgumentError("model must be the drawing's model member", detail={"parameter": "model"})
    host_windows = os.name == "nt"
    windows = host_windows if windows is None else bool(windows)
    simulated = windows != host_windows
    mod = ntpath if windows else posixpath
    real_fs = file_hash is None and not simulated
    if file_hash is None:

        def file_hash(path: str) -> str | None:
            return document.file_sha256(path)

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise InvalidArgumentError("limit must be 1 to 1,000", detail={"parameter": "limit"})
    want = model.get("sha256")
    want = want if isinstance(want, str) else None
    drawing_path = os.fspath(drawing_path)
    folder = mod.dirname(mod.normpath(drawing_path) if simulated else os.path.abspath(drawing_path))
    candidates: list[Candidate] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()

    def offer(path: str, how: str) -> None:
        key = mod.normcase(mod.normpath(path))
        if key in seen:
            return
        seen.add(key)
        h = file_hash(path)
        if h is None:
            return
        ok = want is not None and h == want
        candidates.append(Candidate(path, how, h, ok, MATCHES if ok else CHANGED))

    # 1. The relative path, kept within the drawing's folder.
    relative = model.get("relative")
    if isinstance(relative, str) and relative:
        parts = _parts(relative)
        if parts is None:
            skipped.append(
                ("relative", "the relative path leaves the drawing's folder or is not a plain path")
            )
        else:
            path = mod.join(folder, *parts)
            if not _inside(path, folder, mod):
                skipped.append(("relative", "the relative path leaves the drawing's folder"))
            elif real_fs and not _no_links(folder, parts):
                skipped.append(
                    ("relative", "a folder on the relative path is a link, which SolidSeas never follows")
                )
            else:
                offer(path, "relative")

    # 2. The stored path, only on a local drive.
    stored = model.get("stored")
    if isinstance(stored, str) and stored:
        why = None
        path = None
        if windows:
            sp = names.parse_stored(stored)
            if sp.kind == "unc":
                why = "the stored path is on a network share (a UNC path), which SolidSeas never looks at"
            elif sp.kind != "drive" or not sp.usable:
                why = f"the stored path is not one SolidSeas looks at ({sp.problem or sp.kind})"
            else:
                kind = (drive_type or _windows_drive_type)(sp.anchor + "\\")
                if kind == DRIVE_REMOTE:
                    why = "the stored path is on a mapped network drive, which SolidSeas never looks at"
                elif kind not in LOCAL_DRIVES:
                    why = "the stored path is not on a drive of this computer"
                elif real_fs and _through_link(sp.anchor + "\\", [*sp.folder, sp.name]):
                    why = LINK_ON_STORED_PATH
                else:
                    path = sp.anchor + "\\" + "\\".join((*sp.folder, sp.name))
        else:
            if not posixpath.isabs(stored) or "\\" in stored or len(stored) > MAX_PATH or "\x00" in stored:
                why = "the stored path is not a path of this computer"
            else:
                comps = [c for c in stored.split("/") if c]
                if not comps or any(names.component_problem(c) is not None for c in comps):
                    why = "the stored path is not one SolidSeas looks at"
                elif real_fs and _through_link("/", comps):
                    why = LINK_ON_STORED_PATH
                else:
                    path = "/" + "/".join(comps)
        if why is not None:
            skipped.append(("stored", why))
        elif path is not None:
            offer(path, "stored")

    # 3. The catalog, by hash and then by name.
    if catalog is not None:
        asks: list[tuple[str, str]] = []
        if want is not None:
            asks.append(("sha256", want))
        name = model.get("name")
        if isinstance(name, str) and names.name_problem(name) is None:
            asks.append(("name", name))
        for kind, value in asks:
            found = catalog(kind, value) or ()
            for k, path in enumerate(found):
                if k >= limit:
                    break
                if isinstance(path, str) and path and len(path) <= MAX_PATH and "\x00" not in path:
                    offer(path, "catalog")
    return Lookup(tuple(candidates), tuple(skipped))


def model_reference(
    model_path: str | os.PathLike, drawing_path: str | os.PathLike, *, windows: bool | None = None
) -> dict[str, str | None]:
    """The ``relative`` and ``stored`` members for a model at ``model_path`` and a drawing
    at ``drawing_path``: the path relative to the drawing's folder when the model is in
    it or below it (with ``/`` between folders), else the absolute path."""
    host_windows = os.name == "nt"
    windows = host_windows if windows is None else bool(windows)
    mod = ntpath if windows else posixpath
    simulated = windows != host_windows
    m = os.fspath(model_path)
    d = os.fspath(drawing_path)
    if not simulated:
        m, d = os.path.abspath(m), os.path.abspath(d)
    m, folder = mod.normpath(m), mod.dirname(mod.normpath(d))
    if _inside(m, folder, mod) and mod.normcase(m) != mod.normcase(folder):
        rel = mod.relpath(m, folder) if not simulated else m[len(folder) :].lstrip("\\/")
        return {"relative": rel.replace("\\", "/"), "stored": None}
    return {"relative": None, "stored": m}


def with_model_path(
    drawing: types.Drawing,
    model_path: str | os.PathLike,
    drawing_path: str | os.PathLike,
    *,
    windows: bool | None = None,
) -> types.Drawing:
    """``drawing`` whose model member names the model at ``model_path`` as seen from a
    drawing saved at ``drawing_path`` (the name kept, the paths set)."""
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    model = dict(drawing.model or {})
    model.update(model_reference(model_path, drawing_path, windows=windows))
    return replace(drawing, model=model)


def for_sending(drawing: types.Drawing) -> types.Drawing:
    """``drawing`` without the model's absolute path: Save a Copy to Send never carries
    it (13.1, 18)."""
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    model = dict(drawing.model or {})
    model["stored"] = None
    return replace(drawing, model=model)


__all__ = [
    "CHANGED",
    "MATCHES",
    "Candidate",
    "Lookup",
    "catalog_lookup",
    "find_model",
    "for_sending",
    "model_reference",
    "with_model_path",
]
