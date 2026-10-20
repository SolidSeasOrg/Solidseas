"""The document types the list's quick filter offers, and the type of each listing entry.

:data:`FILE_TYPES` is the whole table: one :class:`FileType` per button, in the
order the buttons stand, SOLIDWORKS parts, assemblies and drawings first, then
the exchange and mesh formats SolidSeas reads (STEP, STL, 3MF, Parasolid text and
binary, ACIS binary, OBJ, PLY, OFF, glTF and GLB, AMF), then Alibre Design parts
and assemblies, then, on grey buttons as the list draws their rows, the formats
SolidSeas lists but cannot read (IGES and BREP while the OCCT backend extension is
off, Alibre Design drawings and packages, Inventor, Solid Edge, Fusion, eDrawings, 3D
XML, VRML). ACIS text has a grey button
of its own beside ACIS binary's: the ACIS reader refuses it (:data:`NOT_READ`), so
its files are listed as not read. Every format the registry
(:mod:`solidseas.formats.registry`) lets a listing report has rows here,
named after the registry's name for it, so each gets a button with its own name;
the tests hold the two together. A type is offered only when the opened folder
holds a file of it, and any other type the listing reports gets a grey button that
shows its extension (the first :data:`BADGE_LETTERS` letters of a longer one),
after the known ones in alphabetical order. A new format needs one row here,
nothing else; one row with several extensions (``.igs`` and ``.iges``) gives them
one button.

:func:`file_type` decides an entry's type as the listing reports it: a
SOLIDWORKS document by its document type (what the file says, else its
extension, as the Type column does), a file of another format by its name when
that agrees with what the listing found inside (``model.format``, or
``detected`` for a STEP file wearing a SOLIDWORKS extension, which the Type
column then calls STEP too), else by what was found inside. A folder has no
type.

Nothing here imports Qt, so it is tested everywhere.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# The glyphs' colours: SOLIDWORKS parts, assemblies and drawings as the list's badges
# have them; other formats by family, exchange purple, mesh teal, another program's own
# brown, and grey for a type the table does not have.
BLUE, GREEN, ORANGE = "#4a7fb5", "#4f9a5a", "#c07a2c"  # SOLIDWORKS
PURPLE, TEAL, BROWN, GREY = "#7a5cc0", "#2a8f8f", "#a0522d", "#8a8f96"  # exchange, mesh, native, other
GLYPHS = ("part", "assembly", "drawing", "badge")
_KEY = re.compile(r"[a-z0-9_]{1,12}")
MAX_KEYS = 32  # a remembered selection longer than this is not ours
# Extensions of a format SolidSeas reads whose reader refuses them: ACIS text (.sat, the
# reader's rule sat_text). Their buttons are grey, as for a format that is not read.
NOT_READ = frozenset({".sat"})
BADGE_LETTERS = 6  # a grey badge shows this much of a longer extension (the tooltip has it all)


@dataclass(frozen=True)
class FileType:
    """One quick filter button. ``key`` is what the settings store; ``extensions`` are the
    names it takes (lower case, with the dot), the first one shown; ``formats`` the
    listing's format ids whose content it is (``solidworks`` for a SOLIDWORKS document,
    then ``doc_type`` tells part, assembly and drawing apart); ``glyph`` what the button
    draws (:data:`GLYPHS`) and ``letters`` the badge's text, or the tag on a part or an
    assembly of another program."""

    key: str
    name: str
    extensions: tuple[str, ...]
    formats: tuple[str, ...]
    glyph: str
    color: str
    letters: str = ""
    doc_type: str | None = None

    @property
    def shown_extensions(self) -> str:
        """``SLDPRT``, ``STEP, STP, P21``: the names it takes, as a person reads them."""
        return ", ".join(e.lstrip(".").upper() for e in self.extensions)

    @property
    def title(self) -> str:
        """``SOLIDWORKS Part (SLDPRT)``: its tooltip's first line and its accessible name."""
        return f"{self.name} ({self.shown_extensions})"


