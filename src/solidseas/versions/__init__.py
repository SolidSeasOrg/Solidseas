"""A file's versions and what changed between them (provisional, ``docs/VERSIONS.md``,
``docs/API.md`` 3.26).

Inside a Git repository a file's history comes from Git (:mod:`.gitrepo`, read in pure
Python: no program runs and nothing is fetched); anywhere else from SolidSeas' own
snapshots (:mod:`.snapstore`), which are taken only when asked. Either way the history
lists the versions newest first, with the working copy on top when it differs from the
newest one, and any two versions can be compared (:mod:`.versiondiff`): document,
properties, configurations and geometry.

```python
from solidseas import versions

h = versions.history("D:/Jobs/Example/bracket.SLDPRT")      # file_history data
s = versions.snapshot("D:/Jobs/Example/bracket.SLDPRT")     # snapshot_taken data
d = versions.compare("D:/Jobs/Example/bracket.SLDPRT")      # version_diff: the two newest versions
d = versions.compare("D:/Jobs/Example/bracket.SLDPRT", "v2", "working")
```

A version is named by ``working`` (the file as it is now), ``latest`` (the newest
stored version), ``vN`` (its number in the history, 1 the oldest) or its id: a commit
id or a snapshot id, or at least four leading hex digits of one that no other version
shares.

Nothing here writes beside a source document: a snapshot is written to the user's data
folder, or to a project's ``.solidseas/history`` only when the project is named, never
through a link. Every source file is opened read-only.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import (
    BusyError,
    FileTooLargeError,
    InvalidArgumentError,
    VersionNotFoundError,
    VersionUnavailableError,
)
from ..formats.solidworks._io import open_readonly, relative_parts
from ..formats.solidworks.container import MAX_IN_MEMORY_BYTES
from . import gitrepo, snapstore
from .gitrepo import DEFAULT_MAX_COMMITS
from .snapstore import data_dir, open_store
from .versiondiff import DEFAULT_MAX_SECONDS, Side, compare_sides

SOURCES = ("auto", "git", "snapshots")
DEFAULT_MAX_VERSION_BYTES = MAX_IN_MEMORY_BYTES  # a version is read whole to be compared
_VERSION_NUMBER = re.compile(r"v([1-9][0-9]{0,8})\Z")
_ID_PREFIX = re.compile(r"[0-9a-f]{4,64}\Z")
_CHUNK = 1 << 20


# --------------------------------------------------------------------------- one version
@dataclass
class Version:
    """One entry of a file's history (see ``docs/API.md`` 5.19 for the fields)."""

    number: int
    id: str
    kind: str  # commit, snapshot or working
    status: str | None = None  # added, modified or deleted (commits)
    time: datetime.datetime | None = None
    authored: datetime.datetime | None = None
    author: str | None = None
    subject: str | None = None
    size: int | None = None
    sha256: str | None = None
    git_blob: str | None = None
    lfs: gitrepo.LfsPointer | None = None
    available: bool = True
    snapshot: snapstore.Snapshot | None = field(default=None, repr=False)

    @property
    def has_content(self) -> bool:
        return self.status != "deleted"

    def data(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "time_utc": _iso(self.time),
            "authored_utc": _iso(self.authored),
            "author": self.author,
            "subject": self.subject,
            "size": self.size,
            "sha256": self.sha256,
            "git_blob": self.git_blob,
            "lfs": None if self.lfs is None else {"oid": self.lfs.oid, "size": self.lfs.size},
            "available": self.available,
        }


def _iso(when: datetime.datetime | None) -> str | None:
    if when is None:
        return None
    return when.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_unix(seconds: int | None) -> datetime.datetime | None:
    if seconds is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- the working copy
@dataclass
class _Working:
    exists: bool
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None
    blob: str | None = None
    state: str = "missing"

    def data(self) -> dict[str, Any]:
        from ..model import file_object

        f = file_object(None, self.size, self.mtime_ns)
        return {
            "state": self.state,
            "size": f["size"],
            "modified_utc": f["modified_utc"],
            "mtime_ns": f["mtime_ns"],
            "sha256": self.sha256,
        }


