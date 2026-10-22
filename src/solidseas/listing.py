"""Folder listings: one entry per SOLIDWORKS document (and, when asked, per 3D file of any
format SolidSeas knows), for ERP sync and file browsers.

:func:`scan` walks a folder with the shared walker (:mod:`solidseas.walk`) and
builds one ``listing`` entry per SOLIDWORKS document, from the same
sub-builders as ``document_summary`` (``docs/API.md`` section 5.7):

* each document is opened read-only with a held, unbuffered handle
  (``open_document(..., hold_open=True)``), only the streams the entry needs
  are read, and the handle is closed before the next file, so a listing reads a
  few percent of each file and never keeps one open while SOLIDWORKS may want to
  save over it;
* links and mount points are listed with status ``link`` and never followed,
  cloud placeholders with status ``placeholder`` and never opened, SOLIDWORKS
  lock files (``~$``) and FIFOs, sockets or devices named like a document with
  status ``skipped``, and a STEP file wearing a SOLIDWORKS extension with
  status ``not_solidworks`` and ``detected: "step"``;
* each document is opened ``within`` the listed folder, so a name that became a
  link after its folder was listed is refused (``link_refused``) and a file
  that became a placeholder is not recalled (``placeholder_file``);
* one bad file never stops the listing: its entry carries the error object
  (a locked file has code ``locked`` and ``retryable: true``) and the walk goes
  on. Only the folder argument itself raises: ``FileNotFoundError``,
  ``NotADirectoryError`` or ``PermissionError``.

The bounds (``max_entries``, ``max_examined``, ``max_seconds``) are checked
between entries. A slow file, or a listing call that blocks on an unreachable
share, runs past ``max_seconds`` until it returns. With a ``pool``
(:class:`solidseas.workers.WorkerPool`) every document is read in a worker
process instead, with ``file_timeout`` as its deadline: a file that hangs or
crashes its worker becomes an error entry (``timeout``, ``worker_crashed``)
and the listing goes on. The REST service lists folders this way.

``threads`` (default 1) reads that many files at once, in threads, a few files
ahead of the entry yielded: on a network share most of a file's time is the
round trips to the server, which then overlap. The entries, their order, the
counts and the inline images are exactly those of a listing read one file at a
time; only the bounds are checked against the entries yielded, so a listing
stopped by them may have read a few files more than it lists.

``after`` resumes a listing after the entry with that path (relative to the
listed folder), in the walk's own order, so a page of a long listing can
continue where the last one stopped; :meth:`Scan.fingerprint` hashes what a
listing would cover from the directory entries alone, without opening a file
(the REST service's ``ETag``).

``formats`` (provisional) chooses the file formats listed: ``"solidworks"`` (the
default, and the listing exactly as before), ``"all"``, or format ids of the
registry (:mod:`solidseas.formats.registry`). A file of a format SolidSeas reads
is read with :func:`solidseas.formats.open_any` (in ``foreign_pool``, else
``pool``, when one is given) into an entry whose ``model`` object holds its
format, units, counts and application, its SOLIDWORKS fields null; a file of a
format SolidSeas lists but cannot read yet is listed with status
``unsupported``, ``detected`` its format id and ``model.readable`` false, and is
never opened. A name an extension shared with other programs gives (``.asm``,
``.prt``) is listed only when the file's first bytes are that format's. With a
``foreign_pool`` and no ``pool`` (the viewer: SOLIDWORKS documents in its own
threads, everything else in workers), a file wearing a SOLIDWORKS extension over
another format's content is read in the foreign pool too when ``open_document``
finds no SOLIDWORKS container in it. A compound file (an Alibre, Inventor or
Solid Edge file renamed) or a 2015+ container is one to ``open_document``: it is
read in the caller's process as the SOLIDWORKS document its name says, as any
``.sldprt`` is, and listed as one.

``scan`` returns a :class:`Scan`: iterate it for the entries (plain JSON data,
exactly what the CLI and REST send), then read :attr:`Scan.counts`; or call
:meth:`Scan.listing` for the whole ``listing`` data at once.
"""

import hashlib
import os
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator
from typing import Any

from . import model
from .errors import InvalidArgumentError, SolidSeasError, UnknownFormatError
from .formats import registry
from .formats.solidworks import SOLIDWORKS_EXTENSIONS, open_document
from .formats.solidworks._io import open_readonly
from .walk import DEFAULT_MAX_DEPTH, DEFAULT_MAX_EXAMINED, Walk, WalkEntry