SW, ALIBRE = ("solidworks",), ("alibre",)
FILE_TYPES: tuple[FileType, ...] = (
    FileType("sldprt", "SOLIDWORKS Part", (".sldprt",), SW, "part", BLUE, "", "part"),
    FileType("sldasm", "SOLIDWORKS Assembly", (".sldasm",), SW, "assembly", GREEN, "", "assembly"),
    FileType("slddrw", "SOLIDWORKS Drawing", (".slddrw",), SW, "drawing", ORANGE, "", "drawing"),
    FileType("step", "STEP", (".step", ".stp", ".p21"), ("step",), "badge", PURPLE, "STEP"),
    FileType("stl", "STL", (".stl",), ("stl",), "badge", TEAL, "STL"),
    FileType("3mf", "3MF", (".3mf",), ("3mf",), "badge", TEAL, "3MF"),
    FileType("x_t", "Parasolid text", (".x_t", ".xmt_txt"), ("parasolid",), "badge", PURPLE, "X_T"),
    FileType("x_b", "Parasolid binary", (".x_b", ".xmt_bin"), ("parasolid",), "badge", PURPLE, "X_B"),
    FileType("sab", "ACIS binary", (".sab",), ("acis",), "badge", PURPLE, "SAB"),
    FileType("sat", "ACIS text", (".sat",), ("acis",), "badge", GREY, "SAT"),  # not read yet: NOT_READ
    FileType("obj", "OBJ", (".obj",), ("obj",), "badge", TEAL, "OBJ"),
    FileType("ply", "PLY", (".ply",), ("ply",), "badge", TEAL, "PLY"),
    FileType("off", "OFF", (".off",), ("off",), "badge", TEAL, "OFF"),
    FileType("gltf", "glTF", (".gltf",), ("gltf",), "badge", TEAL, "GLTF"),
    FileType("glb", "glTF binary", (".glb",), ("gltf",), "badge", TEAL, "GLB"),
    FileType("amf", "AMF", (".amf",), ("amf",), "badge", TEAL, "AMF"),
    FileType("ad_prt", "Alibre Design part", (".ad_prt", ".ad_smp"), ALIBRE, "part", BROWN, "AD", "part"),
    FileType("ad_asm", "Alibre Design assembly", (".ad_asm",), ALIBRE, "assembly", BROWN, "AD", "assembly"),
    # Formats SolidSeas lists but cannot read: grey, as the list draws their rows.
    FileType("iges", "IGES", (".igs", ".iges"), ("iges",), "badge", GREY, "IGES"),
    FileType("brep", "BREP", (".brep",), ("occt_brep",), "badge", GREY, "BREP"),
    FileType("ad_drw", "Alibre Design drawing", (".ad_drw",), ("alibre_drawing",), "badge", GREY, "AD_DRW"),
    FileType("ad_pkg", "Alibre Design package", (".ad_pkg",), ("alibre_package",), "badge", GREY, "AD_PKG"),
    FileType("ipt", "Inventor part", (".ipt",), ("inventor",), "badge", GREY, "IPT", "part"),
    FileType("iam", "Inventor assembly", (".iam",), ("inventor",), "badge", GREY, "IAM", "assembly"),
    FileType("par", "Solid Edge part", (".par",), ("solid_edge",), "badge", GREY, "PAR", "part"),
    FileType("psm", "Solid Edge sheet metal part", (".psm",), ("solid_edge",), "badge", GREY, "PSM", "part"),
    FileType("asm", "Solid Edge assembly", (".asm",), ("solid_edge",), "badge", GREY, "ASM", "assembly"),
    FileType("f3d", "Fusion design", (".f3d",), ("fusion",), "badge", GREY, "F3D"),
    FileType("f3z", "Fusion archive", (".f3z",), ("fusion",), "badge", GREY, "F3Z"),
    FileType("eprt", "eDrawings part", (".eprt",), ("edrawings",), "badge", GREY, "EPRT", "part"),
    FileType("easm", "eDrawings assembly", (".easm",), ("edrawings",), "badge", GREY, "EASM", "assembly"),
    FileType("edrw", "eDrawings drawing", (".edrw",), ("edrawings",), "badge", GREY, "EDRW", "drawing"),
    FileType("3dxml", "3D XML", (".3dxml",), ("3dxml",), "badge", GREY, "3DXML"),
    FileType("vrml", "VRML", (".wrl", ".vrml"), ("vrml",), "badge", GREY, "VRML"),
)
TYPES: dict[str, FileType] = {t.key: t for t in FILE_TYPES}
_ORDER = {t.key: i for i, t in enumerate(FILE_TYPES)}
_BY_EXTENSION = {ext: t for t in FILE_TYPES for ext in t.extensions}


