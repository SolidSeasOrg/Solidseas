"""The format registry: every 3D file format SolidSeas knows, and how a file is told
apart from the others (provisional).

:data:`FORMATS` holds one :class:`FormatSpec` per format: its id, display name,
extensions, family, what its documents usually hold, its capabilities, the
dotted path of its reader (None for a format that is listed but not read), the
axis that points up in its Home view and its media type. A reader is imported
only when a document of its format is opened: :func:`readable` asks whether its
module exists without importing it, so a listing process can say which files
are readable without loading any reader.

:func:`detect` decides a file's format from its first 4 KiB, its size and its
name (``docs/API.md`` 3.20.3): the extension's own format when that format's
content test accepts the head, else the first content test that accepts it in a
fixed order, else the extension's format, whose reader will then refuse the
content. Content and extension that disagree give ``mismatch``; the content
wins. Every content test lives here, so detection never imports a reader.

Every entry is written here once, the reader paths of modules that arrive later
included: a reader joins by its module appearing, never by an edit to this file.
"""

import importlib
import importlib.util
import os
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .solidworks.container import MODERN_MAGIC, OLE_MAGIC

HEAD_BYTES = 4096

CAPABILITIES = frozenset(
    {
        "metadata",
        "mesh",
        "brep",
        "components",
        "properties",
        "stored_preview",
        "units",
        "colors",
        "external_references",
    }
)
FAMILIES = ("solidworks", "mesh", "exchange", "native")
KINDS = ("mesh", "brep", "mixed")


@dataclass(frozen=True)
class FormatSpec:
    """One file format. ``id`` is an open set of short names (``stl``, ``3mf``,
    ``step``...). ``reader`` is ``"module:function"``, the function that opens a
    document of this format (``open(source, *, name, path, file_info, limits,
    hold_open, detection)``), or None for a format SolidSeas lists but cannot read.
    ``signature`` is the content test an extension shared with other programs needs
    before a file is listed as this format (``ole``), and ``needs_signature`` says
    which extensions need it."""

    id: str
    name: str
    extensions: tuple[str, ...]
    family: str
    kind: str
    capabilities: frozenset = field(default_factory=frozenset)
    reader: str | None = None
    up_axis: str = "z"
    mime: str | None = None
    needs_signature: tuple[str, ...] = ()
    signature: str | None = None

    @property
    def module(self) -> str | None:
        return self.reader.split(":", 1)[0] if self.reader else None


def _caps(*names: str) -> frozenset:
    unknown = set(names) - CAPABILITIES
    if unknown:
        raise ValueError(f"unknown capabilities {sorted(unknown)}")
    return frozenset(names)


