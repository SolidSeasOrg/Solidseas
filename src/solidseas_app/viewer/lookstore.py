"""Each document's looks in the 3D view, kept from one run of the viewer to the next.

What the user chose to see of an assembly in the 3D view (:mod:`.preview`): the
components hidden or made transparent (:class:`.appearance.Looks`) and the
sub-assemblies chosen to explode or stay together (:mod:`.explode`). The preview pane
keeps them in a :class:`LookStore` for each document it shows, so they come back when
the document is shown again. A store made with a path also keeps them in that file,
``SolidSeas\\ViewerLooks.json`` beside ``Viewer.ini`` (:func:`path_beside`), never next to
a document, for the next run; one made with none keeps them in memory only (the tests',
the self-test's).

A document is kept under a digest of its path, with its name when it is stored inside
another file (:func:`document_id`), so the file names no path. It keeps the
:data:`MAX_DOCUMENTS` documents changed last, and a document left with nothing chosen
(Reset appearance) is dropped. The file is read when first asked and written through a
temporary file and a rename when :meth:`LookStore.flush` is called (the window does a
moment after a change, and when it closes), with the documents changed here put over
what the file holds then, so two viewers open at once keep each other's changes. Every
value read back is checked: a file that is damaged, too large or of another version is
taken as empty and replaced at the next write, and a choice that does not check out is
left out, so a hand-edited file never stops the viewer. Nothing here raises, and
nothing here imports Qt.
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from typing import Any

from .appearance import HIDDEN, KINDS, MAX_TRANSPARENCY, TRANSPARENCY

FILE_NAME = "ViewerLooks.json"
VERSION = 1
MAX_DOCUMENTS = 200  # the documents changed last
MAX_FILE_BYTES = 4 << 20  # a file larger than this is not one of ours
MAX_CHOICES = 2000  # a document's looks: each is one scope's hidden or transparency
MAX_SWITCHES = 2000  # a document's sub-assemblies chosen to explode or stay together
MAX_TEXT = 4096  # characters of a component tree id or a file key
_ID = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SEQ = 2**53


def path_beside(settings_path: str) -> str:
    """The file kept beside the viewer's settings file ``settings_path``."""
    return os.path.join(os.path.dirname(settings_path), FILE_NAME)


def document_id(key: Any) -> str | None:
    """The id a document's looks are kept under, from the preview pane's
    ``document_key`` (``(path, path below the opened folder)``): a digest of its path as
    the system compares names, and of the name it is shown under when that is not the
    file's own (a virtual component, stored inside its assembly's file). None for none."""
    if not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str) or not key[0]:
        return None
    path, shown = key
    ident = os.path.normcase(os.path.abspath(path))
    name = shown.rpartition("/")[2] if isinstance(shown, str) else ""
    if name and name != os.path.basename(path):
        ident += "\n" + name
    return hashlib.sha256(ident.encode("utf-8", "surrogatepass")).hexdigest()


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < _MAX_SEQ


def _looks(raw: Any) -> dict[str, Any] | None:
    """``raw``, a :meth:`.appearance.Looks.state` read back, with every choice that does
    not check out left out; None when none is left."""
    if not isinstance(raw, dict) or not isinstance(raw.get("choices"), list):
        return None
    choices = []
    for c in raw["choices"][:MAX_CHOICES]:
        if not isinstance(c, list) or len(c) != 5:
            continue
        kind, value, prop, v, seq = c
        if kind not in KINDS or not isinstance(value, str) or len(value) > MAX_TEXT or not _whole(seq):
            continue
        if prop == HIDDEN and isinstance(v, bool):
            choices.append([kind, value, prop, v, seq])
        elif prop == TRANSPARENCY and _whole(v) and v <= MAX_TRANSPARENCY:
            choices.append([kind, value, prop, v, seq])
    if not choices:
        return None
    seq = raw.get("seq")
    return {"seq": seq if _whole(seq) else 0, "choices": choices}


def _switches(raw: Any) -> dict[str, bool]:
    """``raw``, the sub-assemblies' explode switches read back, those that check out."""
    out: dict[str, bool] = {}
    if isinstance(raw, dict):
        for ident, on in raw.items():
            if len(out) >= MAX_SWITCHES:
                break
            if isinstance(ident, str) and 0 < len(ident) <= MAX_TEXT and isinstance(on, bool):
                out[ident] = on
    return out


