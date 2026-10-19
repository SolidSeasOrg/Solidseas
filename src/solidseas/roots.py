"""Roots: the folders SolidSeas may search or serve (``docs/API.md`` C5 and C6).

One type serves reference resolution today and the folder listing and the REST
service later. A root has an ``id`` (``[a-z0-9_-]{1,32}``), an absolute
``path``, ``recursive`` and a ``role``: ``project`` or ``library``. Roots are
searched in the order given.

A root is configuration chosen by whoever runs SolidSeas, not content from a
file, so a root that is a junction, a symbolic link or a UNC share is accepted
(C6). Refused, with :class:`~solidseas.errors.PathRefusedError` and
``detail["rule"]``:

* ``device_path``: ``\\\\?\\`` and ``\\\\.\\`` paths;
* ``webdav``: a share whose host carries ``@`` (``\\\\host@SSL\\share``) or whose
  share is ``DavWWWRoot``, which Windows reaches over HTTP with the user's
  credentials;
* ``not_absolute``: a relative path, a drive-relative ``C:folder`` or a path
  rooted on the current drive (``\\folder``).

Constructing a root checks the text only. Whether the folder exists is found
out when something first walks it.
"""

import ntpath
import os
import posixpath
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .errors import InvalidArgumentError, PathRefusedError

ROOT_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")
ROLES = ("project", "library")
MAX_ROOT_PATH = 4096


def _refuse(path: str, rule: str, why: str) -> PathRefusedError:
    return PathRefusedError(f"root {path!r} refused: {why}", detail={"rule": rule})


def check_root_path(path: str | os.PathLike) -> str:
    """The root folder ``path`` normalised (text only), or :class:`PathRefusedError`."""
    text = os.fspath(path)
    if not isinstance(text, str) or not text or len(text) > MAX_ROOT_PATH or "\x00" in text:
        raise InvalidArgumentError("a root is a folder path", detail={"parameter": "root"})
    slashed = text.replace("/", "\\")
    if slashed.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        raise _refuse(text, "device_path", "device and long-path prefixes are not accepted")
    if slashed.startswith("\\\\"):
        parts = slashed[2:].split("\\")
        host = parts[0]
        share = parts[1] if len(parts) > 1 else ""
        if "@" in host or share.casefold() == "davwwwroot":
            raise _refuse(text, "webdav", "a WebDAV share is reached over HTTP with your credentials")
        if not host or not share:
            raise _refuse(text, "not_absolute", "a share is \\\\host\\share")
    if os.name == "nt":
        drive, rest = ntpath.splitdrive(text)
        if not drive or not (drive.startswith("\\\\") or rest[:1] in ("\\", "/")):
            raise _refuse(text, "not_absolute", "a root is an absolute folder path")
        return ntpath.normpath(text)
    if not posixpath.isabs(text):
        raise _refuse(text, "not_absolute", "a root is an absolute folder path")
    return posixpath.normpath(text)


@dataclass(frozen=True)
class Root:
    """One root folder. ``path`` is normalised absolute text."""

    id: str
    path: str
    recursive: bool = True
    role: str = "project"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not ROOT_ID.match(self.id):
            raise InvalidArgumentError(
                f"a root id matches [a-z0-9_-]{{1,32}}, not {self.id!r}", detail={"parameter": "root"}
            )
        if self.role not in ROLES:
            raise InvalidArgumentError(
                f"a root's role is project or library, not {self.role!r}", detail={"parameter": "role"}
            )
        if not isinstance(self.recursive, bool):
            raise InvalidArgumentError("recursive is true or false", detail={"parameter": "recursive"})
        object.__setattr__(self, "path", check_root_path(self.path))


class Roots:
    """An ordered set of :class:`Root` with unique ids."""

    def __init__(self, roots: "Iterable[Root] | Roots" = ()) -> None:
        items = list(roots)
        seen: set[str] = set()
        for r in items:
            if not isinstance(r, Root):
                raise InvalidArgumentError("Roots holds Root objects", detail={"parameter": "root"})
            if r.id in seen:
                raise InvalidArgumentError(f"two roots have the id {r.id!r}", detail={"parameter": "root"})
            seen.add(r.id)
        self._roots = tuple(items)

    @classmethod
    def from_mapping(
        cls, mapping: Mapping[str, str | os.PathLike], *, role: str = "project", recursive: bool = True
    ) -> "Roots":
        """``{id: folder}``, every root with the same role, in mapping order."""
        return cls(Root(k, os.fspath(v), recursive, role) for k, v in mapping.items())

    def ids(self) -> list[str]:
        return [r.id for r in self._roots]

    def __getitem__(self, root_id: str) -> Root:
        for r in self._roots:
            if r.id == root_id:
                return r
        raise KeyError(root_id)

    def __iter__(self) -> Iterator[Root]:
        return iter(self._roots)

    def __len__(self) -> int:
        return len(self._roots)

    def __bool__(self) -> bool:
        return bool(self._roots)

    def __repr__(self) -> str:
        return f"Roots({list(self._roots)!r})"


__all__ = ["ROLES", "ROOT_ID", "Root", "Roots", "check_root_path"]