def _extension_key(ext: str) -> str | None:
    key = ext.lstrip(".").lower()
    return key if _KEY.fullmatch(key) else None


def shown_color(ft: FileType) -> str:
    """The colour ``ft``'s button is drawn in now: a grey type whose formats a conversion
    backend reads (IGES and BREP, the OCCT backend) takes its family's colour while that
    backend is available, as the list draws its rows then."""
    if ft.color != GREY or not ft.formats:
        return ft.color
    from solidseas.formats import registry

    specs = [registry.FORMATS.get(f) for f in ft.formats]
    if all(s is not None and s.backend is not None and registry.readable(s.id) for s in specs):
        return {"exchange": PURPLE, "mesh": TEAL, "native": BROWN}.get(specs[0].family, ft.color)
    return ft.color


def file_type(entry: dict[str, Any]) -> str | None:
    """The quick filter's type of a listing entry (a key of :data:`TYPES`, or the
    extension of a type without a row there); None for a folder or a file whose type
    cannot be told."""
    if entry.get("type") != "file":
        return None
    ext = os.path.splitext(entry.get("path") or "")[1].lower()
    by_name = _BY_EXTENSION.get(ext)
    content = (entry.get("model") or {}).get("format") or entry.get("detected")
    if not content and entry.get("format") in ("modern", "ole"):
        content = "solidworks"  # read as a SOLIDWORKS document
    if not content:  # nothing was read: the name says, as it does in the Type column
        return by_name.key if by_name is not None else _extension_key(ext)
    doc_type = entry.get("doc_type")
    if (
        by_name is not None
        and content in by_name.formats
        and (by_name.doc_type is None or not doc_type or by_name.doc_type == doc_type)
    ):
        return by_name.key  # the name agrees with the content: X_T or X_B, glTF or GLB
    candidates = [t for t in FILE_TYPES if content in t.formats]
    for t in candidates:
        if t.doc_type is None or t.doc_type == doc_type:
            return t.key
    if candidates and content != "solidworks":
        return candidates[0].key
    return _extension_key(ext) or (content if _KEY.fullmatch(content) else None)


def info(key: str) -> FileType:
    """The :class:`FileType` of ``key``: its row, or a grey badge of its extension."""
    known = TYPES.get(key)
    if known is not None:
        return known
    return FileType(key, f"{key.upper()} file", (f".{key}",), (), "badge", GREY, key.upper()[:BADGE_LETTERS])


def ordered(keys: Iterable[str]) -> list[str]:
    """``keys`` in the buttons' order: the table's, then the others alphabetically."""
    return sorted(set(keys), key=lambda k: (_ORDER.get(k, len(_ORDER)), k))


def parse_key(text: str) -> str | None:
    """A type key from what a person types: a key (``sldprt``), an extension with or
    without its dot (``.STP`` gives ``step``); None when it cannot be one."""
    text = text.strip().lower()
    if text in TYPES:
        return text
    known = _BY_EXTENSION.get("." + text.lstrip("."))
    return known.key if known is not None else _extension_key(text)


def parse_keys(text: str | None) -> tuple[str, ...]:
    """A remembered selection, ``sldprt,step``: its valid keys in the buttons' order;
    nothing for a value that is not one."""
    if not text or text.startswith("@") or len(text) > MAX_KEYS * 13:
        return ()
    keys = [k.strip().lower() for k in text.split(",") if k.strip()]
    if len(keys) > MAX_KEYS or not all(_KEY.fullmatch(k) for k in keys):
        return ()
    return tuple(ordered(keys))


def format_keys(keys: Iterable[str]) -> str:
    return ",".join(ordered(keys))
