"""The HEADER, CLASSES, TABLES and OBJECTS sections of the DXF (``docs/DRAWINGS.md`` 12.2).

What an R2000 reader needs and nothing it does not: the header variables (the
version, the units, ``$LTSCALE``, ``$DIMSTYLE`` and ``$HANDSEED`` among them), the
three classes the objects use, all nine tables, and the root dictionary with the
groups, the two layouts, the standard multiline style and the plot style
placeholder the layers point to.

Layers go by role, line types carry ``acad.lin``'s names and patterns (in inches
for an inch drawing, ``acadiso.lin``'s millimetres for a millimetre one), and
``$LTSCALE`` makes the hidden line's dash 3 mm on paper at the sheet's scale.
There is one dimension style per unit, ``SOLIDSEAS_MM`` and ``SOLIDSEAS_IN``,
each with the preset's text height, arrow and gaps in that unit on paper and
``DIMSCALE`` the inverse of the sheet's scale, besides AutoCAD's ``Standard``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..numbers import plain_sum
from ..standards import DIMENSIONS, TEXT

INCH_MM = 25.4

# name, description, pattern in inches (acad.lin)
LTYPES: tuple[tuple[str, str, tuple[float, ...]], ...] = (
    ("ByBlock", "", ()),
    ("ByLayer", "", ()),
    ("CONTINUOUS", "Solid line", ()),
    ("HIDDEN", "Hidden __ __ __ __ __ __ __ __ __ __ __ __ __ __", (0.25, -0.125)),
    ("DASHED", "Dashed __ __ __ __ __ __ __ __ __ __ __ __ __ _", (0.5, -0.25)),
    ("CENTER", "Center ____ _ ____ _ ____ _ ____ _ ____ _ ____", (1.25, -0.25, 0.25, -0.25)),
    ("PHANTOM", "Phantom ______  __  __  ______  __  __  ______", (1.25, -0.25, 0.25, -0.25, 0.25, -0.25)),
)
LTYPE_NAMES = tuple(name for name, _d, _p in LTYPES)
HIDDEN_DASH_MM = 3.0  # the preset's hidden dash on paper (standards.LINES)


@dataclass(frozen=True)
class Layer:
    name: str
    colour: int
    linetype: str
    lineweight: int  # hundredths of a millimetre; -3 the default
    plot: bool = True


LAYERS: tuple[Layer, ...] = (
    Layer("0", 7, "CONTINUOUS", -3),
    Layer("VISIBLE", 7, "CONTINUOUS", 60),
    Layer("HIDDEN", 7, "HIDDEN", 30),
    Layer("TANGENT", 7, "DASHED", 30),
    Layer("CENTER", 7, "CENTER", 30),
    Layer("PHANTOM", 7, "PHANTOM", 30),
    Layer("DIM", 7, "CONTINUOUS", 30),
    Layer("HATCH", 7, "CONTINUOUS", 30),
    Layer("BORDER", 7, "CONTINUOUS", 60),
    Layer("TITLE", 7, "CONTINUOUS", 30),
    Layer("NOTES", 7, "CONTINUOUS", 30),
    Layer("STAMP", 7, "CONTINUOUS", 30),
    Layer("DEFPOINTS", 7, "CONTINUOUS", -3, plot=False),
)
LAYER_BY_NAME = {layer.name: layer for layer in LAYERS}

# The display list's layers (display.LAYERS) as DXF layers.
LAYER_OF = {
    "visible": "VISIBLE",
    "hidden": "HIDDEN",
    "tangent": "TANGENT",
    "centre": "CENTER",
    "phantom": "PHANTOM",
    "hatch": "HATCH",
    "border": "BORDER",
    "dimensions": "DIM",
    "notes": "NOTES",
    "title": "TITLE",
    "stamp": "STAMP",
}
# A geometry style's layer (display.STYLE_LAYER, with thin lines kept on VISIBLE).
STYLE_LAYER = {
    "visible": "VISIBLE",
    "hidden": "HIDDEN",
    "tangent": "TANGENT",
    "centre": "CENTER",
    "phantom": "PHANTOM",
    "border": "BORDER",
    "thin": "VISIBLE",
}

# Valid DXF lineweights in hundredths of a millimetre.
LINEWEIGHTS = (
    0,
    5,
    9,
    13,
    15,
    18,
    20,
    25,
    30,
    35,
    40,
    50,
    53,
    60,
    70,
    80,
    90,
    100,
    106,
    120,
    140,
    158,
    200,
    211,
)

STYLE_REGULAR = "SOLIDSEAS"
STYLE_BOLD = "SOLIDSEAS_BOLD"
# name, font file (Arial has Helvetica's widths)
STYLES: tuple[tuple[str, str], ...] = (
    ("Standard", "txt"),
    (STYLE_REGULAR, "arial.ttf"),
    (STYLE_BOLD, "arialbd.ttf"),
)

DIMSTYLE_OF = {"mm": "SOLIDSEAS_MM", "in": "SOLIDSEAS_IN"}
DIMSTYLE_NAMES = ("Standard", "SOLIDSEAS_MM", "SOLIDSEAS_IN")
DIMDEC = {"mm": 2, "in": 3}  # the styles' linear decimals; a dimension overrides its own
DIMADEC = 1
DIMGAP_MM = 1.0  # the gap round dimension text on paper

CLASSES: tuple[tuple[str, str], ...] = (
    ("ACDBDICTIONARYWDFLT", "AcDbDictionaryWithDefault"),
    ("ACDBPLACEHOLDER", "AcDbPlaceHolder"),
    ("LAYOUT", "AcDbLayout"),
)
TABLE_NAMES = ("VPORT", "LTYPE", "LAYER", "STYLE", "VIEW", "UCS", "APPID", "DIMSTYLE", "BLOCK_RECORD")
OBJECT_NAMES = (
    "root",
    "groups",
    "layouts",
    "layout_model",
    "layout_paper",
    "mlinestyles",
    "mlinestyle",
    "plotsettings",
    "plotstylenames",
    "normal",
)


def lineweight(width_mm: float) -> int:
    """The DXF lineweight nearest a width in millimetres."""
    target = width_mm * 100.0
    return min(LINEWEIGHTS, key=lambda w: (abs(w - target), w))


def ltscale(sheet_scale: float) -> float:
    """``$LTSCALE`` for a sheet at ``sheet_scale`` (sheet mm per model mm): the hidden
    line's 6.35 mm (0.25 in) dash drawn 3 mm long on paper, in either unit."""
    return HIDDEN_DASH_MM / (0.25 * INCH_MM) / sheet_scale