_MESH_CAPS = ("mesh", "units")
FORMATS: dict[str, FormatSpec] = {
    f.id: f
    for f in (
        FormatSpec(
            "solidworks",
            "SOLIDWORKS",
            (".sldprt", ".sldasm", ".slddrw"),
            "solidworks",
            "brep",
            _caps(
                "metadata",
                "mesh",
                "brep",
                "components",
                "properties",
                "stored_preview",
                "units",
                "external_references",
            ),
            "solidseas.formats.solidworks:open_document",
            "y",
        ),
        FormatSpec(
            "stl",
            "STL",
            (".stl",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "metadata"),
            "solidseas.formats.stl:open",
            "z",
            "model/stl",
        ),
        FormatSpec(
            "3mf",
            "3MF",
            (".3mf",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "metadata", "components", "properties", "stored_preview", "colors"),
            "solidseas.formats.threemf:open",
            "z",
            "model/3mf",
        ),
        FormatSpec(
            "obj",
            "OBJ",
            (".obj",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "colors", "external_references"),
            "solidseas.formats.obj:open",
            "z",
            "model/obj",
        ),
        FormatSpec(
            "ply",
            "PLY",
            (".ply",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "properties", "colors"),
            "solidseas.formats.ply:open",
            "z",
        ),
        FormatSpec(
            "off",
            "OFF",
            (".off",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "colors"),
            "solidseas.formats.off:open",
            "z",
        ),
        FormatSpec(
            "gltf",
            "glTF",
            (".gltf", ".glb"),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "metadata", "components", "properties", "colors", "external_references"),
            "solidseas.formats.gltf:open",
            "z",
            "model/gltf-binary",
        ),
        FormatSpec(
            "amf",
            "AMF",
            (".amf",),
            "mesh",
            "mesh",
            _caps(*_MESH_CAPS, "metadata", "components", "properties", "colors"),
            "solidseas.formats.amf:open",
            "z",
        ),
        FormatSpec(
            "parasolid",
            "Parasolid",
            (".x_t", ".x_b", ".xmt_txt", ".xmt_bin"),
            "exchange",
            "brep",
            _caps("metadata", "brep", "components", "properties", "units", "colors"),
            "solidseas.formats.xt:open",
            "y",
        ),
        FormatSpec(
            "step",
            "STEP",
            (".step", ".stp", ".p21"),
            "exchange",
            "brep",
            _caps(
                "metadata",
                "mesh",
                "brep",
                "components",
                "properties",
                "units",
                "colors",
                "external_references",
            ),
            "solidseas.formats.step:open",
            "y",
            "model/step",
        ),
        FormatSpec(
            "alibre",
            "Alibre Design",
            (".ad_prt", ".ad_asm", ".ad_smp"),
            "native",
            "brep",
            _caps(
                "metadata",
                "mesh",
                "brep",
                "components",
                "properties",
                "stored_preview",
                "units",
                "colors",
                "external_references",
            ),
            "solidseas.formats.alibre:open",
            "y",
        ),
        FormatSpec(
            "acis",
            "ACIS",
            (".sab", ".sat"),
            "exchange",
            "brep",
            _caps("brep", "units", "colors"),
            "solidseas.formats.acis:open",
            "y",
        ),
        FormatSpec("iges", "IGES", (".igs", ".iges"), "exchange", "brep", up_axis="y", mime="model/iges"),
        FormatSpec("alibre_drawing", "Alibre Design drawing", (".ad_drw",), "native", "mixed", up_axis="y"),
        FormatSpec("alibre_package", "Alibre Design package", (".ad_pkg",), "native", "mixed", up_axis="y"),
        FormatSpec("3dxml", "3D XML", (".3dxml",), "exchange", "mixed", up_axis="y"),
        FormatSpec("fusion", "Fusion", (".f3d", ".f3z"), "native", "brep", up_axis="y"),
        FormatSpec("inventor", "Inventor", (".ipt", ".iam"), "native", "brep", up_axis="y"),
        FormatSpec(
            "solid_edge",
            "Solid Edge",
            (".par", ".psm", ".asm"),
            "native",
            "brep",
            up_axis="y",
            needs_signature=(".asm",),
            signature="ole",
        ),
        FormatSpec("nx", "NX", (".prt",), "native", "brep", up_axis="y", needs_signature=(".prt",)),
        FormatSpec("edrawings", "eDrawings", (".eprt", ".easm", ".edrw"), "native", "mixed", up_axis="y"),
        FormatSpec("vrml", "VRML", (".wrl", ".vrml"), "mesh", "mesh", up_axis="y", mime="model/vrml"),
    )
}
SOLIDWORKS = "solidworks"
_BY_EXTENSION: dict[str, str] = {ext: f.id for f in FORMATS.values() for ext in f.extensions}
_OLE_FORMATS = (
    "solidworks",
    "alibre",
    "alibre_drawing",
    "alibre_package",
    "inventor",
    "solid_edge",
    "edrawings",
)
_ZIP_FORMATS = ("3mf", "amf", "fusion", "3dxml")


def get(format_id: str) -> FormatSpec:
    """The :class:`FormatSpec` of ``format_id``; ``KeyError`` for an unknown id."""
    return FORMATS[format_id]


def extension_of(name: str | None) -> str:
    """The lower-case extension of a file name, with its dot (``""`` when it has none)."""
    if not name:
        return ""
    return os.path.splitext(name.replace("\\", "/").rsplit("/", 1)[-1])[1].lower()


def _ext(name: str | None) -> str:
    """The extension of ``name``, a file name or an extension (``.stl``)."""
    if not name:
        return ""
    if name.startswith(".") and name.count(".") == 1 and "/" not in name and "\\" not in name:
        return name.lower()
    return extension_of(name)


def by_extension(name: str | None) -> FormatSpec | None:
    """The format whose extension ``name`` (a file name or an extension) has, or None."""
    fid = _BY_EXTENSION.get(_ext(name))
    return FORMATS[fid] if fid is not None else None


def extensions(formats: Any = "all") -> tuple[str, ...]:
    """The extensions of ``formats`` (``"all"``, one id or ids), sorted."""
    return tuple(sorted(ext for f in select(formats) for ext in FORMATS[f].extensions))