def _hash_file(path: str, within: str, object_format: str | None, max_file_bytes: int | None) -> _Working:
    """The file at ``path`` read once (read-only, no link below ``within`` followed): its
    size, modification time, SHA-256 and, with ``object_format``, its Git blob id."""
    for _attempt in range(3):
        with open_readonly(path, within=within) as fh:
            before = os.fstat(fh.fileno())
            if max_file_bytes is not None and before.st_size > max_file_bytes:
                raise FileTooLargeError(
                    "the file is larger than the configured maximum",
                    detail={"limit": max_file_bytes, "value": before.st_size},
                )
            sha = hashlib.sha256()
            blob = gitrepo.blob_hasher(before.st_size, object_format) if object_format else None
            n = 0
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                sha.update(chunk)
                if blob is not None:
                    blob.update(chunk)
                n += len(chunk)
            after = os.fstat(fh.fileno())
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and n == before.st_size:
            return _Working(
                True, n, after.st_mtime_ns, sha.hexdigest(), blob.hexdigest() if blob is not None else None
            )
    raise BusyError(
        "the file kept changing while it was read: try again once it is saved",
        detail={"rule": "file_changing"},
    )


def _read_working(path: str, within: str, limit: int) -> bytes:
    for _attempt in range(3):
        with open_readonly(path, within=within) as fh:
            before = os.fstat(fh.fileno())
            if before.st_size > limit:
                raise FileTooLargeError(
                    "the file is larger than the configured maximum",
                    detail={"limit": limit, "value": before.st_size},
                )
            data = fh.read(before.st_size + 1)
            after = os.fstat(fh.fileno())
        unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        if unchanged and len(data) == before.st_size:
            return data
    raise BusyError(
        "the file kept changing while it was read: try again once it is saved",
        detail={"rule": "file_changing"},
    )