class Handles:
    """Handles in hexadecimal from 1, in the order asked for."""

    def __init__(self) -> None:
        self.n = 0

    def new(self) -> str:
        self.n += 1
        return f"{self.n:X}"

    def seed(self) -> str:
        return f"{self.n + 1:X}"


@dataclass
class Structure:
    """The handles of the tables, their entries and the objects, given out in one
    fixed order before any block or entity."""

    tables: dict[str, str] = field(default_factory=dict)
    vport: str = ""
    ltypes: dict[str, str] = field(default_factory=dict)
    layers: dict[str, str] = field(default_factory=dict)
    styles: dict[str, str] = field(default_factory=dict)
    appid: str = ""
    dimstyles: dict[str, str] = field(default_factory=dict)
    block_records: dict[str, str] = field(default_factory=dict)
    objects: dict[str, str] = field(default_factory=dict)


def allocate(handles: Handles, block_names: list[str]) -> Structure:
    s = Structure()
    for name in TABLE_NAMES:
        s.tables[name] = handles.new()
    s.vport = handles.new()
    for name in LTYPE_NAMES:
        s.ltypes[name] = handles.new()
    for layer in LAYERS:
        s.layers[layer.name] = handles.new()
    for name, _font in STYLES:
        s.styles[name] = handles.new()
    s.appid = handles.new()
    for name in DIMSTYLE_NAMES:
        s.dimstyles[name] = handles.new()
    for name in ("*Model_Space", "*Paper_Space", *block_names):
        s.block_records[name] = handles.new()
    for name in OBJECT_NAMES:
        s.objects[name] = handles.new()
    return s


