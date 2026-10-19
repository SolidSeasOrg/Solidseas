"""Background jobs: every file read runs here, never on the UI thread.

A :class:`Job` runs a function in a ``QThreadPool`` and reports through Qt
signals, which reach the window on the UI thread as queued calls. The function
gets ``emit`` (send a progress value) and ``cancelled`` (true once the window
no longer wants the result) and returns the final value. An exception becomes
``{"ok": False, "error": ...}`` instead of escaping the thread.
"""

import base64
import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QImage, QImageReader

from solidseas import model, scan

THUMB_WIDTH, THUMB_HEIGHT = 128, 96  # the default thumbnail size; Settings can change it
PREVIEW_MAX = 1600  # the Preview tab's image is scaled to fit this square, off the UI thread
_BATCH_ROWS, _BATCH_SECONDS = 64, 0.15
# Documents a listing reads at once, and thumbnails it makes at once: on a network share a
# document's time is mostly round trips to the server, which overlap (solidseas.scan threads).
LISTING_THREADS = 8
THUMBNAIL_THREADS = 4


class JobSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class Job(QRunnable):
    """``work(emit, cancelled)`` in a pool thread; ``finished`` carries its result."""

    def __init__(self, work: Callable[[Callable[[Any], None], Callable[[], bool]], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)  # the window keeps the Python object until it has finished
        self.signals = JobSignals()
        self._work = work
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            result = self._work(self.signals.progress.emit, self._cancel.is_set)
        except Exception as exc:  # never let an exception end the pool thread
            result = {"ok": False, "error": model.error_info(exc)}
        self.signals.finished.emit(result)


def _decode(image: bytes, width: int, height: int) -> QImage:
    """``image`` decoded and scaled down to fit ``width`` x ``height``; a null image
    when it does not decode.

    Through ``QImageReader``, whose ``read`` lets go of the interpreter lock:
    ``QImage.fromData`` keeps it, and an 8000 x 8000 preview decoding in a worker
    then held the window for half a second."""
    buf = QBuffer()
    buf.setData(QByteArray(image))
    if not buf.open(QIODevice.OpenModeFlag.ReadOnly):
        return QImage()
    reader = QImageReader(buf)
    size = reader.size()  # from the header, without decoding
    if size.isValid() and (size.width() > width or size.height() > height):
        reader.setScaledSize(size.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio))
    return reader.read()


def thumbnail(image: bytes, size: tuple[int, int] = (THUMB_WIDTH, THUMB_HEIGHT)) -> bytes | None:
    """A preview image scaled to fit ``size`` (the thumbnail size setting), as PNG
    bytes (small, so a listing of thousands of documents keeps little memory);
    None when it does not decode."""
    width, height = size
    img = _decode(image, width, height)
    if img.isNull():
        return None
    if img.width() < width and img.height() < height:  # a small preview fills the tile
        img = img.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def preview_image(image: bytes) -> QImage:
    """The Preview tab's image, decoded here in the worker and scaled down to fit
    :data:`PREVIEW_MAX`, so the UI thread only wraps it in a pixmap: decoding an
    8000 x 8000 preview there held the window for 0.6 s. A null image when it
    does not decode."""
    return _decode(image, PREVIEW_MAX, PREVIEW_MAX)


def listing_work(
    folder: str,
    thumb_size: tuple[int, int] = (THUMB_WIDTH, THUMB_HEIGHT),
    *,
    formats: str = "solidworks",
    foreign_pool=None,
) -> Callable[[Callable[[Any], None], Callable[[], bool]], dict[str, Any]]:
    """The recursive listing of ``folder`` through ``solidseas.scan``, with thumbnails
    of ``thumb_size``.

    ``formats`` is ``solidworks`` (SOLIDWORKS documents only) or ``all`` (every 3D
    file SolidSeas knows, :mod:`solidseas.formats.registry`); a file of another
    format is read by ``foreign_pool`` (the window's :class:`.modelpool.ModelPool`),
    never in this process, and its stored image arrives as a PNG SolidSeas wrote.

    Progress values are lists of ``(entry, thumbnail_png)``, in the walk's order, sent
    every 64 entries or 0.15 s. Documents are read :data:`LISTING_THREADS` at a time.
    The inline image of each entry is turned into a thumbnail in a pool of
    :data:`THUMBNAIL_THREADS` threads (``QImageReader`` lets go of the interpreter
    lock while it decodes) and dropped from the entry, so the listing has no cap on
    images to honour."""

    def work(emit: Callable[[Any], None], cancelled: Callable[[], bool]) -> dict[str, Any]:
        from concurrent.futures import Future, ThreadPoolExecutor

        t = time.perf_counter()
        options: dict[str, Any] = {}
        if formats != "solidworks":
            options = {"formats": formats, "foreign_pool": foreign_pool}
        listing = scan(
            folder,
            recursive=True,
            include=("preview_data",),
            max_preview_data_bytes=1 << 62,
            threads=LISTING_THREADS,
            **options,
        )
        thumbs = ThreadPoolExecutor(THUMBNAIL_THREADS, thread_name_prefix="solidseas-thumbnails")
        batch: list[tuple[dict[str, Any], Future | None]] = []
        last = time.monotonic()
        stopped = False

        def send() -> None:
            emit([(entry, None if f is None else f.result()) for entry, f in batch])

        try:
            for entry in listing:
                if cancelled():
                    stopped = True
                    break
                future = None
                pv = entry.get("preview")
                if pv and pv.get("data_base64"):
                    future = thumbs.submit(thumbnail, base64.b64decode(pv["data_base64"]), thumb_size)
                    pv["data_base64"] = None
                batch.append((entry, future))
                if len(batch) >= _BATCH_ROWS or time.monotonic() - last >= _BATCH_SECONDS:
                    send()
                    batch, last = [], time.monotonic()
            if batch:
                send()
        finally:
            thumbs.shutdown(wait=False, cancel_futures=True)  # every thumbnail sent was waited for
        return {
            "ok": True,
            "counts": dict(listing.counts),
            "truncated_reason": listing.truncated_reason,
            "cancelled": stopped,
            "seconds": time.perf_counter() - t,
        }

    return work