# --------------------------------------------------------------------------- a timeline
@dataclass
class Timeline:
    """A file's history as :func:`timeline` builds it: the versions newest first, the
    working copy's state, and what the history came from. :meth:`read` returns a
    version's content; :meth:`find` picks a version by name. Close it (or use it as a
    context manager) to release the repository's files."""

    path: str
    source: str
    versions: list[Version]
    working: _Working
    within: str = ""  # the folder below which the working copy is read with no link followed
    repository: gitrepo.Repository | None = None
    git: dict[str, Any] | None = None
    store: snapstore.SnapshotStore | None = None
    truncated: bool = False
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def __enter__(self) -> Timeline:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.repository is not None:
            self.repository.close()

    @property
    def stored(self) -> list[Version]:
        return [v for v in self.versions if v.kind != "working"]

    def data(self) -> dict[str, Any]:
        """``file_history`` data."""
        return {
            "file": _file_data(self.path),
            "source": self.source,
            "git": self.git,
            "store": None
            if self.store is None
            else {"location": self.store.location, "path": self.store.root},
            "working": self.working.data(),
            "versions": [v.data() for v in self.versions],
            "truncated": self.truncated,
            "warnings": list(self.warnings),
        }

    def find(self, name: str, *, parameter: str = "version") -> Version:
        """The version ``name`` names (see the module notes)."""
        if not isinstance(name, str):
            raise InvalidArgumentError("a version is named by text", detail={"parameter": parameter})
        text = name.strip()
        if text == "working":
            if not self.working.exists:
                raise VersionNotFoundError("the file does not exist now", detail={"parameter": parameter})
            for v in self.versions:
                if v.kind == "working":
                    return v
            latest = self._latest()
            if latest is not None:  # unchanged: the working copy is the newest version
                return latest
            raise VersionNotFoundError("the file has no working copy", detail={"parameter": parameter})
        if text == "latest":
            latest = self._latest()
            if latest is None:
                raise VersionNotFoundError(
                    "the file has no stored version yet", detail={"parameter": parameter}
                )
            return latest
        m = _VERSION_NUMBER.match(text)
        if m:
            n = int(m.group(1))
            for v in self.versions:
                if v.number == n:
                    return v
            raise VersionNotFoundError(f"the file has no version {text}", detail={"parameter": parameter})
        lowered = text.lower()
        if _ID_PREFIX.match(lowered):
            hits = [v for v in self.stored if v.id.startswith(lowered)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise VersionNotFoundError(
                    f"{text} starts the ids of {len(hits)} versions: give more of it",
                    detail={"parameter": parameter},
                )
        raise VersionNotFoundError(
            f"no version of the file is named {text!r}: use working, latest, vN or an id",
            detail={"parameter": parameter},
        )

    def _latest(self) -> Version | None:
        for v in self.stored:
            if v.has_content:
                return v
        return None

    def pair(self, older: str | None, newer: str | None) -> tuple[Version, Version]:
        """The two versions :func:`compare` compares (see its notes)."""
        contentful = [v for v in self.versions if v.has_content]
        b = self.find(newer, parameter="newer") if newer is not None else None
        a = self.find(older, parameter="older") if older is not None else None
        if b is None:
            if a is not None:
                b = contentful[0] if contentful else None
            elif len(contentful) >= 2:
                b = contentful[0]
        if a is None and b is not None:
            earlier = [v for v in contentful if v.number < b.number]
            a = earlier[0] if earlier else None
            if a is None and newer is not None:
                raise VersionNotFoundError(
                    f"no version of the file comes before v{b.number}: there is nothing to compare it with",
                    detail={"parameter": "older"},
                )
        if a is None or b is None:
            raise VersionNotFoundError(
                "the file has fewer than two versions: there is nothing to compare",
                detail={"parameter": "older"},
            )
        return a, b

    def read(self, v: Version, *, limit: int = DEFAULT_MAX_VERSION_BYTES) -> bytes:
        """The content of ``v``, read whole (at most ``limit`` bytes)."""
        if v.kind == "working":
            return _read_working(self.path, self.within or os.path.dirname(self.path), limit)
        if v.kind == "snapshot":
            return self.store.read(v.snapshot, limit=limit)
        if not v.has_content:
            raise VersionUnavailableError(
                "that commit deleted the file: it has no content", detail={"rule": "deleted"}
            )
        repo = self.repository
        if v.lfs is not None:
            path = repo.lfs_object(v.lfs)
            if path is None:
                raise VersionUnavailableError(
                    "that version is stored with Git LFS and its content is not on this machine: fetch it "
                    "with git lfs fetch, then try again",
                    detail={"rule": "lfs_object_missing"},
                )
            if v.lfs.size > limit:
                raise FileTooLargeError(
                    "a version of the file is larger than the configured maximum",
                    detail={"limit": limit, "value": v.lfs.size},
                )
            with open_readonly(path, within=repo.lfs_folder()) as fh:
                data = fh.read(v.lfs.size + 1)
            if len(data) != v.lfs.size or hashlib.sha256(data).hexdigest() != v.lfs.oid:
                raise gitrepo.GitObjectError("a Git LFS object does not match its pointer")
            return data
        return repo.read_blob(v.git_blob, limit=limit)


def _file_data(path: str) -> dict[str, Any]:
    return {"name": os.path.basename(path), "path": path}


def _check_source(source: str) -> str:
    if source not in SOURCES:
        raise InvalidArgumentError("source is auto, git or snapshots", detail={"parameter": "source"})
    return source


def _git_timeline(
    path: str, repo: gitrepo.Repository, max_commits: int, hashes: bool, limit: int
) -> Timeline:
    parts = tuple(relative_parts(path, repo.work_tree))
    branch, head = repo.head()
    hist = repo.file_history(parts, start=head, max_commits=max_commits) if head else gitrepo.History()
    stored: list[Version] = []
    missing_lfs = 0
    for k, fv in enumerate(reversed(hist.versions), 1):
        c = fv.commit
        v = Version(
            number=k,
            id=c.oid,
            kind="commit",
            status=fv.status,
            time=_from_unix(c.committed),
            authored=_from_unix(c.authored),
            author=c.author,
            subject=c.subject or None,
            size=fv.lfs.size if fv.lfs is not None else fv.size,
            sha256=fv.lfs.oid if fv.lfs is not None else None,
            git_blob=fv.blob,
            lfs=fv.lfs,
        )
        if fv.status == "deleted":
            v.available = False
        elif fv.lfs is not None:
            v.available = repo.lfs_object(fv.lfs) is not None
            missing_lfs += not v.available
        else:
            v.available = fv.size is not None
        stored.append(v)
    stored.reverse()
    timeline = Timeline(
        path,
        "git",
        stored,
        _Working(False),
        within=repo.work_tree,
        repository=repo,
        git={
            "work_tree": repo.work_tree,
            "path": "/".join(parts),
            "branch": branch[len("refs/heads/") :] if branch and branch.startswith("refs/heads/") else branch,
            "head": head,
            "object_format": repo.object_format,
            "shallow": bool(repo.shallow),
            "partial": repo.partial,
            "commits_walked": hist.walked,
        },
        truncated=hist.truncated,
    )
    if hashes:
        for v in stored:
            if v.sha256 is None and v.available and v.git_blob:
                v.sha256 = hashlib.sha256(repo.read_blob(v.git_blob, limit=limit)).hexdigest()
    if hist.incomplete:
        timeline.warnings.append(
            {
                "code": "history_incomplete",
                "stream": None,
                "message": "the repository is a shallow or partial clone: the history stops where its "
                "commits end",
            }
        )
    if missing_lfs:
        are = "version is" if missing_lfs == 1 else "versions are"
        timeline.warnings.append(
            {
                "code": "lfs_not_fetched",
                "stream": None,
                "message": f"{missing_lfs} {are} stored with Git LFS and not on this machine: git lfs fetch "
                "brings them",
            }
        )
    return timeline


def _snapshot_timeline(path: str, store: snapstore.SnapshotStore) -> Timeline:
    snaps = store.snapshots(path)
    versions = [
        Version(
            number=k,
            id=s.id,
            kind="snapshot",
            time=s.taken,
            subject=s.note,
            size=s.size,
            sha256=s.sha256,
            available=store.has_object(s.sha256, s.size),
            snapshot=s,
        )
        for k, s in enumerate(snaps, 1)
    ]
    versions.reverse()
    return Timeline(path, "snapshots", versions, _Working(False), within=os.path.dirname(path), store=store)


def _add_working(t: Timeline) -> None:
    """Hash the working copy (streamed, so no size limit is needed) and put it on top of
    the versions when it differs from the newest one."""
    try:
        w = _hash_file(t.path, t.within, t.repository.object_format if t.repository else None, None)
    except FileNotFoundError:
        if not t.versions:
            raise
        t.working = _Working(False, state="missing")
        return
    latest = t._latest()
    newest = t.stored[0] if t.stored else None
    if latest is None or newest is None or not newest.has_content:
        w.state = "new"
    elif latest.kind == "commit":
        # a work tree without git-lfs holds the pointer itself, whose blob is the commit's
        same = w.blob == latest.git_blob or (latest.lfs is not None and w.sha256 == latest.sha256)
        w.state = "unchanged" if same else "changed"
    else:
        w.state = "unchanged" if w.sha256 == latest.sha256 else "changed"
    t.working = w
    if w.state != "unchanged":
        when = datetime.datetime.fromtimestamp(w.mtime_ns / 1e9, datetime.UTC) if w.mtime_ns else None
        t.versions.insert(
            0,
            Version(
                number=len(t.stored) + 1,
                id="working",
                kind="working",
                time=when,
                size=w.size,
                sha256=w.sha256,
            ),
        )


def timeline(
    path: str | os.PathLike,
    *,
    source: str = "auto",
    project: str | os.PathLike | None = None,
    store: str | os.PathLike | None = None,
    max_commits: int = DEFAULT_MAX_COMMITS,
    hashes: bool = False,
    max_file_bytes: int | None = DEFAULT_MAX_VERSION_BYTES,
) -> Timeline:
    """The history of the file at ``path`` as a :class:`Timeline` (close it when done).

    ``source`` is ``git``, ``snapshots`` or ``auto``: Git when the file is inside a
    repository's work tree and Git has a version of it, else the snapshots. ``project``
    or ``store`` names the snapshot store to read (default: the user's own). Git's walk
    stops after ``max_commits`` commits (``truncated``). ``hashes`` also reads every Git
    version that is not an LFS pointer to give its SHA-256."""
    _check_source(source)
    if isinstance(max_commits, bool) or not isinstance(max_commits, int) or max_commits < 1:
        raise InvalidArgumentError(
            "max_commits is a positive whole number", detail={"parameter": "max_commits"}
        )
    full = os.path.abspath(os.fspath(path))
    if os.path.isdir(full):
        raise IsADirectoryError(21, "a folder has no versions; name a file", full)
    limit = max_file_bytes if max_file_bytes is not None else DEFAULT_MAX_VERSION_BYTES
    t: Timeline | None = None
    if source in ("auto", "git"):
        repo = gitrepo.find_repository(full)
        if repo is None:
            if source == "git":
                raise InvalidArgumentError(
                    "the file is not inside a Git repository's work tree", detail={"parameter": "source"}
                )
        else:
            try:
                t = _git_timeline(full, repo, max_commits, hashes, limit)
            except BaseException:
                repo.close()
                raise
            if source == "auto" and not t.stored:
                snaps = _snapshot_timeline(full, open_store(project=project, store=store))
                if snaps.stored:
                    t.close()
                    t = snaps
    if t is None:
        t = _snapshot_timeline(full, open_store(project=project, store=store))
    try:
        _add_working(t)
    except BaseException:
        t.close()
        raise
    return t


# --------------------------------------------------------------------------- the public calls
def history(path: str | os.PathLike, **options: Any) -> dict[str, Any]:
    """``file_history`` data of the file at ``path`` (the options of :func:`timeline`)."""
    with timeline(path, **options) as t:
        return t.data()


def snapshot(
    path: str | os.PathLike,
    *,
    project: str | os.PathLike | None = None,
    store: str | os.PathLike | None = None,
    note: str | None = None,
    max_file_bytes: int | None = None,
) -> dict[str, Any]:
    """Take a snapshot of the file at ``path`` into the user's store, or the project's
    (``project``) or a store folder (``store``): ``snapshot_taken`` data. When the file is
    as its newest snapshot, nothing is written (``new`` false)."""
    full = os.path.abspath(os.fspath(path))
    st = open_store(project=project, store=store)
    snap, new = st.add(full, note=note, max_file_bytes=max_file_bytes)
    with timeline(full, source="snapshots", project=project, store=store) as t:
        entry = next((v for v in t.stored if v.id == snap.id), None)
        count = len(t.stored)
    return {
        "file": _file_data(full),
        "store": {"location": st.location, "path": st.root},
        "new": new,
        "snapshot": entry.data() if entry is not None else None,
        "versions": count,
    }


def compare(
    path: str | os.PathLike,
    older: str | None = None,
    newer: str | None = None,
    *,
    source: str = "auto",
    project: str | os.PathLike | None = None,
    store: str | os.PathLike | None = None,
    measure: bool = True,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_commits: int = DEFAULT_MAX_COMMITS,
    max_file_bytes: int = DEFAULT_MAX_VERSION_BYTES,
) -> dict[str, Any]:
    """``version_diff`` data: what changed from ``older`` to ``newer`` (version names,
    see the module notes). Left out, ``newer`` is the newest version (the working copy
    when it differs from the newest stored one) and ``older`` the one before ``newer``.
    ``measure`` measures the geometry of configurations whose fingerprints differ, both
    versions together within ``max_seconds``."""
    if not isinstance(measure, bool):
        raise InvalidArgumentError("measure is True or False", detail={"parameter": "measure"})
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not max_seconds > 0:
        raise InvalidArgumentError("max_seconds must be positive", detail={"parameter": "max_seconds"})
    with timeline(
        path,
        source=source,
        project=project,
        store=store,
        max_commits=max_commits,
        max_file_bytes=max_file_bytes,
    ) as t:
        a, b = t.pair(older, newer)
        data_a = t.read(a, limit=max_file_bytes)
        data_b = t.read(b, limit=max_file_bytes)
        sha_a, sha_b = hashlib.sha256(data_a).hexdigest(), hashlib.sha256(data_b).hexdigest()
        a.sha256, b.sha256 = a.sha256 or sha_a, b.sha256 or sha_b
        name = os.path.basename(t.path)
        with Side(data_a, name) as side_a, Side(data_b, name) as side_b:
            diff = compare_sides(side_a, side_b, measure=measure, max_seconds=float(max_seconds))
        return {
            "file": _file_data(t.path),
            "source": t.source,
            "from": a.data(),
            "to": b.data(),
            "same_content": sha_a == sha_b,
            **diff,
            "warnings": list(t.warnings) + diff["warnings"],
        }


def read_version(path: str | os.PathLike, version: str, **options: Any) -> bytes:
    """The content of one version of the file at ``path`` (``options``: those of
    :func:`timeline`)."""
    limit = options.get("max_file_bytes") or DEFAULT_MAX_VERSION_BYTES
    with timeline(path, **options) as t:
        return t.read(t.find(version), limit=limit)


def open_version(path: str | os.PathLike, version: str, **options: Any):
    """One version of the file at ``path`` opened read-only from its content, as
    :func:`solidseas.formats.open_any` opens bytes: for its preview, its summary and the
    rest. Close it when done."""
    from ..formats import open_any

    data = read_version(path, version, **options)
    return open_any(data, name=os.path.basename(os.fspath(path)))


__all__ = [
    "DEFAULT_MAX_COMMITS",
    "DEFAULT_MAX_SECONDS",
    "DEFAULT_MAX_VERSION_BYTES",
    "SOURCES",
    "Timeline",
    "Version",
    "compare",
    "data_dir",
    "history",
    "open_store",
    "open_version",
    "read_version",
    "snapshot",
    "timeline",
]