# --------------------------------------------------------------------------- HEADER and CLASSES


def write_header(w, *, unit: str, sheet_scale: float, extents, handseed: str, text_height: float) -> None:
    (x0, y0), (x1, y1) = extents
    w.tags([(0, "SECTION"), (2, "HEADER")])
    w.tags([(9, "$ACADVER"), (1, "AC1015"), (9, "$ACADMAINTVER"), (70, 6)])
    w.tags([(9, "$DWGCODEPAGE"), (3, "ANSI_1252")])
    w.tag(9, "$INSBASE")
    w.point(10, (0.0, 0.0))
    w.tag(9, "$EXTMIN")
    w.point(10, (x0, y0))
    w.tag(9, "$EXTMAX")
    w.point(10, (x1, y1))
    w.tag(9, "$LIMMIN")
    w.point(10, (x0, y0), z=False)
    w.tag(9, "$LIMMAX")
    w.point(10, (x1, y1), z=False)
    w.tags([(9, "$ORTHOMODE"), (70, 0), (9, "$LTSCALE"), (40, ltscale(sheet_scale))])
    w.tags([(9, "$TEXTSIZE"), (40, text_height), (9, "$TEXTSTYLE"), (7, STYLE_REGULAR)])
    w.tags([(9, "$CLAYER"), (8, "0"), (9, "$CELTYPE"), (6, "ByLayer"), (9, "$CECOLOR"), (62, 256)])
    w.tags([(9, "$CELTSCALE"), (40, 1.0), (9, "$CELWEIGHT"), (370, -1)])
    w.tags([(9, "$DIMSCALE"), (40, 1.0 / sheet_scale), (9, "$DIMSTYLE"), (2, DIMSTYLE_OF[unit])])
    w.tags(
        [(9, "$LUNITS"), (70, 2), (9, "$LUPREC"), (70, 4), (9, "$AUNITS"), (70, 0), (9, "$AUPREC"), (70, 2)]
    )
    w.tags([(9, "$MEASUREMENT"), (70, 0 if unit == "in" else 1)])
    w.tags([(9, "$INSUNITS"), (70, 1 if unit == "in" else 4)])
    w.tags([(9, "$PSLTSCALE"), (70, 1), (9, "$TILEMODE"), (70, 1), (9, "$LWDISPLAY"), (290, 1)])
    w.tags([(9, "$HANDSEED"), (5, handseed)])
    w.tags([(0, "ENDSEC")])


def write_classes(w) -> None:
    w.tags([(0, "SECTION"), (2, "CLASSES")])
    for dxf_name, cpp_name in CLASSES:
        w.tags(
            [
                (0, "CLASS"),
                (1, dxf_name),
                (2, cpp_name),
                (3, "ObjectDBX Classes"),
                (90, 0),
                (280, 0),
                (281, 0),
            ]
        )
    w.tag(0, "ENDSEC")


# --------------------------------------------------------------------------- TABLES


def _table(w, s: Structure, name: str, count: int) -> None:
    w.tags([(0, "TABLE"), (2, name), (5, s.tables[name]), (330, "0"), (100, "AcDbSymbolTable"), (70, count)])


def _record(w, kind: str, handle: str, owner: str, subclass: str, handle_code: int = 5) -> None:
    w.tags([(0, kind), (handle_code, handle), (330, owner), (100, "AcDbSymbolTableRecord"), (100, subclass)])


