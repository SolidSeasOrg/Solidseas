"""Each folder's index kept between runs: the listing the viewer read (every document's
entry and its thumbnail), so opening the folder again shows it at once instead of reading
every file again.

One SQLite file a folder in the cache folder (:func:`index_folder`, ``indexes`` beside the
catalogs), named by a digest of the folder's path, what the list shows (SOLIDWORKS
documents alone or every 3D file), the thumbnail size and, when the list shows every 3D
file, the formats an extension reads that were readable when the folder was read
(:func:`extension_formats`: IGES and BREP while the OCCT backend is on), so a listing is
never shown for another choice, nor a folder read with the OCCT backend on once it is
off, or the other way round. With no such format readable the name is the one an index
had before extensions read formats, so those indexes stay good. :func:`save` writes a
temporary file beside it and renames it into place, so a reader sees the old index or
the new one, never half of one. :func:`load`
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


def extension_formats() -> tuple[str, ...]:
    """The formats a conversion backend reads (an extension: IGES and BREP, the OCCT
    backend's) that SolidSeas can read now, sorted; empty while none is on."""
    from solidseas.formats import registry

    return tuple(
        sorted(f.id for f in registry.FORMATS.values() if f.backend is not None and registry.readable(f.id))
    )


def _extensions(formats: str, extensions: Iterable[str] | None) -> list[str]:
    """What an index of ``formats`` is kept for: the extension formats readable (now, when
    ``extensions`` is None), or none for a list of SOLIDWORKS documents alone, which they
    do not change."""
    if formats == "solidworks":
        return []
    return sorted(extension_formats() if extensions is None else set(extensions))


def _key(folder: str, formats: str, thumb_size: tuple[int, int], extensions: list[str]) -> str:
    parts: list[Any] = [os.path.normcase(os.path.abspath(folder)), formats, list(thumb_size)]
    if extensions:
        parts.append(extensions)
    what = json.dumps(parts)
    return hashlib.sha256(what.encode("utf-8")).hexdigest()[:40]


def index_path(
    folder: str,
    formats: str,
    thumb_size: tuple[int, int],
    *,
    root: str | None = None,
    extensions: Iterable[str] | None = None,
) -> str:
    """The file of ``folder``'s index; ``extensions`` as :func:`save` takes them."""
    key = _key(folder, formats, thumb_size, _extensions(formats, extensions))
    return os.path.join(root or index_folder(), key + ".sqlite")


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
    extensions: Iterable[str] | None = None,
) -> str:
    """Save ``rows`` as ``folder``'s index (see the module notes) and return its file.
    ``extensions`` are the extension formats that were readable when the folder was read
    (:func:`extension_formats` now, when None)."""
    kept = _extensions(formats, extensions)
    target = index_path(folder, formats, thumb_size, root=root, extensions=kept)
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
                "extensions": kept,
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
    folder: str,
    formats: str,
    thumb_size: tuple[int, int],
    *,
    root: str | None = None,
    extensions: Iterable[str] | None = None,
) -> SavedIndex | None:
    """``folder``'s saved index, or None (see the module notes): one read while the same
    extension formats were readable as ``extensions`` (:func:`extension_formats` now, when
    None)."""
    kept = _extensions(formats, extensions)
    path = index_path(folder, formats, thumb_size, root=root, extensions=kept)
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
    if meta.get("extensions", []) != kept:  # an index saved before extensions read formats had none
        return None
    if os.path.normcase(str(meta.get("folder"))) != os.path.normcase(os.path.abspath(folder)):
        return None
    read_at = meta.get("read_at")
    if isinstance(read_at, bool) or not isinstance(read_at, (int, float)):
        return None
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
    reason = meta.get("truncated_reason") if isinstance(meta.get("truncated_reason"), str) else None
    return SavedIndex(path, os.path.abspath(folder), float(read_at), counts, reason, int(rows))


def forget(
    folder: str,
    formats: str,
    thumb_size: tuple[int, int],
    *,
    root: str | None = None,
    extensions: Iterable[str] | None = None,
) -> None:
    """Remove ``folder``'s saved index, if there is one."""
    try:
        os.remove(index_path(folder, formats, thumb_size, root=root, extensions=extensions))
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


__all__ = [
    "SavedIndex",
    "age_text",
    "extension_formats",
    "forget",
    "index_folder",
    "index_path",
    "load",
    "save",
]