def clean(state: Any) -> dict[str, Any] | None:
    """A document's ``{"looks", "explode"}`` (:meth:`.preview.PreviewPane.view_state`)
    with what does not check out left out; None when nothing is chosen."""
    if not isinstance(state, dict):
        return None
    looks, switches = _looks(state.get("looks")), _switches(state.get("explode"))
    if looks is None and not switches:
        return None
    return {"looks": looks, "explode": switches}


def _keep(docs: dict[str, dict[str, Any]], ident: str, state: dict[str, Any] | None) -> None:
    """Put ``state`` in ``docs`` for ``ident`` as the one changed last (None: drop it), and
    drop the oldest past :data:`MAX_DOCUMENTS`."""
    docs.pop(ident, None)
    if state is not None:
        docs[ident] = state
        while len(docs) > MAX_DOCUMENTS:
            docs.pop(next(iter(docs)))


class LookStore:
    """The looks of the documents shown, by :func:`document_id` (see the module notes):
    in the file at ``path``, or in memory only when it is None. ``on_change`` is called
    when a document's looks change and the file has something to write."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.on_change: Callable[[], None] | None = None
        self.write_failed = False
        self._docs: dict[str, dict[str, Any]] | None = None  # the one changed last comes last
        # The documents changed here since the last write, each with its state (None:
        # forgotten), the one changed last last: what a write adds to the file's own.
        self._changed: dict[str, dict[str, Any] | None] = {}

    @property
    def dirty(self) -> bool:
        """Whether the file lacks a change made here."""
        return bool(self._changed)

    def _loaded(self) -> dict[str, dict[str, Any]]:
        if self._docs is None:
            self._docs = self._read() if self.path else {}
        return self._docs

    def _read(self) -> dict[str, dict[str, Any]]:
        assert self.path is not None
        try:
            with open(self.path, "rb") as fh:
                data = fh.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                return {}
            raw = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RecursionError):
            return {}
        if not isinstance(raw, dict) or raw.get("version") != VERSION:
            return {}
        if not isinstance(raw.get("documents"), list):
            return {}
        docs: dict[str, dict[str, Any]] = {}
        for doc in reversed(raw["documents"][:MAX_DOCUMENTS]):  # the file lists the latest first
            if not isinstance(doc, dict) or not isinstance(doc.get("id"), str) or not _ID.match(doc["id"]):
                continue
            state = clean(doc)
            if state is not None:
                docs.pop(doc["id"], None)
                docs[doc["id"]] = state
        return docs

    def get(self, ident: str | None) -> dict[str, Any] | None:
        """The ``{"looks", "explode"}`` kept for the document ``ident``, a copy, or None."""
        state = self._loaded().get(ident) if ident else None
        if state is None:
            return None
        return json.loads(json.dumps(state))

    def put(self, ident: str | None, state: Any) -> None:
        """Keep ``state`` (``{"looks", "explode"}``) for the document ``ident``, as the one
        changed last; with nothing chosen, forget the document."""
        if not ident:
            return
        docs = self._loaded()
        kept = clean(state)
        if kept == docs.get(ident):
            return
        _keep(docs, ident, kept)
        if self.path is not None:
            self._changed.pop(ident, None)
            self._changed[ident] = kept
            if self.on_change is not None:
                self.on_change()

    def flush(self) -> bool:
        """Write what changed here to the file, over what the file holds now, so the
        changes another viewer wrote meanwhile are kept; True when the file has them all
        (or there is no file). A failed write leaves the file as it was, keeps the
        changes for the next one and sets ``write_failed``."""
        if not self._changed or self.path is None:
            return True
        merged = self._read()
        for ident, state in self._changed.items():
            _keep(merged, ident, state)
        docs = list(reversed(merged.items()))  # the latest first
        while True:
            # Escaped to ASCII: a name with a character UTF-8 cannot hold still reads back.
            text = json.dumps(
                {"version": VERSION, "documents": [{"id": ident, **state} for ident, state in docs]},
                separators=(",", ":"),
            )
            data = text.encode("ascii")
            if len(data) <= MAX_FILE_BYTES or not docs:
                break
            docs = docs[: len(docs) * 3 // 4]  # the oldest go first
        ok = self._write(data)
        if ok:
            self._changed.clear()
            self._docs = dict(reversed(docs))  # with what the other viewer changed
        self.write_failed = self.write_failed or not ok
        return ok

    def _write(self, data: bytes) -> bool:
        assert self.path is not None
        tmp = None
        try:
            folder = os.path.dirname(self.path)
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="ViewerLooks.", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, self.path)
            tmp = None
            return True
        except OSError:
            return False
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