MAX_PREVIEW_DATA_BYTES = 8 << 20  # inline base64 image text per listing
_IMAGE = "\x00image"  # a read entry's image, until it is inlined in walk order
_SNIFF_BYTES = 4096
_STATUSES = ("ok", "error", "skipped", "link", "placeholder", "not_solidworks", "unsupported")
_SIGNATURE_BYTES = 8
MAX_THREADS = 32
_AHEAD = 4  # files read ahead per thread


def sniff_format(path: str, *, within: str | None = None) -> str | None:
    """What a file that is not a SOLIDWORKS container is instead, from its first bytes:
    ``"step"`` for a STEP file (``ISO-10303`` after leading whitespace), else None.
    ``within`` opens it as :func:`~solidseas.formats.solidworks.open_document` does."""
    try:
        with open_readonly(path) if within is None else open_readonly(path, within=within) as fh:
            head = fh.read(_SNIFF_BYTES)
    except (OSError, SolidSeasError):
        return None
    head = head.removeprefix(b"\xef\xbb\xbf").lstrip(b" \t\r\n\x0b\x0c")
    return "step" if head.startswith(b"ISO-10303") else None


def _is_document_name(name: str) -> bool:
    return name.lower().endswith(SOLIDWORKS_EXTENSIONS)


def walk_order(rel: str) -> tuple:
    """The position of a path (``/``-separated, relative to the walked folder) in the
    walker's order: breadth first, each folder's entries sorted case-folded."""
    parts = rel.split("/")
    return len(parts), tuple((p.casefold(), p) for p in parts)


def read_entry(
    path: str,
    rel: str,
    name: str,
    file: dict[str, Any] | None,
    *,
    within: str,
    include: Collection[str],
    reader_message: bool = True,
    max_file_bytes: int | None = None,
    refuse_hard_links: bool = False,
    formats: Collection[str] | None = None,
    limits: Any = None,
) -> tuple[dict[str, Any], bytes | None]:
    """The ``listing`` entry for one document the walk found, and its preview image when
    ``include`` asks for the preview. The document is opened ``within`` the folder;
    any failure becomes the entry's error, and a STEP file wearing a SOLIDWORKS
    extension becomes ``not_solidworks``. A worker process runs this for a
    listing that has a pool; ``max_file_bytes`` and ``refuse_hard_links`` are
    passed to ``open_document``. With ``formats`` (format ids), a file wearing a
    SOLIDWORKS extension whose content is a format among them that SolidSeas reads
    is read as that format (:func:`read_model_entry`, with those ``formats`` and
    ``limits``)."""
    try:
        with open_document(
            path,
            hold_open=True,
            name=name,
            within=within,
            max_file_bytes=max_file_bytes,
            refuse_hard_links=refuse_hard_links,
        ) as doc:
            return model.document_entry(rel, doc, include)
    except UnknownFormatError as exc:
        if formats:
            other = _content_format(path, name, within)
            if other is not None and other in formats and registry.readable(other):
                return read_model_entry(
                    path,
                    rel,
                    name,
                    file,
                    within=within,
                    include=include,
                    reader_message=reader_message,
                    max_file_bytes=max_file_bytes,
                    refuse_hard_links=refuse_hard_links,
                    formats=formats,
                    limits=limits,
                )
        detected = sniff_format(path, within=within)
        if detected is not None:
            return model.listing_entry(rel, "file", "not_solidworks", detected=detected, file=file), None
        error = model.error_info(exc, reader_message=reader_message)
    except Exception as exc:  # one bad file never stops the listing
        error = model.error_info(exc, reader_message=reader_message)
    return model.listing_entry(rel, "file", "error", file=file, error=error), None


def _content_format(path: str, name: str, within: str) -> str | None:
    """The format the first bytes of a file say it is, whatever its name says."""
    try:
        det = registry.detect(path, name, within=within)
    except (OSError, SolidSeasError):
        return None
    return det.format if det.by == "content" else None