def _dimstyle(unit: str | None, sheet_scale: float) -> list[tuple[int, object]]:
    if unit is None:  # AutoCAD's own Standard, untouched
        return [(70, 0)]
    f = 1.0 / INCH_MM if unit == "in" else 1.0
    text = TEXT[unit].dimension * f
    d = DIMENSIONS
    return [
        (70, 0),
        (3, ""),
        (4, ""),
        (40, 1.0 / sheet_scale),  # DIMSCALE
        (41, text),  # DIMASZ: the arrow as long as the text is tall
        (42, d.extension_gap * f),  # DIMEXO
        (43, d.row_spacing * f),  # DIMDLI
        (44, d.extension_overrun * f),  # DIMEXE
        (46, 0.0),  # DIMDLE
        (140, text),  # DIMTXT
        (141, 0.0),  # DIMCEN: centre marks are drawn by the views
        (144, 1.0),  # DIMLFAC
        (147, DIMGAP_MM * f),  # DIMGAP
        (73, 1),  # DIMTIH: unidirectional
        (74, 1),  # DIMTOH
        (77, 0),  # DIMTAD: the value in a break of the line
        (78, 4 if unit == "in" else 0),  # DIMZIN: no leading zero in inches; trailing zeros kept
        (79, 0),  # DIMAZIN
        (172, 1),  # DIMTOFL
        (179, DIMADEC),  # DIMADEC
        (271, DIMDEC[unit]),  # DIMDEC
        (272, DIMDEC[unit]),  # DIMTDEC
        (275, 0),  # DIMAUNIT: decimal degrees
        (277, 2),  # DIMLUNIT: decimal
        (278, 46),  # DIMDSEP: a full stop
        (280, 0),  # DIMJUST
        (371, -2),  # DIMLWD: by block
        (372, -2),  # DIMLWE
    ]


