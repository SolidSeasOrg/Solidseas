"""Parts' tessellations kept from one call to the next (provisional).

Tessellating a part's Parasolid bodies (:mod:`solidseas.tessellate`) is the slowest read
SolidSeas makes: seconds for a large part, tens of seconds for an assembly whose parts
saved no display mesh, and all of it again each time the assembly is read. A
:class:`TessellationCache` keeps what a tessellation gave, so the next call that needs
the same triangles takes them at once. :func:`solidseas.geometry.display_geometry` takes
one as ``brep_cache`` for its ``brep`` source, and SolidSeas Viewer's mesh process keeps
one while it runs, so showing an assembly again, another configuration of it, another
assembly with the same parts or one of those parts on its own tessellates no part twice.

An entry is keyed by what the part's document holds, never by its name or its time: a
digest of every stream in it, as stored (nothing is decompressed for it), the
configuration asked for and every setting that changes the triangles. A file saved
again is a new key, so it is read and tessellated again, and a copy of the file in
another folder finds the same entry. Only a whole result is kept: none that a limit
stopped (``truncated``), and none with a face left out for a reason that depends on the
time the tessellation was given or that this module does not know
(:data:`KEPT_REASONS`), since another call could do better.

The cache is bounded by the bytes its entries hold and lets the least recently used go
first; an entry larger than the bound is not kept, nor a document larger than
:data:`MAX_DIGEST_BYTES`. It stands outside the tessellator: the key is what goes in, the
entry what came out, and nothing in between is touched. Entries are shared by every
call that takes them, so a caller never changes a mesh it was given. One cache may be
used from several threads.
"""

import hashlib
import threading
import weakref
from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import InvalidArgumentError, ReaderWarning
from .formats.solidworks.mesh import Mesh

DEFAULT_MAX_BYTES = 256 << 20
# A document whose streams hold more than this, as stored, is not cached: reading it
# whole for its digest would cost more than it saves, and a crafted one could hold
# anything up to its file's size.
MAX_DIGEST_BYTES = 512 << 20
# The reasons a face is left out (solidseas.tessellate.REASONS) that do not depend on
# the time a tessellation had: a result whose faces were left out only for these is
# the one any later call would give, so it is kept. ``max_seconds`` (a blend the time
# ran out on) and ``fit_failed`` (a blend whose fit may also have run out of its share
# of the time) are not: more time could do those faces. A reason the tessellator gains
# later is not kept until it is listed here.
KEPT_REASONS = frozenset(
    {
        "unsupported_surface",
        "unsupported_curve",
        "orientation_conflict",
        "seam_configuration",
        "no_boundary",
        "inversion_failed",
        "triangulation_failed",
        "edge_too_long",
        "max_face_points",
        "bad_reference",
        "bad_geometry",
        "non_finite",
        "degenerate",
    }
)
# What an entry costs beside its arrays: its own objects, and each face record of its
# mesh (measured at about 140 bytes).
ENTRY_BYTES = 1024
FACE_BYTES = 160


@dataclass(frozen=True)
class CachedTessellation:
    """What a part's tessellation left for the next call. ``configuration`` is the one
    whose bodies were tessellated (the active one's when the one asked for stores none),
    ``stream`` the stream that held the first body, ``mesh`` the triangles,
    ``warnings`` those the ``brep`` source of display geometry gives with them,
    ``chord_m`` the chord tolerance and ``welded`` the triangles over shared vertices
    (with ``keep_welded``, else None). An entry made by a plain tessellation of a part,
    outside display geometry, has ``stream`` and ``warnings`` None: it serves a part
    drawn on its own, and the ``brep`` source makes it again whole."""

    configuration: str | None
    stream: str | None
    mesh: Mesh
    warnings: tuple[ReaderWarning, ...] | None
    chord_m: float
    welded: tuple[Any, Any] | None = None

    @property
    def nbytes(self) -> int:
        """Roughly what the entry holds in memory."""
        m = self.mesh
        n = ENTRY_BYTES + FACE_BYTES * len(m.faces)
        for a in (m.positions, m.normals, m.triangles, *(self.welded or ())):
            n += len(a) * a.itemsize
        return n


def settings_key(
    options: Mapping[str, Any] | None = None,
    body_types: Collection[str] = ("solid", "sheet"),
    include_hidden: bool = True,
    keep_welded: bool = False,
) -> tuple:
    """The settings that change a part's triangles, as a key: the tessellation options
    (``chord_m``, ``angle_deg`` and the others, as given), the body types, whether
    hidden bodies are included and whether the shared-vertex triangles are kept. The
    limits (``max_seconds``, ``max_triangles``) are not part of it: a result one of them
    stopped is never kept. The defaults are those of ``Document.tessellate()`` and of
    the ``brep`` source given no ``brep_options``."""
    return (
        tuple(sorted((str(k), v) for k, v in (options or {}).items())),
        tuple(sorted(body_types)),
        bool(include_hidden),
        bool(keep_welded),
    )


DEFAULT_SETTINGS = settings_key()


def keepable(tessellation) -> bool:
    """Whether a :class:`solidseas.tessellate.Tessellation` is one any later call with
    the same document, configuration and settings would give: it has triangles, no
    limit stopped it, and every face it left out was left out for a reason of
    :data:`KEPT_REASONS`."""
    return (
        tessellation is not None
        and tessellation.mesh.n_triangles > 0
        and not tessellation.truncated
        and all(reason in KEPT_REASONS for reason in tessellation.reasons)
    )


