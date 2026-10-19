"""``VERSION`` and ``CONSTITUENTS``: which Alibre Design document this is, and which
documents an assembly is made of (provisional, ``docs/formats/alibre.md``).

``VERSION`` holds one string with a big-endian 16-bit length: an XML element
``<Repository Guid=... Name=... V3Name=... Type=.../>``, then a colon and the
document's repository path (forward slashes, no extension), a vertical bar and
the document GUID, two vertical bars and an integer, a vertical bar and the
document's version. ``CONSTITUENTS`` holds one such string per document an
assembly references (one or more ``Repository`` elements, then the same fields,
then more text that is not read).

The repository path is the user's own data (it names folders on the machine
that saved the file): it is kept for the references and never written into a
warning's text.
"""

import re
import struct
from dataclasses import dataclass

from ...errors import SldFormatError
from .._source import xml_tree
from ..limits import Limits

GUID = re.compile(r"\{?([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\}?\Z")
_ELEMENTS = re.compile(r"(?:<Repository\b[^<>]*/>)+")
_FIELDS = re.compile(r":(?P<path>[^|]*)\|(?P<guid>[^|]*)\|\|(?P<a>-?\d+)\|(?P<version>-?\d+)")


@dataclass(frozen=True)
class DocumentIdentity:
    """A document's GUID (lower case, no braces), its version, its repository path and
    the attributes of its first ``Repository`` element."""

    guid: str
    version: int | None
    path: str | None
    repository: dict

    @property
    def name(self) -> str | None:
        """The last component of the repository path: the document's stored name."""
        if not self.path:
            return None
        return self.path.rstrip("/").rsplit("/", 1)[-1] or None


def normal_guid(text: str) -> str | None:
    m = GUID.match(text.strip())
    return m.group(1).lower() if m else None


def parse(text: str, limits: Limits, *, whole: bool) -> DocumentIdentity:
    """One identity string (see the module notes). ``whole``: nothing may follow the
    version (``VERSION``); otherwise more text may (``CONSTITUENTS``)."""
    m = _ELEMENTS.match(text)
    if m is None:
        raise SldFormatError("an identity string does not start with its Repository element")
    first = re.match(r"<Repository\b[^<>]*/>", text).group(0)
    attrs = dict(xml_tree(first.encode("utf-8"), limits, max_nodes=1, namespaces=False).attrs)
    rest = text[m.end() :]
    f = _FIELDS.match(rest)
    if f is None or (whole and f.end() != len(rest)):
        raise SldFormatError("an identity string is not the path, GUID and version an Alibre document stores")
    guid = normal_guid(f.group("guid"))
    if guid is None:
        raise SldFormatError("an identity string's GUID is not a GUID")
    try:
        version = int(f.group("version"))
    except ValueError:
        version = None
    return DocumentIdentity(guid, version, f.group("path") or None, attrs)


def _strings(data: bytes, limits: Limits, stream: str):
    i, n = 0, len(data)
    count = 0
    while i < n:
        if i + 2 > n:
            raise SldFormatError(f"{stream} ends inside a length", detail={"stream": stream})
        (k,) = struct.unpack_from(">H", data, i)
        if i + 2 + k > n:
            raise SldFormatError(f"a string of {stream} runs past the stream", detail={"stream": stream})
        yield data[i + 2 : i + 2 + k].decode("utf-8", "replace")
        i += 2 + k
        count += 1
        if count > limits.references:
            raise limits.exceeded("references", f"{stream} names more than {limits.references:,} documents")


def read_version(data: bytes, limits: Limits) -> DocumentIdentity:
    """The identity in a ``VERSION`` stream: exactly one string."""
    strings = list(_strings(data, limits, "VERSION"))
    if len(strings) != 1:
        raise SldFormatError("VERSION does not hold exactly one string", detail={"stream": "VERSION"})
    return parse(strings[0], limits, whole=True)


def read_constituents(data: bytes, limits: Limits) -> list[DocumentIdentity]:
    """The identities a ``CONSTITUENTS`` stream lists, in order."""
    return [parse(s, limits, whole=False) for s in _strings(data, limits, "CONSTITUENTS")]


__all__ = ["GUID", "DocumentIdentity", "normal_guid", "parse", "read_constituents", "read_version"]