def select(formats: Any) -> frozenset[str]:
    """``formats`` as a set of ids: ``"all"`` is every format, ``"solidworks"`` (or any id)
    that one, and an iterable of ids those. An unknown id raises ``InvalidArgumentError``
    (``detail["parameter"]`` ``formats``)."""
    from ..errors import InvalidArgumentError

    if formats is None:
        formats = SOLIDWORKS
    if isinstance(formats, str):
        if formats == "all":
            return frozenset(FORMATS)
        items = [p.strip() for p in formats.split(",") if p.strip()]
    else:
        try:
            items = list(formats)
        except TypeError:
            raise InvalidArgumentError(
                "formats is all, an id or ids", detail={"parameter": "formats"}
            ) from None
    if "all" in items:
        return frozenset(FORMATS)
    unknown = [f for f in items if not isinstance(f, str) or f not in FORMATS]
    if unknown or not items:
        raise InvalidArgumentError(
            f"formats takes all or ids from: {', '.join(sorted(FORMATS))}", detail={"parameter": "formats"}
        )
    return frozenset(items)


_READABLE: dict[str, bool] = {}


def readable(format_id: str) -> bool:
    """Whether SolidSeas can read documents of ``format_id``: the entry has a reader and
    its module is installed. The module is found, not imported."""
    spec = FORMATS.get(format_id)
    if spec is None or spec.reader is None:
        return False
    hit = _READABLE.get(format_id)
    if hit is None:
        try:
            hit = importlib.util.find_spec(spec.module) is not None
        except (ImportError, ValueError):
            hit = False
        _READABLE[format_id] = hit
    return hit


def reader(format_id: str) -> Callable[..., Any] | None:
    """The function that opens a document of ``format_id`` (its module imported now), or
    None when the format has no reader or its module is not installed."""
    spec = FORMATS.get(format_id)
    if spec is None or spec.reader is None or not readable(format_id):
        return None
    module, func = spec.reader.split(":", 1)
    return getattr(importlib.import_module(module), func)


# --------------------------------------------------------------------------- content tests
@dataclass(frozen=True)
class Detection:
    """What :func:`detect` decided: ``format`` (an id, or None when nothing fits),
    ``variant`` (the format's variant when the head shows it), ``by`` (``content``,
    ``extension``, ``both``, or ``forced`` when the caller named the format) and
    ``mismatch`` (the extension names another format)."""

    format: str | None
    variant: str | None = None
    by: str | None = None
    mismatch: bool = False


def _skip_space(head: bytes) -> bytes:
    return head.removeprefix(b"\xef\xbb\xbf").lstrip(b" \t\r\n\x0b\x0c")


def _sniff_ole(head: bytes, size: int | None, ext: str) -> str | None:
    if head[:8] == OLE_MAGIC:
        return "ole"
    if len(head) >= 8 and head[4:8] == MODERN_MAGIC:
        return "modern"
    return None


def _zip_member(head: bytes) -> str | None:
    from ._source import first_member_name

    return first_member_name(head)


def _sniff_3mf(head: bytes, size: int | None, ext: str) -> str | None:
    if head[:4] != b"PK\x03\x04":
        return None
    if ext == ".3mf":
        return ""
    first = _zip_member(head) or ""
    if first in ("[Content_Types].xml", "_rels/.rels") or first.startswith("3D/"):
        return ""
    return None


def _sniff_amf(head: bytes, size: int | None, ext: str) -> str | None:
    if head[:4] == b"PK\x03\x04":
        first = _zip_member(head) or ""
        return "zip" if ext == ".amf" or first.lower().endswith(".amf") else None
    text = _skip_space(head)
    if text.startswith(b"<?xml") or text.startswith(b"<amf"):
        return "plain" if b"<amf" in head else None
    return None


def _sniff_zip_by_extension(fid: str) -> Callable[[bytes, int | None, str], str | None]:
    def sniff(head: bytes, size: int | None, ext: str) -> str | None:
        return "" if head[:4] == b"PK\x03\x04" and ext in FORMATS[fid].extensions else None

    return sniff


def _sniff_glb(head: bytes, size: int | None, ext: str) -> str | None:
    if len(head) >= 12 and head[:4] == b"glTF":
        (version,) = struct.unpack_from("<I", head, 4)
        return "glb" if version == 2 else None
    return None