def read_model_entry(
    path: str,
    rel: str,
    name: str,
    file: dict[str, Any] | None,
    *,
    within: str,
    include: Collection[str],
    reader_message: bool = True,
    max_file_bytes: int | None = None,
    refuse_hard_links: bool = False,
    formats: Collection[str] | None = None,
    limits: Any = None,
) -> tuple[dict[str, Any], bytes | None]:
    """The ``listing`` entry for one file of another format than SOLIDWORKS (provisional),
    and the preview it stores, as a PNG SolidSeas wrote, when ``include`` asks for the
    preview. The file is opened with :func:`solidseas.formats.open_any` ``within`` the
    folder, holding its handle, reading only ``formats`` (None: every format) within
    ``limits``; a SOLIDWORKS document wearing another extension gets a SOLIDWORKS
    entry. Any failure becomes the entry's error. A worker runs this for a listing with
    a pool (the job ``model_entry``)."""
    from .formats import open_any
    from .formats.base import ModelDocument

    try:
        with open_any(
            path,
            name=name,
            within=within,
            hold_open=True,
            max_file_bytes=max_file_bytes,
            refuse_hard_links=refuse_hard_links,
            formats=formats,
            limits=limits,
        ) as doc:
            if isinstance(doc, ModelDocument):
                return model.model_listing_entry(rel, doc, include)
            return model.document_entry(rel, doc, include)
    except Exception as exc:  # one bad file never stops the listing
        error = model.error_info(exc, reader_message=reader_message)
    return model.listing_entry(rel, "file", "error", file=file, error=error), None


def _include(include: Collection[str] | str) -> tuple[str, ...]:
    if isinstance(include, str):
        include = (include,)
    unknown = [p for p in include if p not in model.LISTING_PARTS]
    if unknown:
        raise InvalidArgumentError(
            f"include accepts {', '.join(model.LISTING_PARTS)}", detail={"parameter": "include"}
        )
    return tuple(p for p in model.LISTING_PARTS if p in include)


def _count(value: Any, name: str, *, allow_none: bool) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidArgumentError(f"{name} must be a positive whole number", detail={"parameter": name})
    return value


