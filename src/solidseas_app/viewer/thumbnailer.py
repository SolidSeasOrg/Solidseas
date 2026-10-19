"""Thumbnails drawn for 3D files that store no preview image (an STL, a STEP file...).

The listing gives a file of another format the image it stores, as a PNG SolidSeas
wrote; one that stores none says so (``model.preview_renderable``). Once the
listing has finished, :class:`Thumbnailer` has those drawn from their geometry, one
at a time, the rows on screen first: in the window's worker pool (the library's job
``model_preview``, :mod:`.modelpool`), never in the window's process. Each picture
is kept in the thumbnail cache (:class:`solidseas.render.ThumbnailCache`,
``thumbnails.sqlite`` in the user's cache folder, ``SOLIDSEAS_CACHE_DIR`` when set),
keyed by the file's path, size and modification time and the thumbnail size, so the
next listing of the folder shows it at once. Only this process writes the cache.

Opening another folder, a new listing or closing the window stops it: the picture
being drawn is dropped and nothing more is asked for. A file whose picture cannot be
drawn because its geometry cannot be read (a damaged mesh, a buffer outside its
folder, nothing to draw) has its row marked ``Geometry not readable``
(:meth:`.documents.DocumentModel.mark_unusable`); a timeout or a stopped worker is
not held against the file.
"""

import os
import threading
from typing import Any

from PySide6.QtCore import QObject, QRect, QThreadPool, QTimer, Signal

from .wording import first_sentence, unusable
from .workers import Job, thumbnail

JOB = "model_preview"
TIMEOUT_S = 60.0


def wants_render(entry: dict[str, Any], thumb: bytes | None) -> bool:
    """Whether a listing entry is a file of another format that was read, stores no image
    and can be drawn."""
    m = entry.get("model") or {}
    return (
        thumb is None
        and entry.get("type") == "file"
        and entry.get("status") == "ok"
        and bool(m.get("readable"))
        and bool(m.get("preview_renderable"))
    )


class Thumbnailer(QObject):
    """Draws the thumbnails of the rows that want one (:func:`wants_render`) for ``window``:
    :meth:`start` after a listing, :meth:`stop` when the folder changes or the window
    closes. ``done`` is emitted once nothing is left to draw."""

    done = Signal()

    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._pending: set[int] = set()
        self._generation = 0
        self._busy = False
        self._cache: Any = None
        self._cache_lock = threading.Lock()
        self.drawn = 0  # pictures rendered by a worker
        self.cached = 0  # taken from the cache
        self.failed = 0
        self.active = False

    # -- the cache, made on first use ----------------------------------------------------
    def cache(self):
        with self._cache_lock:
            if self._cache is None:
                from solidseas.render import ThumbnailCache

                self._cache = ThumbnailCache()
            return self._cache

    def close_cache(self) -> None:
        with self._cache_lock:
            if self._cache is not None:
                self._cache.close()
                self._cache = None

    # -- the queue -------------------------------------------------------------------------
    def start(self) -> None:
        """Draw every row of the window's list that wants it, from the current listing."""
        self._generation += 1
        rows = self.w.model.rows
        self._pending = {i for i, r in enumerate(rows) if wants_render(r.entry, r.thumb)}
        self.drawn = self.cached = self.failed = 0
        self.active = bool(self._pending)
        self._busy = False
        if self._pending:
            QTimer.singleShot(0, self._next)
        else:
            self.done.emit()

    def stop(self) -> None:
        self._generation += 1
        self._pending.clear()
        self.active = False

    @property
    def left(self) -> int:
        return len(self._pending) + (1 if self._busy else 0)

    def _visible(self) -> list[int]:
        """The rows of the model the list shows on screen now, top first."""
        view = self.w.list_stack.currentWidget()
        if view not in (self.w.table, self.w.icons):
            return []
        proxy = self.w.proxy
        port: QRect = view.viewport().rect()
        out = []
        if view is self.w.table:
            first = view.rowAt(0)
            last = view.rowAt(port.height() - 1)
            if first < 0:
                return []
            last = proxy.rowCount() - 1 if last < 0 else last
            rows = range(first, last + 1)
        else:
            rows = range(proxy.rowCount())
        for r in rows:
            index = proxy.index(r, 0)
            if view is self.w.icons and not view.visualRect(index).intersects(port):
                continue
            out.append(proxy.mapToSource(index).row())
        return out

    def _next(self) -> None:
        if self._busy or not self._pending or self.w._closing:
            if not self._pending and not self._busy and self.active:
                self.active = False
                self.done.emit()
            return
        on_screen = [i for i in self._visible() if i in self._pending]
        i = on_screen[0] if on_screen else min(self._pending)
        self._pending.discard(i)
        row = self.w.model.rows[i] if i < len(self.w.model.rows) else None
        folder = self.w.folder
        if row is None or folder is None:
            QTimer.singleShot(0, self._next)
            return
        from . import reading

        entry = row.entry
        path = reading.host_path(folder, entry["path"])
        file = entry.get("file") or {}
        size, mtime = file.get("size"), file.get("mtime_ns")
        w, h = self.w.settings.thumbnail_pixels
        settings = f"thumbnail {w}x{h}"
        pool, generation = self.w.models, self._generation

        def work(_emit, cancelled):
            png = None
            key_ok = isinstance(size, int) and mtime is not None
            if key_ok:
                png = self.cache().get(path, size, int(mtime), settings)
            if png is not None:
                return {"ok": True, "png": thumbnail(png, (w, h)), "cached": True}
            if cancelled():
                return {"ok": False}
            params = {"path": path, "within": folder, "render": "auto", "width": w, "height": h}
            result = pool.call(JOB, params, timeout=TIMEOUT_S)
            png = result.payload
            if not png:
                return {"ok": False}
            if key_ok:
                self.cache().put(path, size, int(mtime), png, settings)
            return {"ok": True, "png": thumbnail(png, (w, h)), "cached": False}

        self._busy = True
        job = Job(work)
        self.w._start(self.pool, job, on_finished=lambda r, g=generation, k=i: self._finished(g, k, r))

    def _finished(self, generation: int, i: int, result: Any) -> None:
        self._busy = False
        if generation != self._generation:
            return
        if isinstance(result, dict) and result.get("ok") and result.get("png"):
            self.w.model.set_thumb(i, result["png"])
            if result.get("cached"):
                self.cached += 1
            else:
                self.drawn += 1
        else:
            self.failed += 1
            error = result.get("error") if isinstance(result, dict) else None
            if unusable(error):
                self.w.model.mark_unusable(i, first_sentence(error, self._path_of(i)))
        QTimer.singleShot(0, self._next)

    def _path_of(self, i: int) -> str | None:
        rows, folder = self.w.model.rows, self.w.folder
        if i >= len(rows) or folder is None:
            return None
        from . import reading

        return reading.host_path(folder, rows[i].entry["path"])

    def report(self) -> dict[str, Any]:
        return {"drawn": self.drawn, "cached": self.cached, "failed": self.failed, "left": self.left}


def cache_path() -> str:
    """Where the thumbnail cache is kept (``SOLIDSEAS_CACHE_DIR`` when set)."""
    from solidseas.catalog.store import cache_dir
    from solidseas.render import THUMBNAIL_FILE

    return os.path.join(cache_dir(), THUMBNAIL_FILE)


__all__ = ["Thumbnailer", "cache_path", "wants_render"]