def _sniff_gltf(head: bytes, size: int | None, ext: str) -> str | None:
    glb = _sniff_glb(head, size, ext)
    if glb is not None:
        return glb
    text = _skip_space(head)
    return "gltf" if text.startswith(b"{") and b'"asset"' in head else None


def _sniff_step(head: bytes, size: int | None, ext: str) -> str | None:
    return "" if _skip_space(head).startswith(b"ISO-10303-21;") else None


_XT_TEXT_BODY = re.compile(rb"T\d+\s*:\s*TRANSMIT FILE")


def _sniff_parasolid(head: bytes, size: int | None, ext: str) -> str | None:
    if head.startswith(b"**ABCDEFGHIJ"):
        end = head.find(b"**END_OF_HEADER")
        if end >= 0:
            nl = head.find(b"\n", end)
            body = head[nl + 1 :] if nl >= 0 else b""
            if body.startswith(b"PS"):
                return "binary"
            if body:
                return "text"
        return "text" if b"FORMAT=text" in head else ("binary" if b"FORMAT=binary" in head else "")
    if head.startswith(b"PS\x00\x00"):
        return "binary"
    if _XT_TEXT_BODY.match(head):
        return "text"
    return None


def _sniff_acis(head: bytes, size: int | None, ext: str) -> str | None:
    if head.startswith(b"ACIS BinaryFile") or head.startswith(b"ASM BinaryFile"):
        return "sab"
    if ext == ".sat":
        first = head.split(b"\n", 1)[0].strip()
        return "sat" if re.fullmatch(rb"\d{3,5}( +-?\d+){3}", first) else None
    return None


def _sniff_iges(head: bytes, size: int | None, ext: str) -> str | None:
    line = head.split(b"\n", 1)[0].rstrip(b"\r")
    return "" if len(line) == 80 and line[72:73] == b"S" and line[73:].strip().isdigit() else None


def _sniff_ply(head: bytes, size: int | None, ext: str) -> str | None:
    if not (head.startswith(b"ply\n") or head.startswith(b"ply\r\n")):
        return None
    m = re.search(rb"\nformat\s+(ascii|binary_little_endian|binary_big_endian)\s", head)
    if m is None:
        return ""
    return {b"ascii": "ascii", b"binary_little_endian": "binary_le", b"binary_big_endian": "binary_be"}[
        m.group(1)
    ]


_OFF_KEYWORD = re.compile(rb"(ST)?(C)?(N)?(4)?(n)?OFF(\s|$)")


def _sniff_off(head: bytes, size: int | None, ext: str) -> str | None:
    text = head.lstrip(b" \t\r\n")
    m = _OFF_KEYWORD.match(text)
    if m is None:
        return None
    return text[: m.end(0)].strip().decode("ascii")


_OBJ_STATEMENT = re.compile(rb"(?m)^\s*(v|vn|vt|f|o|g|mtllib|usemtl|s)\s")


def _sniff_obj(head: bytes, size: int | None, ext: str) -> str | None:
    if ext != ".obj":
        return None
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(head) - 4:  # a character cut at the end of the head is fine
            return None
    return "" if _OBJ_STATEMENT.search(head) else None


def _sniff_stl(head: bytes, size: int | None, ext: str) -> str | None:
    if size is not None and len(head) >= 84:
        (n,) = struct.unpack_from("<I", head, 80)
        if size == 84 + 50 * n:
            return "binary"
    text = _skip_space(head)
    if text[:5].lower() == b"solid" and (b"facet" in head or b"endsolid" in head):
        return "ascii"
    return None


# Content tests, in the order detection tries them (docs/API.md 3.20.3).
_ORDER: tuple[tuple[str, Callable[[bytes, int | None, str], str | None]], ...] = (
    ("solidworks", _sniff_ole),
    ("3mf", _sniff_3mf),
    ("amf", _sniff_amf),
    ("fusion", _sniff_zip_by_extension("fusion")),
    ("3dxml", _sniff_zip_by_extension("3dxml")),
    ("gltf", _sniff_glb),
    ("step", _sniff_step),
    ("parasolid", _sniff_parasolid),
    ("acis", _sniff_acis),
    ("iges", _sniff_iges),
    ("ply", _sniff_ply),
    ("off", _sniff_off),
    ("gltf", _sniff_gltf),
    ("obj", _sniff_obj),
    ("stl", _sniff_stl),
)
# The test each format's extension asks for (formats an extension alone decides have none).
_SNIFF: dict[str, Callable[[bytes, int | None, str], str | None]] = {
    "solidworks": _sniff_ole,
    "stl": _sniff_stl,
    "3mf": _sniff_3mf,
    "obj": _sniff_obj,
    "ply": _sniff_ply,
    "off": _sniff_off,
    "gltf": _sniff_gltf,
    "amf": _sniff_amf,
    "parasolid": _sniff_parasolid,
    "step": _sniff_step,
    "alibre": _sniff_ole,
    "acis": _sniff_acis,
    "iges": _sniff_iges,
    "alibre_drawing": _sniff_ole,
    "alibre_package": _sniff_ole,
    "inventor": _sniff_ole,
    "solid_edge": _sniff_ole,
    "edrawings": _sniff_ole,
    "fusion": _sniff_zip_by_extension("fusion"),
    "3dxml": _sniff_zip_by_extension("3dxml"),
}
_ALIBRE_VARIANTS = {".ad_prt": "part", ".ad_asm": "assembly", ".ad_smp": "sheet_metal"}


