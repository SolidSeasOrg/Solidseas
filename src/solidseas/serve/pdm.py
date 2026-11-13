"""The service's PDM routes (provisional, ``docs/API.md`` 8.6 and 5.21): a library's
status, a file's history and one of its versions, the recent check-ins and a
project's self-contained check, read from the vault (:mod:`solidseas.pdm`) in a
worker process.

The functions here run in the worker (:mod:`solidseas.jobs` calls them after its
``within`` check), so the server process never reads the vault or a CAD file. Each
opens the library that holds the requested path, which may be the root, a folder
above it or a folder inside it, and answers with every path relative to the root:

* the library's own folder is given relative to the root, or null when it lies above
  the root;
* a file of the vault outside the root (another project of a library above it) is
  left out, and so is a check-in that names no file below the requested folder;
* a warning whose text names a folder on this machine has that text replaced;
* a file the self-contained check finds is given as a root id and a path when it lies
  in one of the service's roots, and as null (``outside_roots``) when it does not.

Nothing here writes: the vault is only read, and :func:`solidseas.pdm.check.check_project`
opens every document read-only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..errors import InvalidArgumentError, PathRefusedError
from ..formats.solidworks._io import relative_parts
from .query import ServiceError

ACTIONS = ("status", "log", "version", "checkins", "check")
MAX_CHECKIN_FILES = 100  # the files one check-in lists in an answer; files_total counts them all
WITHHELD = "The text of this warning names a folder on the server, so it is not sent."
# An absolute path in a warning's text: /..., C:\... or \\server\..., at the start of a word.
_ABSOLUTE = re.compile(r"(?:^|[\s'\"(=])(?:/[^\s/]|[A-Za-z]:[\\/]|\\\\)")


def not_a_library() -> ServiceError:
    return ServiceError(
        "not_a_library",
        "the folder is not inside a PDM library: make one with solidseas pdm init",
        detail={"rule": "not_a_library"},
    )


def _below(path: str, folder: str) -> list[str] | None:
    """The components of ``path`` below ``folder`` (empty for the folder itself), or None
    when it is not inside it."""
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(folder)):
        return []
    try:
        return relative_parts(path, folder)
    except PathRefusedError:
        return None


class _Scope:
    """An opened library seen from a root: maps the library's paths to the root's."""

    def __init__(self, vault, within: str) -> None:
        from ..pdm.vault import _folded

        self.vault = vault
        self.within = os.path.abspath(within)
        self._fold = _folded
        above = _below(self.within, vault.root)
        if above is not None:  # the library is the root or a folder above it
            self.root_in_lib: list[str] | None = above
            self.lib_in_root: list[str] | None = None
        else:  # the library is a folder inside the root
            self.root_in_lib = None
            self.lib_in_root = _below(vault.root, self.within)
            if self.lib_in_root is None:  # a library found from a path in the root holds it or lies in it
                raise PathRefusedError(
                    "the library is not where the path is", detail={"rule": "escapes_root"}
                )

    @property
    def library(self) -> str | None:
        """The library folder relative to the root, or None when it lies above the root."""
        if self.lib_in_root is not None:
            return "/".join(self.lib_in_root)
        return "" if not self.root_in_lib else None

    def to_root(self, rel: str) -> str | None:
        """A ``/``-separated path below the library as a path below the root; None for one
        outside the root."""
        parts = rel.split("/") if rel else []
        if self.lib_in_root is not None:
            return "/".join([*self.lib_in_root, *parts])
        n = len(self.root_in_lib or ())
        if n == 0:
            return rel
        if len(parts) < n or self._fold("/".join(parts[:n])) != self._fold("/".join(self.root_in_lib or ())):
            return None
        return "/".join(parts[n:])

    def path_in_root(self, path: str | os.PathLike) -> str | None:
        parts = _below(os.fspath(path), self.within)
        return None if parts is None else "/".join(parts)

    def warnings(self, warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The warnings, with any text that names a folder on this machine replaced."""
        hidden = [h.casefold() for h in (self.vault.root, self.within) if h]
        out = []
        for w in warnings:
            message = str(w.get("message") or "")
            low = message.casefold()
            if any(h in low for h in hidden) or _ABSOLUTE.search(message):
                message = WITHHELD
            out.append({"code": w.get("code"), "stream": w.get("stream"), "message": message})
        return out


def _open(params: dict[str, Any]):
    """The vault holding the request's path, the scope and the path (on this machine)."""
    from .. import pdm

    within = params["within"]
    host = params["path"]
    if not isinstance(host, str) or _below(host, within) is None:
        raise PathRefusedError("the path is not inside the root", detail={"rule": "outside_roots"})
    if pdm.find_library(host) is None:
        raise not_a_library()
    vault = pdm.open_vault(host)
    return vault, _Scope(vault, within), host


def status(params: dict[str, Any]) -> dict[str, Any]:
    vault, scope, host = _open(params)
    st = vault.status(host, unchanged=bool(params.get("unchanged")))
    files = []
    for f in st.files:
        row = f.data()
        rel = scope.to_root(row["path"])
        if rel is not None:
            files.append({**row, "path": rel})
    skipped = []
    for s in st.skipped:
        rel = scope.to_root(s["path"])
        if rel is not None:
            skipped.append({"path": rel, "reason": s["reason"]})
    return {
        "library": scope.library,
        "scope": scope.to_root(st.scope) or "",
        "counts": dict(st.counts),
        "hashed": st.hashed,
        "files": files,
        "skipped": skipped,
    }


