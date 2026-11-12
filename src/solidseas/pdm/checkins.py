"""Check-in records: ``.solidseas/vault/checkins/<yyyy>/<time>-<id>.json`` (``docs/PDM.md`` 3).

One record per check-in, created with ``O_EXCL`` and never rewritten, so two programs
never lose each other's records and no lock is needed. A record names the files it
covers by their path below the library, with the SHA-256, size and snapshot id of the
version it stored or found. A file the check-in recorded as gone carries ``removed``
and no content.

Records are data from a folder others may write to: :func:`parse_checkin` checks each
field and returns None for a record that does not hold up, which the reader skips.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Any

from ..versions.snapstore import MAX_NOTE

RECORD_VERSION = 1
MAX_CHECKIN_BYTES = 32 << 20
MAX_CHECKIN_FILES = 200_000
MAX_LABEL = 64
MAX_WHO = 100
CHECKIN_NAME = re.compile(r"(\d{8}T\d{12}Z)-([0-9a-f]{12})\.json\Z")
YEAR_NAME = re.compile(r"\d{4}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_ID = re.compile(r"[0-9a-f]{12}\Z")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class CheckinFile:
    """One file of a check-in: ``path`` below the library (``/``-separated), the SHA-256,
    size and snapshot id of its version, ``new`` when this check-in stored that version
    and ``removed`` when it recorded the file as gone (no content then)."""

    path: str
    sha256: str | None
    size: int | None
    snapshot: str | None
    new: bool = False
    removed: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "snapshot": self.snapshot,
            "new": self.new,
            "removed": self.removed,
        }


@dataclass(frozen=True)
class Checkin:
    """One check-in record. ``auto`` marks a scan's. ``record`` is the record's file name."""

    id: str
    when: datetime.datetime
    note: str | None
    who: str
    revision: str | None
    state: str | None
    auto: bool
    solidseas: str
    files: tuple[CheckinFile, ...]
    record: str = ""

    def stamp(self) -> str:
        return self.when.strftime("%Y%m%dT%H%M%S%f") + "Z"

    def name(self) -> str:
        return f"{self.stamp()}-{self.id}.json"

    def to_json(self) -> dict[str, Any]:
        return {
            "v": RECORD_VERSION,
            "id": self.id,
            "when_utc": self.when.strftime(_TIME_FORMAT),
            "note": self.note,
            "who": self.who,
            "revision": self.revision,
            "state": self.state,
            "auto": self.auto,
            "solidseas": self.solidseas,
            "files": [f.to_json() for f in self.files],
        }

    def brief(self) -> dict[str, Any]:
        """The check-in without its files, as ``pdm log`` lists it beside a version."""
        return {
            "id": self.id,
            "when_utc": self.when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": self.note,
            "who": self.who,
            "revision": self.revision,
            "state": self.state,
            "auto": self.auto,
        }


def valid_relative(path: Any) -> bool:
    """Whether ``path`` is a ``/``-separated path strictly below the library."""
    if not isinstance(path, str) or not 0 < len(path) <= 4096 or "\0" in path or "\\" in path:
        return False
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return False
    return all(p not in ("", ".", "..") for p in path.split("/"))


def valid_label(value: Any, limit: int = MAX_LABEL) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def _text(value: Any, limit: int, *, empty: bool = True) -> bool:
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        return False
    return empty or bool(value)


def _parse_file(item: Any) -> CheckinFile | None:
    if not isinstance(item, dict):
        return None
    path, sha, size, snap = item.get("path"), item.get("sha256"), item.get("size"), item.get("snapshot")
    new, removed = item.get("new"), item.get("removed")
    if not valid_relative(path) or not isinstance(new, bool) or not isinstance(removed, bool):
        return None
    if removed:
        if sha is not None or size is not None or snap is not None or new:
            return None
        return CheckinFile(path, None, None, None, False, True)
    if (
        not isinstance(sha, str)
        or not _SHA256.match(sha)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 <= size <= 2**53 - 1
        or not isinstance(snap, str)
        or not _SNAPSHOT_ID.match(snap)
    ):
        return None
    return CheckinFile(path, sha, size, snap, new, False)


def parse_checkin(data: bytes, name: str, year: str | None = None) -> Checkin | None:
    """The check-in a record file holds, or None when any field does not hold up: its
    name, the year folder it sits in, the time and id in its name, and every field and
    file entry inside."""
    m = CHECKIN_NAME.match(name)
    if m is None or len(data) > MAX_CHECKIN_BYTES:
        return None
    if year is not None and m.group(1)[:4] != year:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != RECORD_VERSION or obj.get("id") != m.group(2):
        return None
    when_text = obj.get("when_utc")
    if not isinstance(when_text, str) or len(when_text) > 40:
        return None
    try:
        when = datetime.datetime.strptime(when_text, _TIME_FORMAT).replace(tzinfo=datetime.UTC)
    except ValueError:
        return None
    if when.strftime("%Y%m%dT%H%M%S%f") + "Z" != m.group(1):
        return None
    note, who, revision, state = obj.get("note"), obj.get("who"), obj.get("revision"), obj.get("state")
    auto, made_by, files = obj.get("auto"), obj.get("solidseas"), obj.get("files")
    if (
        (note is not None and not _text(note, MAX_NOTE))
        or not _text(who, MAX_WHO)
        or (revision is not None and not valid_label(revision))
        or (state is not None and not valid_label(state))
        or not isinstance(auto, bool)
        or not _text(made_by, 40)
        or not isinstance(files, list)
        or len(files) > MAX_CHECKIN_FILES
    ):
        return None
    parsed = []
    for item in files:
        f = _parse_file(item)
        if f is None:
            return None
        parsed.append(f)
    return Checkin(m.group(2), when, note, who, revision, state, auto, made_by, tuple(parsed), name)


__all__ = ["Checkin", "CheckinFile", "parse_checkin", "valid_label", "valid_relative"]