class Scan:
    """One folder listing in progress. Create it with :func:`scan`.

    Iterating yields ``listing`` entries as plain JSON data; a scan can be iterated
    once. :attr:`counts`, :attr:`truncated_reason`, :attr:`preview_data_capped` and
    :attr:`walk_stats` describe what was done so far.
    """

    def __init__(
        self,
        folder: str | os.PathLike,
        *,
        recursive: bool = False,
        include: Collection[str] | str = model.LISTING_DEFAULT,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_entries: int | None = None,
        max_examined: int | None = DEFAULT_MAX_EXAMINED,
        max_seconds: float | None = None,
        max_preview_data_bytes: int = MAX_PREVIEW_DATA_BYTES,
        reader_message: bool = True,
        pool=None,
        file_timeout: float | None = None,
        within: str | os.PathLike | None = None,
        root_id: str | None = None,
        folder_rel: str = "",
        after: str | None = None,
        formats: Any = registry.SOLIDWORKS,
        foreign_pool=None,
        threads: int = 1,
    ) -> None:
        self.include = _include(include)
        self.formats = registry.select(formats)
        self.foreign_pool = foreign_pool
        self._only_solidworks = self.formats == {registry.SOLIDWORKS}
        self.recursive = bool(recursive)
        self.max_entries = _count(max_entries, "max_entries", allow_none=True)
        self.max_examined = _count(max_examined, "max_examined", allow_none=True)
        _count(max_depth, "max_depth", allow_none=False)
        if max_seconds is not None and (isinstance(max_seconds, bool) or not max_seconds > 0):
            raise InvalidArgumentError("max_seconds must be positive", detail={"parameter": "max_seconds"})
        self.max_preview_data_bytes = max_preview_data_bytes
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= MAX_THREADS:
            raise InvalidArgumentError(
                f"threads is a whole number from 1 to {MAX_THREADS}", detail={"parameter": "threads"}
            )
        self.threads = threads
        self.reader_message = reader_message
        self.pool = pool
        if file_timeout is not None and (isinstance(file_timeout, bool) or not file_timeout > 0):
            raise InvalidArgumentError("file_timeout must be positive", detail={"parameter": "file_timeout"})
        self.file_timeout = file_timeout
        self.root_id = root_id
        self.folder_rel = folder_rel
        if after is not None and (not isinstance(after, str) or not after):
            raise InvalidArgumentError("after is a path in the listing", detail={"parameter": "after"})
        self._after = walk_order(after) if after is not None else None
        self.last_rel: str | None = None  # the walk path of the last entry listed
        self.folder = os.fspath(folder)
        self.within = os.fspath(within) if within is not None else self.folder
        self._deadline = time.monotonic() + max_seconds if max_seconds is not None else None
        self._walk = Walk(
            self.folder,
            recursive=self.recursive,
            max_depth=max_depth,
            max_examined=self.max_examined,
            deadline=self._deadline,
        )
        self.counts: dict[str, int] = {"entries": 0, **dict.fromkeys(_STATUSES, 0), "folders": 0}
        self.truncated_reason: str | None = None
        self.preview_data_capped = False
        self._inline_chars = 0
        self._deferred = False  # reading in threads: images are inlined in walk order
        self._folders_at: int | None = None  # the folders walked when a threaded listing stopped
        self._started = False

    @property
    def walk_stats(self):
        """The walker's own counts (:class:`solidseas.walk.WalkStats`)."""
        return self._walk.stats

    # -- what becomes an entry -----------------------------------------------------
    def _listed_name(self, name: str) -> bool:
        if self._only_solidworks:
            return _is_document_name(name)
        spec = registry.by_extension(name)
        return spec is not None and spec.id in self.formats

    def _relevant(self, we: WalkEntry) -> bool:
        if we.kind == "folder":
            return not self.recursive or we.reason == "max_depth"
        if we.kind in ("file", "skipped"):
            return self._listed_name(we.name)
        if we.kind == "link" and we.reason == "symlink" and os.name != "nt":
            # On Linux and macOS a symbolic link does not record whether it leads to a
            # folder, and finding out would follow it, so every one is listed.
            return True
        return we.is_dir or self._listed_name(we.name)  # link, placeholder, error

    def _error(self, exc: BaseException) -> dict[str, Any]:
        return model.error_info(exc, reader_message=self.reader_message)

    def _rel(self, we: WalkEntry) -> str:
        return f"{self.folder_rel}/{we.rel}" if self.folder_rel else we.rel

    def _entry(self, we: WalkEntry) -> dict[str, Any] | None:
        type_ = "folder" if we.is_dir else "file"
        rel = self._rel(we)
        file = None if we.is_dir else model.file_object(we.name, we.size, we.mtime_ns)
        if we.kind == "folder":
            if we.reason == "max_depth":
                return model.listing_entry(rel, "folder", "skipped", reason="max_depth")
            return model.listing_entry(rel, "folder", "ok")
        if we.kind == "link":
            return model.listing_entry(rel, type_, "link", reason=we.reason)
        if we.kind == "placeholder":
            return model.listing_entry(rel, type_, "placeholder", reason=we.reason, file=file)
        if we.kind == "skipped":
            return model.listing_entry(rel, "file", "skipped", reason=we.reason, file=file)
        if we.kind == "error":
            return model.listing_entry(rel, type_, "error", file=file, error=self._error(we.error))
        if self._only_solidworks:
            return self._read(we, rel, file)
        spec = registry.by_extension(we.name)
        if spec is None:  # pragma: no cover - _relevant listed only known extensions
            return None
        if registry.extension_of(we.name) in spec.needs_signature and not self._signature(we, spec):
            return None  # an extension another program shares, and not this format's content
        if spec.id == registry.SOLIDWORKS:
            return self._read(we, rel, file)
        if not registry.readable(spec.id):
            return model.unsupported_entry(rel, file, spec)
        return self._read_model(we, rel, file)

    def _signature(self, we: WalkEntry, spec) -> bool:
        """Whether a file whose extension other programs share is ``spec``'s, from its
        first bytes (read here: a few bytes compared, nothing parsed)."""
        try:
            with open_readonly(we.path, within=self.within) as fh:
                head = fh.read(_SIGNATURE_BYTES)
        except (OSError, SolidSeasError):
            return False
        return registry.signature_ok(spec, we.name, head)

    def _read_model(self, we: WalkEntry, rel: str, file: dict[str, Any] | None) -> dict[str, Any]:
        """A model file's entry, read as one of the listed formats only: content of
        another format, whatever the name says, is the entry's error."""
        pool = self.foreign_pool if self.foreign_pool is not None else self.pool
        listed = None if self.formats == frozenset(registry.FORMATS) else sorted(self.formats)
        if pool is None:
            entry, image = read_model_entry(
                we.path,
                rel,
                we.name,
                file,
                within=self.within,
                include=self.include,
                reader_message=self.reader_message,
                formats=listed,
            )
        else:
            params = {
                "path": we.path,
                "rel": rel,
                "name": we.name,
                "file": file,
                "within": self.within,
                "include": list(self.include),
                "reader_message": self.reader_message,
            }
            if listed is not None:
                params["formats"] = listed
            try:
                result = pool.call("model_entry", params, timeout=self.file_timeout)
                entry, image = result.data, result.payload
            except Exception as exc:  # a worker that timed out or crashed is this entry's error
                return model.listing_entry(rel, "file", "error", file=file, error=self._error(exc))
        return self._inline(entry, image)

    def _read(self, we: WalkEntry, rel: str, file: dict[str, Any] | None) -> dict[str, Any]:
        others = None if self._only_solidworks else sorted(self.formats)
        if self.pool is None and others is not None and self.foreign_pool is not None:
            # SOLIDWORKS documents are read here, as always; a file wearing a SOLIDWORKS
            # extension over another format's content that open_document refuses is read
            # only in the foreign pool (its first bytes alone are looked at here). A compound
            # file or 2015+ container is a SOLIDWORKS document to open_document, read here.
            entry, image = read_entry(
                we.path,
                rel,
                we.name,
                file,
                within=self.within,
                include=self.include,
                reader_message=self.reader_message,
            )
            if entry["status"] in ("not_solidworks", "error"):
                other = _content_format(we.path, we.name, self.within)
                if other is not None and other in self.formats and registry.readable(other):
                    return self._read_model(we, rel, file)
            return self._inline(entry, image)
        if self.pool is None:
            entry, image = read_entry(
                we.path,
                rel,
                we.name,
                file,
                within=self.within,
                include=self.include,
                reader_message=self.reader_message,
                formats=others,
            )
        else:
            params = {
                "path": we.path,
                "rel": rel,
                "name": we.name,
                "file": file,
                "within": self.within,
                "include": list(self.include),
                "reader_message": self.reader_message,
            }
            if others is not None:
                params["formats"] = others
            try:
                result = self.pool.call("listing_entry", params, timeout=self.file_timeout)
                entry, image = result.data, result.payload
            except Exception as exc:  # a worker that timed out or crashed is this entry's error
                return model.listing_entry(rel, "file", "error", file=file, error=self._error(exc))
        return self._inline(entry, image)

    def _inline(self, entry: dict[str, Any], image: bytes | None) -> dict[str, Any]:
        if self._deferred:  # the inline budget is spent in walk order, by _run
            return {**entry, _IMAGE: image}
        return self._inline_now(entry, image)

    def _inline_now(self, entry: dict[str, Any], image: bytes | None) -> dict[str, Any]:
        if image is not None and "preview_data" in self.include:
            chars = 4 * -(-len(image) // 3)
            if self.preview_data_capped or self._inline_chars + chars > self.max_preview_data_bytes:
                self.preview_data_capped = True
            else:
                self._inline_chars += model.inline_preview(entry, image)
        return entry

    # -- iteration -----------------------------------------------------------------
    def __iter__(self) -> Iterator[dict[str, Any]]:
        if self._started:
            raise RuntimeError("a Scan can be iterated once")
        self._started = True
        return self._run()

    def _wanted(self) -> Iterator[WalkEntry]:
        for we in self._walk:
            if not self._relevant(we):
                continue
            if self._after is not None and walk_order(we.rel) <= self._after:
                continue  # listed on an earlier page
            yield we

    def _entries(self) -> Iterator[tuple[WalkEntry, dict[str, Any] | None]]:
        """Each wanted walk entry and its listing entry, in walk order: read here one at
        a time, or with ``threads`` a few files ahead in a pool of threads."""
        if self.threads == 1:
            for we in self._wanted():
                yield we, (None if self._stop() else self._entry(we))
            return
        from concurrent.futures import ThreadPoolExecutor

        self._deferred = True
        pool = ThreadPoolExecutor(self.threads, thread_name_prefix="solidseas-listing")
        ahead: deque = deque()
        try:
            wanted = self._wanted()
            stats = self._walk.stats
            for we in wanted:
                ahead.append((we, pool.submit(self._entry, we), stats.folders))
                if len(ahead) >= self.threads * _AHEAD:
                    break
            while ahead:
                we, future, folders = ahead.popleft()
                if self._stop():
                    # The walk ran ahead of the entries: count the folders it had walked when
                    # it reached this entry, as a listing read one file at a time does.
                    self._folders_at = folders
                    yield we, None
                    return
                entry = future.result()
                if entry is not None:
                    entry = self._inline_now(entry, entry.pop(_IMAGE, None))
                yield we, entry
                nxt = next(wanted, None)
                if nxt is not None:
                    ahead.append((nxt, pool.submit(self._entry, nxt), stats.folders))
        finally:
            # A file still being read finishes in its thread; nothing waits for it.
            pool.shutdown(wait=False, cancel_futures=True)

    def _stop(self) -> bool:
        """Whether a bound stops the listing before its next entry (and says which)."""
        if self.max_entries is not None and self.counts["entries"] >= self.max_entries:
            self.truncated_reason = "max_entries"
            return True
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self.truncated_reason = "deadline"
            return True
        return False

    def _run(self) -> Iterator[dict[str, Any]]:
        counts = self.counts
        try:
            for we, entry in self._entries():
                if self.truncated_reason is not None:
                    return
                if entry is None:
                    continue
                counts["entries"] += 1
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
                self.last_rel = we.rel
                yield entry
            if self._walk.stats.truncated and self.truncated_reason is None:
                self.truncated_reason = self._walk.stats.truncated  # max_examined or deadline
        finally:
            counts["folders"] = self._walk.stats.folders if self._folders_at is None else self._folders_at

    def listing(self, *, cursor: Callable[[str], str] | None = None) -> dict[str, Any]:
        """The whole ``listing`` data: runs the scan to the end (or to a limit).

        ``cursor`` turns the walk path of the last entry into ``next_cursor`` when
        ``max_entries`` or the deadline stopped the listing (the REST service pages
        this way); without it, ``next_cursor`` is null."""
        entries = list(self)
        resumable = self.truncated_reason in ("max_entries", "deadline") and self.last_rel is not None
        return model.to_json_data(
            {
                "root": self.root_id,
                "folder": self.folder_rel,
                "recursive": self.recursive,
                "include": list(self.include),
                "entries": entries,
                "counts": dict(self.counts),
                "truncated": self.truncated_reason is not None,
                "truncated_reason": self.truncated_reason,
                "next_cursor": cursor(self.last_rel) if cursor is not None and resumable else None,
                "preview_data_capped": self.preview_data_capped,
            }
        )

    def fingerprint(self) -> str:
        """A SHA-256 of what this listing would cover, from the directory entries alone:
        each entry's path, kind, reason, size and modification time, up to
        ``max_entries`` after ``after``, and whether more follow. Nothing is opened.
        Consumes the scan: make a new one to list."""
        if self._started:
            raise RuntimeError("a Scan can be iterated once")
        self._started = True
        h = hashlib.sha256()
        n = 0
        for we in self._walk:
            if not self._relevant(we):
                continue
            if self._after is not None and walk_order(we.rel) <= self._after:
                continue
            if self.max_entries is not None and n >= self.max_entries:
                h.update(b"more")
                break
            n += 1
            row = (we.rel, we.kind, we.reason, we.is_dir, we.size, we.mtime_ns)
            h.update(repr(row).encode("utf-8", "replace"))
            h.update(b"\n")
        h.update(repr(self._walk.stats.truncated).encode("ascii"))
        return h.hexdigest()


def scan(folder: str | os.PathLike, **options: Any) -> Scan:
    """List the SOLIDWORKS documents in ``folder`` (see :class:`Scan` for the options), or
    with ``formats`` the 3D files of other formats too (see the module notes).

    ``recursive`` (default False) walks subfolders, up to ``max_depth`` levels; when
    it is False, subfolders are entries of their own. ``include`` picks the
    optional parts of each entry from ``properties``, ``configurations``,
    ``preview`` (the default: the summary's preview object) and ``preview_data``
    (the image itself, base64, up to ``max_preview_data_bytes`` of text in all).
    ``max_entries`` (entries listed), ``max_examined`` (directory entries the
    walker looks at, documents or not; one million by default) and
    ``max_seconds`` stop the listing early, with ``truncated_reason`` saying
    which: ``max_entries``, ``max_examined`` or ``deadline``. All three are
    checked between entries.
    """
    return Scan(folder, **options)


__all__ = [
    "MAX_PREVIEW_DATA_BYTES",
    "Scan",
    "read_entry",
    "read_model_entry",
    "scan",
    "sniff_format",
    "walk_order",
]