def _variant(fid: str, raw: str, ext: str) -> str | None:
    if fid == "alibre":
        return _ALIBRE_VARIANTS.get(ext)
    return raw or None


def detect_head(head: bytes, size: int | None = None, name: str | None = None) -> Detection:
    """The format of a file whose first bytes are ``head`` (up to 4 KiB), whose size is
    ``size`` and whose name (or extension) is ``name``. See the module notes."""
    head = bytes(head[:HEAD_BYTES])
    ext = _ext(name)
    named = by_extension(ext) if ext else None
    if named is not None:
        sniff = _SNIFF.get(named.id)
        raw = sniff(head, size, ext) if sniff is not None else None
        if raw is not None:
            return Detection(named.id, _variant(named.id, raw, ext), "both", False)
    for fid, sniff in _ORDER:
        raw = sniff(head, size, ext)
        if raw is None:
            continue
        if fid == "solidworks" and named is not None and named.id in _OLE_FORMATS:
            return Detection(named.id, _variant(named.id, raw, ext), "both", False)
        return Detection(fid, _variant(fid, raw, ext), "content", named is not None and named.id != fid)
    if named is not None:
        return Detection(named.id, None, "extension", False)
    return Detection(None)


def detect_as(format_id: str, head: bytes, size: int | None = None, name: str | None = None) -> Detection:
    """The :class:`Detection` of a file read as ``format_id`` whatever it holds (``by``
    ``forced``), with the variant that format's own content test sees in the head."""
    ext = _ext(name)
    sniff = _SNIFF.get(format_id)
    raw = sniff(bytes(head[:HEAD_BYTES]), size, ext) if sniff is not None else None
    return Detection(format_id, _variant(format_id, raw, ext) if raw is not None else None, "forced", False)


def detect(src: Any, name: str | None = None, *, within: Any = None) -> Detection:
    """The format of ``src``: a path (its first 4 KiB read read-only, ``within`` a folder
    when given, as :func:`~solidseas.formats.solidworks.open_document` opens one) or
    bytes (the head, or the whole file). ``name`` defaults to the path's file name."""
    if isinstance(src, (bytes, bytearray, memoryview)):
        data = bytes(src)
        return detect_head(data[:HEAD_BYTES], len(data), name)
    from .solidworks._io import open_readonly

    path = os.fspath(src)
    fh = open_readonly(path) if within is None else open_readonly(path, within=os.fspath(within))
    with fh:
        size = os.fstat(fh.fileno()).st_size
        head = fh.read(HEAD_BYTES)
    return detect_head(head, size, name if name is not None else os.path.basename(path))


def signature_ok(spec: FormatSpec, name: str, head: bytes) -> bool:
    """Whether a file named ``name`` may be listed as ``spec``: always, unless its extension
    is one :attr:`FormatSpec.needs_signature` names, which then needs the content test
    (``ole``: the compound-file magic). An extension with an unknown test is never enough."""
    if extension_of(name) not in spec.needs_signature:
        return True
    if spec.signature == "ole":
        return head[:8] == OLE_MAGIC
    return False


__all__ = [
    "CAPABILITIES",
    "FAMILIES",
    "FORMATS",
    "HEAD_BYTES",
    "KINDS",
    "SOLIDWORKS",
    "Detection",
    "FormatSpec",
    "by_extension",
    "detect",
    "detect_as",
    "detect_head",
    "extension_of",
    "extensions",
    "get",
    "readable",
    "reader",
    "select",
    "signature_ok",
]
