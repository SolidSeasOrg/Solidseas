"""Each folder's index kept between runs: the listing the viewer read (every document's
entry and its thumbnail), so opening the folder again shows it at once instead of reading
every file again.

One SQLite file a folder in the cache folder (:func:`index_folder`, ``indexes`` beside the
catalogs), named by a digest of the folder's path, what the list shows (SOLIDWORKS
documents alone or every 3D file) and the thumbnail size, so a listing is never shown
for another choice. :func:`save` writes a temporary file beside it and renames it into
place, so a reader sees the old index or the new one, never half of one. :func:`load`
gives the saved index with the time it was read, or None: none saved, one of another
version, or one that cannot be read (a damaged file is never shown as an empty folder).
A folder on a network share is indexed like any other; its index stays on this computer.

Nothing here imports Qt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

VERSION = 1
MAX_ROWS = 2_000_000


def index_folder() -> str:
    """Where the saved indexes are: ``indexes`` in SolidSeas' cache folder."""
    from solidseas.catalog.store import cache_dir

    return os.path.join(cache_dir(), "indexes")


def _key(folder: str, formats: str, thumb_size: tuple[int, int]) -> str:
    what = json.dumps([os.path.normcase(os.path.abspath(folder)), formats, list(thumb_size)])
    return hashlib.sha256(what.encode("utf-8")).hexdigest()[:40]


def index_path(folder: str, formats: str, thumb_size: tuple[int, int], *, root: str | None = None) -> str:
    return os.path.join(root or index_folder(), _key(folder, formats, thumb_size) + ".sqlite")


@dataclass(frozen=True)
class SavedIndex:
    """A folder's saved index: when it was read (seconds since the epoch), the listing's
    counts and why it stopped short (None when it did not), and its rows."""

    path: str
    folder: str
    read_at: float
    counts: dict[str, Any]
    truncated_reason: str | None
    rows: int

    def age_seconds(self, now: float | None = None) -> float:
        return max(0.0, (time.time() if now is None else now) - self.read_at)

    def entries(self, batch: int = 256) -> Iterator[list[tuple[dict[str, Any], bytes | None]]]:
        """The rows in the order they were listed, ``batch`` at a time, as the listing
        sends them: ``(entry, thumbnail_png)``."""
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            cur = con.execute("SELECT entry, thumb FROM rows ORDER BY seq")
            while True:
                got = cur.fetchmany(batch)
                if not got:
                    return
                yield [(json.loads(e), t) for e, t in got]
        finally:
            con.close()


def save(
    folder: str,
    formats: str,
    thumb_size: tuple[int, int],
    rows: Iterable[tuple[dict[str, Any], bytes | None]],
    *,
    counts: dict[str, Any] | None = None,
    truncated_reason: str | None = None,
    read_at: float | None = None,
    root: str | None = None,
) -> str:
    """Save ``rows`` as ``folder``'s index (see the module notes) and return its file."""
    target = index_path(folder, formats, thumb_size, root=root)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".index-", suffix=".sqlite", dir=os.path.dirname(target))
    os.close(fd)
    try:
        con = sqlite3.connect(temp)
        try:
            con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            con.execute("CREATE TABLE rows (seq INTEGER PRIMARY KEY, entry TEXT NOT NULL, thumb BLOB)")
            n = 0
            for entry, thumb in rows:
                if n >= MAX_ROWS:
                    break
                con.execute(
                    "INSERT INTO rows (seq, entry, thumb) VALUES (?, ?, ?)",
                    (n, json.dumps(entry, ensure_ascii=False, allow_nan=False), thumb),
                )
                n += 1
            meta = {
                "version": VERSION,
                "folder": os.path.abspath(folder),
                "formats": formats,
                "thumb_size": list(thumb_size),
                "read_at": time.time() if read_at is None else read_at,
                "counts": counts or {},
                "truncated_reason": truncated_reason,
                "rows": n,
            }
            con.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()]
            )
            con.commit()
        finally:
            con.close()
        with open(temp, "rb+") as fh:
            os.fsync(fh.fileno())
        os.replace(temp, target)
        return target
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise


def load(
    folder: str, formats: str, thumb_size: tuple[int, int], *, root: str | None = None
) -> SavedIndex | None:
    """``folder``'s saved index, or None (see the module notes)."""
    path = index_path(folder, formats, thumb_size, root=root)
    if not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
            rows = con.execute("SELECT count(*) FROM rows").fetchone()[0]
        finally:
            con.close()
    except (sqlite3.Error, ValueError, OSError):
        return None
    if meta.get("version") != VERSION or meta.get("formats") != formats or meta.get("rows") != rows:
        return None
    if os.path.normcase(str(meta.get("folder"))) != os.path.normcase(os.path.abspath(folder)):
        return None
    read_at = meta.get("read_at")
    if isinstance(read_at, bool) or not isinstance(read_at, (int, float)):
        return None
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
    reason = meta.get("truncated_reason") if isinstance(meta.get("truncated_reason"), str) else None
    return SavedIndex(path, os.path.abspath(folder), float(read_at), counts, reason, int(rows))


def forget(folder: str, formats: str, thumb_size: tuple[int, int], *, root: str | None = None) -> None:
    """Remove ``folder``'s saved index, if there is one."""
    try:
        os.remove(index_path(folder, formats, thumb_size, root=root))
    except OSError:
        pass


def age_text(seconds: float) -> str:
    """An index's age as the bar says it: "12 min", "3 h 12 min", "2 days 4 h"."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    hours, mins = divmod(minutes, 60)
    if hours < 1:
        return f"{mins} min"
    days, hrs = divmod(hours, 24)
    if days < 1:
        return f"{hrs} h {mins} min" if mins else f"{hrs} h"
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} {hrs} h" if hrs else f"{days} {unit}"


__all__ = ["SavedIndex", "age_text", "forget", "index_folder", "index_path", "load", "save"]