def write_tables(w, s: Structure, *, unit: str, sheet_scale: float, view) -> None:
    """``view`` is ((centre x, centre y), height, aspect) for the active viewport."""
    w.tags([(0, "SECTION"), (2, "TABLES")])
    owner = s.tables

    _table(w, s, "VPORT", 1)
    (cx, cy), height, aspect = view
    _record(w, "VPORT", s.vport, owner["VPORT"], "AcDbViewportTableRecord")
    w.tags([(2, "*Active"), (70, 0)])
    w.point(10, (0.0, 0.0), z=False)
    w.point(11, (1.0, 1.0), z=False)
    w.point(12, (cx, cy), z=False)
    w.point(13, (0.0, 0.0), z=False)
    w.point(14, (1.0, 1.0), z=False)
    w.point(15, (10.0, 10.0), z=False)
    w.tags([(16, 0.0), (26, 0.0), (36, 1.0)])
    w.point(17, (0.0, 0.0))
    w.tags([(40, height), (41, aspect), (42, 50.0), (43, 0.0), (44, 0.0), (50, 0.0), (51, 0.0)])
    w.tags([(71, 0), (72, 1000), (73, 1), (74, 3), (75, 0), (76, 0), (77, 0), (78, 0)])
    w.tags([(281, 0), (65, 1)])
    w.point(110, (0.0, 0.0))
    w.point(111, (1.0, 0.0))
    w.point(112, (0.0, 1.0))
    w.tags([(79, 0), (146, 0.0)])
    w.tag(0, "ENDTAB")

    _table(w, s, "LTYPE", len(LTYPES))
    f = 1.0 if unit == "in" else INCH_MM
    for name, description, pattern in LTYPES:
        _record(w, "LTYPE", s.ltypes[name], owner["LTYPE"], "AcDbLinetypeTableRecord")
        elements = [p * f for p in pattern]
        w.tags([(2, name), (70, 0), (3, description), (72, 65), (73, len(elements))])
        w.tag(40, plain_sum(abs(e) for e in elements))
        for e in elements:
            w.tags([(49, e), (74, 0)])
    w.tag(0, "ENDTAB")

    _table(w, s, "LAYER", len(LAYERS))
    for layer in LAYERS:
        _record(w, "LAYER", s.layers[layer.name], owner["LAYER"], "AcDbLayerTableRecord")
        w.tags([(2, layer.name), (70, 0), (62, layer.colour), (6, layer.linetype)])
        w.tags([(290, 1 if layer.plot else 0), (370, layer.lineweight), (390, s.objects["normal"])])
    w.tag(0, "ENDTAB")

    _table(w, s, "STYLE", len(STYLES))
    for name, font in STYLES:
        _record(w, "STYLE", s.styles[name], owner["STYLE"], "AcDbTextStyleTableRecord")
        w.tags([(2, name), (70, 0), (40, 0.0), (41, 1.0), (50, 0.0), (71, 0), (42, 2.5), (3, font), (4, "")])
    w.tag(0, "ENDTAB")

    _table(w, s, "VIEW", 0)
    w.tag(0, "ENDTAB")
    _table(w, s, "UCS", 0)
    w.tag(0, "ENDTAB")

    _table(w, s, "APPID", 1)
    _record(w, "APPID", s.appid, owner["APPID"], "AcDbRegAppTableRecord")
    w.tags([(2, "ACAD"), (70, 0)])
    w.tag(0, "ENDTAB")

    _table(w, s, "DIMSTYLE", len(DIMSTYLE_NAMES))
    w.tags([(100, "AcDbDimStyleTable"), (71, len(DIMSTYLE_NAMES))])
    for name in DIMSTYLE_NAMES:
        w.tag(340, s.dimstyles[name])
    for name, which in zip(DIMSTYLE_NAMES, (None, "mm", "in"), strict=True):
        _record(w, "DIMSTYLE", s.dimstyles[name], owner["DIMSTYLE"], "AcDbDimStyleTableRecord", 105)
        w.tag(2, name)
        w.tags(_dimstyle(which, sheet_scale))
        w.tag(340, s.styles[STYLE_REGULAR if which else "Standard"])  # DIMTXSTY
    w.tag(0, "ENDTAB")

    _table(w, s, "BLOCK_RECORD", len(s.block_records))
    for name, handle in s.block_records.items():
        _record(w, "BLOCK_RECORD", handle, owner["BLOCK_RECORD"], "AcDbBlockTableRecord")
        w.tag(2, name)
        if name == "*Model_Space":
            w.tag(340, s.objects["layout_model"])
        elif name == "*Paper_Space":
            w.tag(340, s.objects["layout_paper"])
    w.tag(0, "ENDTAB")
    w.tag(0, "ENDSEC")


# --------------------------------------------------------------------------- OBJECTS


def _dictionary(w, handle: str, owner: str, entries, kind: str = "DICTIONARY") -> None:
    w.tags([(0, kind), (5, handle)])
    if owner != "0":
        w.tags([(102, "{ACAD_REACTORS"), (330, owner), (102, "}")])
    w.tags([(330, owner), (100, "AcDbDictionary"), (281, 1)])
    for key, value in entries:
        w.tags([(3, key), (350, value)])


def _layout(w, handle: str, owner: str, *, name: str, block_record: str, paper, model: bool, order: int):
    width, height = paper
    w.tags([(0, "LAYOUT"), (5, handle), (102, "{ACAD_REACTORS"), (330, owner), (102, "}"), (330, owner)])
    w.tags([(100, "AcDbPlotSettings"), (1, ""), (2, "none_device"), (4, ""), (6, "")])
    w.tags([(40, 0.0), (41, 0.0), (42, 0.0), (43, 0.0), (44, width), (45, height), (46, 0.0), (47, 0.0)])
    w.tags([(48, 0.0), (49, 0.0), (140, 0.0), (141, 0.0), (142, 1.0), (143, 1.0)])
    w.tags([(70, 1712 if model else 688), (72, 1), (73, 0), (74, 5), (7, ""), (75, 16), (147, 1.0)])
    w.tags([(148, 0.0), (149, 0.0)])
    w.tags([(100, "AcDbLayout"), (1, name), (70, 1), (71, order)])
    w.point(10, (0.0, 0.0), z=False)
    w.point(11, (width, height), z=False)
    w.point(12, (0.0, 0.0))
    w.point(14, (0.0, 0.0))
    w.point(15, (0.0, 0.0))
    w.tag(146, 0.0)
    w.point(13, (0.0, 0.0))
    w.point(16, (1.0, 0.0))
    w.point(17, (0.0, 1.0))
    w.tags([(76, 0), (330, block_record)])


