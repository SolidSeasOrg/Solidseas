"""The Alibre Design container: an MS-CFB (OLE) compound file whose streams sit at the
root under fixed names (provisional, ``docs/formats/alibre.md``).

:func:`open_container` opens one over a document's :class:`~.._source.Source`
with SolidSeas' hardened ``OleContainer`` (chain and size checks, partial reads)
and checks that it is an Alibre Design file: ``VERSION``, ``PROP_DATA`` and
``STEP_DATA`` at the root, and ``ALIBRE_SCHEMA`` among the schemas the header of
``STEP_DATA`` names. :meth:`AlibreContainer.read` reads one stream within its
bound, and checks the content signature of the streams that have one
(``ACIS BinaryFile`` for ``SAB_DATA``, ``ISO-10303-21;`` for ``STEP_DATA``, and for
``MESH_DATA`` an entry count followed by the key ``SCHEMA_VERSION_KEY``).
"""

import re

from ...errors import SldFormatError, StreamNotFoundError, UnknownFormatError
from .._source import Source
from ..limits import Limits
from ..solidworks.ole import OleContainer

REQUIRED = ("VERSION", "PROP_DATA", "STEP_DATA")
SMALL_STREAMS = frozenset(
    {
        "VERSION",
        "LIGHT_CONFIGURATION_DATA",
        "AUTOGRAPH_DATA",
        "DESIGN_PARAMETER_DATA",
        "HOLE_OPERATIONS_DATA",
        "EXTERNAL_THREAD_OPERATIONS_DATA",
        "CUSTOM_ITEM_PROP_DATA",
        "STANDARD_DESIGN_PROP_DATA",
    }
)
TEXT_STREAMS = frozenset({"PROP_DATA", "STEP_DATA"})
SIGNATURES = {
    "SAB_DATA": (b"ACIS BinaryFile", b"ASM BinaryFile4"),
    "STEP_DATA": (b"ISO-10303-21;",),
}
MESH_SIGNATURE = b"\x12\x00\x00\x00SCHEMA_VERSION_KEY"
_SCHEMA = re.compile(rb"FILE_SCHEMA\s*\(\s*\(([^)]*)\)\s*\)\s*;", re.S)
HEADER_PEEK = 64 << 10


class AlibreContainer:
    """An open Alibre Design compound file (see the module notes)."""

    def __init__(self, ole: OleContainer, limits: Limits) -> None:
        self.ole = ole
        self.limits = limits
        self.names = {s.name for s in ole.streams()}
        self.sizes = {s.name: s.size for s in ole.streams()}

    def close(self) -> None:
        self.ole.close()

    def has(self, name: str) -> bool:
        return name in self.names

    def bound(self, name: str) -> tuple[int, str]:
        """``(bytes, limit name)`` a stream may hold."""
        lim = self.limits
        if name in SMALL_STREAMS:
            return lim.alibre_small_stream_bytes, "alibre_small_stream_bytes"
        if name == "CONSTITUENTS":
            return lim.alibre_constituents_bytes, "alibre_constituents_bytes"
        if name in TEXT_STREAMS:
            return lim.alibre_text_stream_bytes, "alibre_text_stream_bytes"
        return lim.alibre_stream_bytes, "alibre_stream_bytes"

    def read(self, name: str) -> bytes:
        """A whole stream, within its bound and checked against its signature."""
        if name not in self.names:
            raise StreamNotFoundError(f"no stream named {name!r}", detail={"stream": name})
        cap, which = self.bound(name)
        size = self.sizes[name]
        if size > cap:
            raise self.limits.exceeded(
                which, f"{name} is {size:,} bytes, more than the {cap:,} allowed", size
            )
        data = self.ole.read_raw(name, max_bytes=cap)
        self._check_signature(name, data)
        return data

    def peek(self, name: str, n: int) -> bytes:
        """The first ``n`` bytes of a stream (fewer when it is shorter), signature checked."""
        if name not in self.names:
            raise StreamNotFoundError(f"no stream named {name!r}", detail={"stream": name})
        data = self.ole.peek(name, min(n, self.sizes[name]))
        self._check_signature(name, data)
        return data

    def _check_signature(self, name: str, head: bytes) -> None:
        if name == "MESH_DATA":
            # an entry count, then the first key: SCHEMA_VERSION_KEY (its length 18 first)
            if len(head) >= 26 and head[4:26] != MESH_SIGNATURE:
                raise SldFormatError(f"{name} does not start as that stream does", detail={"stream": name})
            return
        sigs = SIGNATURES.get(name)
        if sigs is None:
            return
        want = max(len(s) for s in sigs)
        if len(head) < min(len(s) for s in sigs) or not any(head.startswith(s) for s in sigs):
            if len(head) < want and any(s.startswith(head) for s in sigs) and head:
                return  # a peek shorter than the signature
            raise SldFormatError(f"{name} does not start as that stream does", detail={"stream": name})


def schemas(head: bytes) -> list[str] | None:
    """The schema names in a Part 21 header's ``FILE_SCHEMA``, upper case; None when the
    head holds none."""
    m = _SCHEMA.search(head)
    if m is None:
        return None
    return [s.decode("latin-1").strip().upper() for s in re.findall(rb"'((?:[^']|'')*)'", m.group(1))]


def open_container(source: Source, limits: Limits) -> AlibreContainer:
    """The Alibre container of ``source``; ``UnknownFormatError`` when the file is a
    compound file of another program (see the module notes)."""
    ole = OleContainer(source.file(), source.size, None, True, 0)
    if len(ole.streams()) > limits.ole_streams:
        n = len(ole.streams())
        ole.close()
        raise limits.exceeded(
            "ole_streams", f"the file holds {n:,} streams, more than the {limits.ole_streams} allowed", n
        )
    c = AlibreContainer(ole, limits)
    try:
        missing = [n for n in REQUIRED if n not in c.names]
        if missing:
            raise UnknownFormatError(
                "the compound file is not an Alibre Design document (it lacks the streams one holds)",
                detail={"rule": "unidentified"},
            )
        head = c.peek("STEP_DATA", HEADER_PEEK)
        end = head.find(b"ENDSEC")
        found = schemas(head[: end if end >= 0 else len(head)])
        if found is None:
            if end < 0 and len(head) >= min(HEADER_PEEK, limits.p21_header_bytes):
                raise limits.exceeded("p21_header_bytes", "the design database's header is too long")
            raise UnknownFormatError(
                "the compound file is not an Alibre Design document (its design database names no schema)",
                detail={"rule": "unidentified"},
            )
        if "ALIBRE_SCHEMA" not in found:
            raise UnknownFormatError(
                "the compound file is not an Alibre Design document (its design database is another schema)",
                detail={"rule": "unidentified"},
            )
    except BaseException:
        c.close()
        raise
    return c


__all__ = ["MESH_SIGNATURE", "REQUIRED", "SIGNATURES", "AlibreContainer", "open_container", "schemas"]