def log(params: dict[str, Any]) -> dict[str, Any]:
    vault, scope, host = _open(params)
    data = vault.log(host)
    git = data["git"]
    return {
        "library": scope.library,
        "path": scope.to_root(data["path"]) or "",
        "name": data["file"]["name"],
        "working": data["working"],
        "git": None if git is None else {"branch": git.get("branch"), "head": git.get("head")},
        "versions": data["versions"],
        "warnings": scope.warnings(data["warnings"]),
    }


def version(params: dict[str, Any]) -> dict[str, Any]:
    vault, scope, host = _open(params)
    data = vault.show(host, params["version"], source=params.get("source") or "vault")
    out = {
        "library": scope.library,
        "path": scope.path_in_root(host) or "",
        "name": data["file"]["name"],
    }
    out.update({k: v for k, v in data.items() if k != "file"})
    out["source"] = "vault" if data["source"] == "snapshots" else data["source"]  # as the request names it
    out["warnings"] = scope.warnings(data["warnings"])
    return out


def checkins(params: dict[str, Any]) -> dict[str, Any]:
    """The check-ins that name a file below the folder, newest first, ``limit`` of them
    after the one ``after`` names (its stamp and id, from the previous page)."""
    vault, scope, host = _open(params)
    limit = int(params.get("limit") or 50)
    after = params.get("after")
    scans = bool(params.get("scans"))
    prefix = vault.relative(host)
    fold = scope._fold
    folded_prefix = fold(prefix + "/") if prefix else ""
    page: list[dict[str, Any]] = []
    more = False
    last = None
    for c in reversed(vault.checkins()):
        if c.auto and not scans:
            continue
        key = f"{c.stamp()}-{c.id}"
        if after is not None and key >= after:
            continue
        rows = []
        for f in c.files:
            if folded_prefix and not fold(f.path).startswith(folded_prefix):
                continue
            rel = scope.to_root(f.path)
            if rel is None:
                continue
            rows.append(
                {
                    "path": rel,
                    "sha256": f.sha256,
                    "size": f.size,
                    "version": f.snapshot,
                    "new": f.new,
                    "removed": f.removed,
                }
            )
        if not rows:
            continue
        if len(page) == limit:
            more = True
            break
        page.append(
            {
                **c.brief(),
                "files_total": len(rows),
                "files_truncated": len(rows) > MAX_CHECKIN_FILES,
                "files": rows[:MAX_CHECKIN_FILES],
            }
        )
        last = key
    return {
        "library": scope.library,
        "scope": scope.path_in_root(host) or "",
        "scans": scans,
        "checkins": page,
        "next_after": last if more else None,
    }


def check(params: dict[str, Any]) -> dict[str, Any]:
    """The self-contained check of the project that holds the folder (``docs/PDM.md`` 5)."""
    from ..pdm.check import check_project

    vault, scope, host = _open(params)
    project = vault.project_of(host)
    if project is None:
        raise InvalidArgumentError(
            "the folder is not a project of the library, nor inside one",
            detail={"rule": "not_a_project", "parameter": "path"},
        )
    project_rel = scope.to_root(project.path)
    if project_rel is None:  # the root lies inside the project: checking it would read outside the root
        raise PathRefusedError(
            "the project holds the root, so it is not checked from it",
            detail={"rule": "project_outside_root"},
        )
    library = None
    for sec in vault.sections():
        if sec.kind == "library":
            folder = vault.absolute(sec.folder)
            if os.path.isdir(folder):
                library = Path(folder)
    copy_toolbox = bool(params.get("copy_toolbox"))
    result = check_project(Path(vault.absolute(project.path)), library=library, copy_toolbox=copy_toolbox)
    roots = [r for r in params.get("roots") or () if isinstance(r, dict)]

    def place(path) -> dict[str, str] | None:
        if path is None:
            return None
        for r in roots:
            parts = _below(os.fspath(path), r["path"])
            if parts is None or (not r.get("recursive", True) and len(parts) > 1):
                continue
            return {"root": r["id"], "path": "/".join(parts)}
        return None

    problems = {id(f) for f in result.problems()}
    findings = []
    for f in result.findings:
        found = place(f.found)
        findings.append(
            {
                "document": scope.path_in_root(f.document) or "",
                "key": f.key,
                "stored_path": f.stored_path,
                "file_name": f.file_name,
                "relation": f.relation,
                "result": f.result,
                "problem": id(f) in problems,
                "found": found,
                "found_in": place(f.found_in),
                "outside_roots": f.found is not None and found is None,
                "place": f.place,
                "status": f.status,
                "rule": f.rule,
                "identity": f.identity,
                "searched": f.searched,
                "toolbox": f.toolbox,
                "warnings": list(f.warnings),
            }
        )
    return {
        "library": scope.library,
        "project": {
            "path": project_rel,
            "name": project.name,
            "section": project.section,
            "archived": project.archived,
        },
        "copy_toolbox": copy_toolbox,
        "documents": result.documents,
        "self_contained": result.self_contained,
        "problems": len(problems),
        "counts": result.counts(),
        "findings": findings,
        "unreadable": [
            {"path": scope.path_in_root(p) or "", "exception": name} for p, name in result.unreadable
        ],
    }


def run(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Run one of :data:`ACTIONS` (the worker job ``pdm_<action>``)."""
    if action not in ACTIONS:
        raise InvalidArgumentError("not a PDM route", detail={"parameter": "action"})
    return globals()[action](params)


__all__ = ["ACTIONS", "MAX_CHECKIN_FILES", "not_a_library", "run"]