def write_objects(w, s: Structure, *, paper) -> None:
    """``paper`` is the sheet's (width, height) in millimetres, for the layouts' plot
    settings."""
    o = s.objects
    w.tags([(0, "SECTION"), (2, "OBJECTS")])
    _dictionary(
        w,
        o["root"],
        "0",
        [
            ("ACAD_GROUP", o["groups"]),
            ("ACAD_LAYOUT", o["layouts"]),
            ("ACAD_MLINESTYLE", o["mlinestyles"]),
            ("ACAD_PLOTSETTINGS", o["plotsettings"]),
            ("ACAD_PLOTSTYLENAME", o["plotstylenames"]),
        ],
    )
    _dictionary(w, o["groups"], o["root"], [])
    _dictionary(w, o["layouts"], o["root"], [("Layout1", o["layout_paper"]), ("Model", o["layout_model"])])
    _layout(
        w,
        o["layout_model"],
        o["layouts"],
        name="Model",
        block_record=s.block_records["*Model_Space"],
        paper=paper,
        model=True,
        order=0,
    )
    _layout(
        w,
        o["layout_paper"],
        o["layouts"],
        name="Layout1",
        block_record=s.block_records["*Paper_Space"],
        paper=paper,
        model=False,
        order=1,
    )
    _dictionary(w, o["mlinestyles"], o["root"], [("Standard", o["mlinestyle"])])
    w.tags([(0, "MLINESTYLE"), (5, o["mlinestyle"]), (102, "{ACAD_REACTORS"), (330, o["mlinestyles"])])
    w.tags([(102, "}"), (330, o["mlinestyles"]), (100, "AcDbMlineStyle"), (2, "Standard"), (70, 0), (3, "")])
    w.tags([(62, 256), (51, 90.0), (52, 90.0), (71, 2)])
    w.tags([(49, 0.5), (62, 256), (6, "BYLAYER"), (49, -0.5), (62, 256), (6, "BYLAYER")])
    _dictionary(w, o["plotsettings"], o["root"], [])
    _dictionary(w, o["plotstylenames"], o["root"], [("Normal", o["normal"])], kind="ACDBDICTIONARYWDFLT")
    w.tags([(100, "AcDbDictionaryWithDefault"), (340, o["normal"])])
    w.tags([(0, "ACDBPLACEHOLDER"), (5, o["normal"]), (102, "{ACAD_REACTORS"), (330, o["plotstylenames"])])
    w.tags([(102, "}"), (330, o["plotstylenames"])])
    w.tag(0, "ENDSEC")


__all__ = [
    "CLASSES",
    "DIMADEC",
    "DIMDEC",
    "DIMGAP_MM",
    "DIMSTYLE_NAMES",
    "DIMSTYLE_OF",
    "LAYERS",
    "LAYER_BY_NAME",
    "LAYER_OF",
    "LINEWEIGHTS",
    "LTYPES",
    "LTYPE_NAMES",
    "STYLES",
    "STYLE_BOLD",
    "STYLE_LAYER",
    "STYLE_REGULAR",
    "TABLE_NAMES",
    "Handles",
    "Layer",
    "Structure",
    "allocate",
    "lineweight",
    "ltscale",
    "write_classes",
    "write_header",
    "write_objects",
    "write_tables",
]
