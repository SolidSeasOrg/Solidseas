"""Which document a file is: its creation time, compared with the one its referencing
document stored.

An assembly stores each referenced file's ``swCreationTime`` (Unix seconds) in
its component tree, and a drawing stores its model's in the ``Header2``
reference record. A part or an assembly carries the same value about itself, in
three places that agree wherever a corpus file has more than one
(``docs/FORMAT.md`` 11.7 has the counts):

* ``ModelStamps``, element 0 (a u32), read first because it is a 12-byte
  stream;
* its own ``swFile`` in its component tree (``Features`` for a part,
  ``COMPINSTANCETREE`` for an assembly);
* the ``id`` of the root element of ``swXmlContents/KeyWords``.

**A drawing is different.** Its ``ModelStamps`` and ``KeyWords`` id hold the
identity stored in the drawing template it was made from, not its own creation time:
every drawing made from one template carries the same value, so for a drawing
:func:`own_identity` names the template lineage, never the drawing itself
(VERIFIED on fixtures o18 and o19 and on the corpus, FORMAT 11.7).
Nothing resolves a drawing as a candidate today; anything that would must not
treat this value as the drawing's own.

Save As keeps the creation time, so it identifies a lineage (the original and
its Save As and Explorer copies), not one file: a strong veto against an
unrelated file that shares a name, a weak picker between copies.

A creation time of 0, a negative one, or one later than now plus one day is
unknown (``falsy-zero-defaults``: unknown is None, never 0), and values are
compared as integers, never through a local time.

Nothing here opens a file: :mod:`.gateway` opens the document and hands it in.
"""

import struct
import time
from dataclasses import dataclass

IDENTITY_STATES = ("match", "differ", "unknown")
_DAY = 86_400
_MAX_DIGITS = 12


def parse_creation_time(value, *, now: float | None = None) -> int | None:
    """A stored creation time as Unix seconds, or None when it is absent, not a whole
    number, 0, negative or later than now plus one day."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > _MAX_DIGITS or not text.isascii() or not text.isdigit():
            return None
        value = int(text)
    if not isinstance(value, int) or value <= 0:
        return None
    limit = (time.time() if now is None else now) + _DAY
    return value if value <= limit else None


@dataclass(frozen=True)
class Identity:
    """What a candidate file says about itself. ``creation_time`` is None when it is
    unknown; ``source`` names the carrier it came from. ``error`` is the error code
    when the file could not be read, ``placeholder`` True for a cloud file that was
    deliberately not opened, and ``skipped`` True when a limit stopped the read."""

    creation_time: int | None
    source: str | None = None
    error: str | None = None
    placeholder: bool = False
    skipped: bool = False


def own_identity(doc) -> Identity:
    """The creation time an open document stores about itself."""
    c = doc.container
    if "ModelStamps" in c:
        try:
            data = doc.read_stream("ModelStamps")
        except Exception:  # a damaged stream: fall back on the other carriers
            data = b""
        if len(data) >= 4:
            ct = parse_creation_time(struct.unpack_from("<I", data, 0)[0])
            if ct is not None:
                return Identity(ct, "ModelStamps")
    md = doc.metadata
    own = md.own_file_ids
    if len(own) == 1:
        fid = next(iter(own))
        ct = parse_creation_time((md.tree.get("files", {}).get(fid) or {}).get("creation_time"))
        if ct is not None:
            return Identity(ct, "tree")
    ct = parse_creation_time(md.keywords_id)
    if ct is not None:
        return Identity(ct, "keywords")
    return Identity(None)


def compare(stored: int | None, own: Identity | None) -> str:
    """``match``, ``differ`` or ``unknown``."""
    if stored is None or own is None or own.creation_time is None:
        return "unknown"
    return "match" if stored == own.creation_time else "differ"


__all__ = ["IDENTITY_STATES", "Identity", "compare", "own_identity", "parse_creation_time"]