def document_digest(doc, max_bytes: int | None = None) -> str | None:
    """A digest of what ``doc`` holds: its container's generation, then every stream in
    directory order, its name, how it is stored (its codec and decoded size) and its
    bytes as stored, which together decide what it decodes to. None when the streams
    hold more than ``max_bytes`` together (:data:`MAX_DIGEST_BYTES` by default), or one
    cannot be read: such a document is not cached."""
    limit = MAX_DIGEST_BYTES if max_bytes is None else max_bytes
    try:
        streams = doc.streams()
        stored = sum(s.compressed_size if s.compressed_size is not None else s.size for s in streams)
        if stored > limit:
            return None
        h = hashlib.sha256(doc.format.encode("ascii", "replace") + b"\0")
        for s in streams:
            data = doc.read_stream(s.name, raw=True)
            head = f"{s.name}\0{s.codec}\0{s.size}\0{len(data)}".encode("utf-8", "surrogatepass")
            h.update(len(head).to_bytes(4, "little"))
            h.update(head)
            h.update(data)
    except MemoryError:
        raise
    except Exception:  # a stream that cannot be read: the document is read as it would be
        return None
    return h.hexdigest()


class TessellationCache:
    """Parts' tessellations by what their documents hold (see the module docstring), at
    most ``max_bytes`` of them, the least recently used going first. ``hits``,
    ``misses``, ``kept``, ``dropped`` (entries let go for room) and ``refused`` (results
    not kept: cut short, or too large) count what happened."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise InvalidArgumentError(
                "max_bytes must be a whole number of at least 0", detail={"parameter": "max_bytes"}
            )
        self.max_bytes = max_bytes
        self._entries: OrderedDict[tuple, CachedTessellation] = OrderedDict()
        self._sizes: dict[tuple, int] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        # Each open document's digest, read once however many configurations of it are
        # asked for, and forgotten with the document.
        self._digests: weakref.WeakKeyDictionary[Any, str | None] = weakref.WeakKeyDictionary()
        self.hits = self.misses = self.kept = self.dropped = self.refused = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def nbytes(self) -> int:
        """What the entries hold, roughly, in bytes."""
        with self._lock:
            return self._bytes

    def key(self, doc, configuration: str | None, settings: tuple = DEFAULT_SETTINGS) -> tuple | None:
        """The key of ``doc``'s bodies in ``configuration`` (a name, None for the active
        one) tessellated with ``settings`` (:func:`settings_key`), or None when ``doc``
        is not cached (:func:`document_digest`). A configuration is keyed by the name
        the document resolves it to, so None and the active one's name share an entry.
        Never raises for what the document holds: a read goes on without the cache."""
        try:
            container = doc.container
            with self._lock:
                digest = self._digests.get(container, False)
            if digest is False:
                digest = document_digest(doc)
                with self._lock:
                    self._digests[container] = digest
        except MemoryError:
            raise
        except Exception:  # a document the cache cannot key: read as it would be without it
            return None
        if digest is None:
            return None
        name = configuration
        try:
            found = doc.configuration(configuration)
            if found is not None and found.name is not None:
                name = found.name
        except MemoryError:
            raise
        except Exception:  # an unknown name: kept as it was asked for
            pass
        return (digest, name, settings)

    def get(self, key: tuple | None, *, whole: bool = False) -> CachedTessellation | None:
        """The entry under ``key``, now the most recently used; None when there is none,
        and with ``whole`` when the entry is a plain tessellation's (``warnings`` None),
        which the ``brep`` source of display geometry makes again."""
        if key is None:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or (whole and entry.warnings is None):
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry

    def put(self, key: tuple | None, entry: CachedTessellation) -> bool:
        """Keep ``entry`` under ``key``, letting the least recently used entries go for
        room; False (and nothing kept) when it alone is larger than the bound."""
        if key is None:
            return False
        size = entry.nbytes
        with self._lock:
            if size > self.max_bytes:
                self.refused += 1
                return False
            if key in self._entries:
                self._bytes -= self._sizes.pop(key)
                del self._entries[key]
            while self._entries and self._bytes + size > self.max_bytes:
                old, _ = self._entries.popitem(last=False)
                self._bytes -= self._sizes.pop(old)
                self.dropped += 1
            self._entries[key] = entry
            self._sizes[key] = size
            self._bytes += size
            self.kept += 1
            return True

    def refuse(self) -> None:
        """Count a result that was not kept (cut short, or with faces left out for want of
        time)."""
        with self._lock:
            self.refused += 1

    def clear(self) -> None:
        """Let every entry go (the counts stay)."""
        with self._lock:
            self._entries.clear()
            self._sizes.clear()
            self._bytes = 0
            self._digests = weakref.WeakKeyDictionary()

    def stats(self) -> dict[str, int]:
        """The counts and the size, for a report."""
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
                "hits": self.hits,
                "misses": self.misses,
                "kept": self.kept,
                "dropped": self.dropped,
                "refused": self.refused,
            }


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_SETTINGS",
    "KEPT_REASONS",
    "MAX_DIGEST_BYTES",
    "CachedTessellation",
    "TessellationCache",
    "document_digest",
    "keepable",
    "settings_key",
]
