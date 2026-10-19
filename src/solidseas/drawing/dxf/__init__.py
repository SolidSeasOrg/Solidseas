"""The DXF writer (``docs/DRAWINGS.md`` 12.2): a drawing's sheet as an ASCII DXF R2000
(AC1015), written by hand.

:func:`write_dxf` takes a :class:`~solidseas.drawing.types.Drawing` (its sheet)
or a :class:`~solidseas.drawing.display.Sheet` and writes, in this order: a
``999`` comment ``SolidSeas <version>`` (how ``dwg-file`` knows SolidSeas wrote a
file), HEADER, CLASSES, TABLES, BLOCKS, ENTITIES and OBJECTS, with handles given
out in one fixed order, so the same sheet always gives the same bytes. Lines end
in CRLF.

What goes where (the semantic layer is read first, the painted layer for what
only it holds):

- **View geometry** (``Sheet.geometry``): exact entities at true size in model
  space (:mod:`.entities` says how a sheet point maps). A painted stroke that is
  the same path as a geometry primitive is not written again.
- **Dimensions**: DIMENSION entities with measured text and a block each
  (:mod:`.dimensions`), filled from the painted items the dimension owns.
- **Feature control frames and datum symbols**: one block per annotation,
  inserted where it stands. The block holds the painted items lying inside the
  annotation's outline (the frame's cells measured as :func:`.entities.frame_box`
  does, the datum's box and leader), or, when the sheet painted none there, the
  frame or symbol drawn from the annotation.
- **Notes** with nothing painted under their id: MTEXT, with inline frames as
  frame blocks after the words.
- **The PRELIMINARY stamp**: TEXT on layer STAMP (painted stamp items are not
  written again).
- **Everything else painted** (border, title block, notes, hatching, centre
  marks): replayed on its layer at ``1/scale``; furniture with nothing painted
  on its layer is drawn from the semantic layer. The logo is not written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ...errors import InvalidArgumentError
from .. import display as D
from ..limits import DEFAULT_LIMITS, DrawingLimits
from ..painter import path_of
from . import dimensions as Dim
from . import entities as E
from . import tables as T
from .tags import TagWriter

UNITS = ("mm", "in")
GEOMETRY_LAYERS = frozenset({"visible", "hidden", "tangent", "centre", "phantom", "border"})
CAPTURE_LAYERS = frozenset({"dimensions", "notes"})
CAPTURE_MARGIN = 0.75  # millimetres round an annotation's outline
SAME_PATH = 0.005  # millimetres within which a painted stroke is a geometry path
FURNITURE_LAYER = {
    D.Border: "border",
    D.TitleBlock: "title",
    D.ProjectionSymbol: "title",
    D.ToleranceBlock: "title",
    D.NotesBlock: "notes",
    D.ViewLabel: "notes",
    D.PlotStamp: "notes",
    D.CentreMark: "centre",
    D.CentreLine: "centre",
    D.VirtualSharp: "dimensions",
}


def _bad(message: str, parameter: str) -> InvalidArgumentError:
    return InvalidArgumentError(message, detail={"parameter": parameter})


@dataclass
class Block:
    name: str
    flags: int
    base: tuple[float, float]
    ents: list[E.Ent]


# --------------------------------------------------------------------------- arguments


def _sheet_and_unit(obj: Any, units: str | None) -> tuple[D.Sheet, str]:
    from ..types import Drawing

    unit = None
    if isinstance(obj, Drawing):
        options = getattr(obj.options, "units", None)
        if options in UNITS:
            unit = options
        else:
            stated = obj.model.get("units") if isinstance(obj.model, dict) else None
            if isinstance(stated, dict):
                stated = stated.get("unit")
            if stated in UNITS:
                unit = stated
        obj = obj.sheet
    if not isinstance(obj, D.Sheet):
        raise _bad("write_dxf needs a Drawing with a sheet, or a Sheet", "drawing")
    if units is not None:
        if units not in UNITS:
            raise _bad("units must be 'mm', 'in' or None", "units")
        unit = units
    return obj, unit or "mm"


def _sheet_scale(sheet: D.Sheet) -> float:
    scale = sheet.scale
    ok = (
        isinstance(scale, tuple)
        and len(scale) == 2
        and all(
            isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) and n > 0
            for n in scale
        )
    )
    if not ok:
        raise _bad("a sheet's scale must be two numbers more than nought", "sheet")
    return float(scale[0]) / float(scale[1])


def _check_sheet(sheet: D.Sheet) -> None:
    for value in (sheet.width, sheet.height):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise _bad("a sheet's size must be finite and more than nought", "sheet")
    for name in ("views", "geometry", "annotations", "painted"):
        if not isinstance(getattr(sheet, name), tuple):
            raise _bad(f"a sheet's {name} must be a tuple", "sheet")


# --------------------------------------------------------------------------- the painted layer sorted


class _Paths:
    """The geometry's paths as the painter draws them, to know a painted stroke that is
    one of them again. Paths match within :data:`SAME_PATH` millimetres, so a sheet
    read back from the ``.ssdrw`` (lengths in whole micrometres) still matches."""

    def __init__(self, geometry) -> None:
        self.buckets: dict[tuple, list[list[tuple]]] = {}
        for item in geometry:
            if isinstance(item, D.GEOMETRY):
                try:
                    path = [tuple(op) for op in path_of(item)]
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                key = self._key(path)
                if key is not None:
                    self.buckets.setdefault(key, []).append(path)

    @staticmethod
    def _key(path, dx: int = 0, dy: int = 0) -> tuple | None:
        if not path or len(path[0]) < 3:
            return None
        letters = tuple(op[0] for op in path)
        return letters, round(path[0][1] * 10.0) + dx, round(path[0][2] * 10.0) + dy

    def __contains__(self, path) -> bool:
        try:
            path = [tuple(op) for op in path]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for candidate in self.buckets.get(self._key(path, dx, dy), ()):
                        if self._same(path, candidate):
                            return True
        except (TypeError, ValueError, IndexError):
            return False
        return False

    @staticmethod
    def _same(a, b) -> bool:
        if len(a) != len(b):
            return False
        for p, q in zip(a, b, strict=True):
            if len(p) != len(q) or p[0] != q[0]:
                return False
            if any(abs(float(u) - float(v)) > SAME_PATH for u, v in zip(p[1:], q[1:], strict=True)):
                return False
        return True


def _near_polyline(p, pts, reach: float) -> bool:
    for a, b in zip(pts, pts[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
        if math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy) <= reach:
            return True
    return False


def _bounds(item):
    pts = E.painted_points(item)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _capture_frame(frame: D.FeatureControlFrame, th: float, pool, taken: set[int]) -> list[int]:
    """The painted items of a frame: those in its band (its height, from its left end)
    that touch the frame as measured, then whatever touches what was taken, so a
    frame the sheet painted wider than the writer measures it still comes whole."""
    x0, y0, x1, y1 = E.frame_box(frame.frame, (float(frame.at[0]), float(frame.at[1])), th)
    m = CAPTURE_MARGIN
    reach = x1
    out: list[int] = []
    for _round in range(len(pool) + 1):
        grew = False
        for i, box in pool:
            if i in taken or box is None:
                continue
            bx0, by0, bx1, by1 = box
            if by0 >= y0 - m and by1 <= y1 + m and bx0 >= x0 - m and bx0 <= reach + m:
                taken.add(i)
                out.append(i)
                reach = max(reach, bx1)
                grew = True
        if not grew:
            break
    return out


def _capture_datum(datum: D.DatumFeature, th: float, pool, items, taken: set[int]) -> list[int]:
    """The painted items of a datum symbol: inside its box (with room for a box drawn
    up to half as large again) or along its leader."""
    (x0, y0, x1, y1), leader = E.datum_shape(datum, th)
    grow = max(CAPTURE_MARGIN, (x1 - x0) / 2.0)
    out: list[int] = []
    for i, box in pool:
        if i in taken or box is None:
            continue
        pts = E.painted_points(items[i])
        if all(
            (x0 - grow <= x <= x1 + grow and y0 - grow <= y <= y1 + grow)
            or _near_polyline((x, y), leader, th)
            for x, y in pts
        ):
            taken.add(i)
            out.append(i)
    return out


@dataclass
class Sorted:
    general: list  # painted items written as they are, in model space
    owned: dict[str, list]  # a dimension's id: its painted items
    captured: dict[int, list]  # an annotation's index: the painted items in its outline
    stamp_runs: list  # the painted stamp's text runs, which place the stamp's TEXT
    owners: set[str]  # every owner the painted layer names


def _sort(sheet: D.Sheet, ctx: E.Context, dims: dict[str, int]) -> Sorted:
    keys = _Paths(sheet.geometry)
    has_stamp = any(isinstance(a, D.Stamp) for a in sheet.annotations)
    out = Sorted([], {}, {}, [], set())
    items = []
    for item in sheet.painted:
        if not isinstance(item, D.PAINTED):
            continue
        out.owners.add(item.owner)
        if isinstance(item, D.ImageRun):
            continue  # the logo: a DXF image would be a link to an outside file
        if isinstance(item, D.Stroke) and item.layer in GEOMETRY_LAYERS and item.path in keys:
            continue  # written exactly from the geometry
        if has_stamp and item.layer == "stamp":
            if isinstance(item, D.TextRun):
                out.stamp_runs.append(item)
            continue
        items.append(item)
    pool = [(i, _bounds(item)) for i, item in enumerate(items) if item.layer in CAPTURE_LAYERS]
    taken: set[int] = set()
    th = ctx.heights.dimension
    owner_of: dict[int, int] = {}
    for n, a in enumerate(sheet.annotations):
        if isinstance(a, D.FeatureControlFrame):
            got = _capture_frame(a, th, pool, taken)
        elif isinstance(a, D.DatumFeature):
            got = _capture_datum(a, th, pool, items, taken)
        else:
            continue
        for i in got:
            owner_of[i] = n
    for i, item in enumerate(items):
        if i in owner_of:
            out.captured.setdefault(owner_of[i], []).append(item)
        elif item.owner in dims:
            out.owned.setdefault(item.owner, []).append(item)
        else:
            out.general.append(item)
    return out


# --------------------------------------------------------------------------- the content


def _content(sheet: D.Sheet, ctx: E.Context) -> tuple[list[Block], list[E.Ent]]:
    placements = {p.view: p for p in sheet.views if isinstance(p, D.ViewPlacement)}
    dims: dict[str, int] = {}  # a measuring dimension's id: the first annotation with it
    for i, a in enumerate(sheet.annotations):
        if isinstance(a, D.Dimension) and Dim.measures(a) and a.id not in dims:
            dims[a.id] = i
    sorted_ = _sort(sheet, ctx, dims)
    blocks: list[Block] = []
    model: list[E.Ent] = []

    for item in sheet.geometry:
        if isinstance(item, D.GEOMETRY):
            model += E.from_geometry(item, ctx)
    for item in sorted_.general:
        model += E.from_painted(item, ctx)
    painted_layers = {item.layer for item in sorted_.general}

    counts = {"D": 0, "FCF": 0, "DATUM": 0}

    def insert_block(kind: str, ents: list[E.Ent], at) -> None:
        counts[kind] += 1
        name = f"SS_{kind}_{counts[kind]}"
        base = ctx.pt(at)
        blocks.append(Block(name, 0, base, ents))
        model.append(E.insert(name, base, "DIM"))

    for i, a in enumerate(sheet.annotations):
        if isinstance(a, D.Dimension):
            if Dim.measures(a):
                counts["D"] += 1
                name = f"*D{counts['D']}"
                # a second dimension with the same id gets a block drawn from its points
                owned = sorted_.owned.get(a.id, []) if dims.get(a.id) == i else []
                written = Dim.write(a, ctx, name=name, painted=owned, placement=placements.get(a.view))
                blocks.append(Block(name, 1, (0.0, 0.0), written.block))
                model.append(written.dimension)
                model += written.beside
            elif a.id not in sorted_.owners:
                sk = E.Sketch(ctx, "DIM")
                th = ctx.heights.dimension
                sk.mtext(
                    (float(a.text_at[0]), float(a.text_at[1])), th, [Dim.shown(a), *a.text.suffix], attach=5
                )
                model += sk.ents
        elif isinstance(a, (D.FeatureControlFrame, D.DatumFeature)):
            captured = sorted_.captured.get(i, [])
            ents: list[E.Ent] = []
            for item in captured:
                ents += E.from_painted(item, ctx, block=True)
            if isinstance(a, D.FeatureControlFrame):
                if not ents:
                    ents = E.frame_entities(a.frame, (float(a.at[0]), float(a.at[1])), ctx)
                insert_block("FCF", ents, a.at)
            else:
                if not ents:
                    ents = E.datum_entities(a, ctx)
                insert_block("DATUM", ents, a.at)
        elif isinstance(a, D.Note):
            if a.id in sorted_.owners:
                continue
            ents, frames = E.note_entities(a, ctx)
            model += ents
            for frame, at in frames:
                insert_block("FCF", E.frame_entities(frame, at, ctx), at)
        elif isinstance(a, D.Stamp):
            run = next((r for r in sorted_.stamp_runs if r.text == a.text), None)
            model += E.stamp_entities(a, ctx, run)
        elif type(a) in FURNITURE_LAYER and FURNITURE_LAYER[type(a)] not in painted_layers:
            model += E.furniture_entities(a, ctx)
    return blocks, model


# --------------------------------------------------------------------------- the file


def _serialise(sheet: D.Sheet, ctx: E.Context, blocks: list[Block], model: list[E.Ent]) -> bytes:
    from ... import __version__

    counter = [0]
    handles = T.Handles()
    structure = T.allocate(handles, [b.name for b in blocks])
    k = ctx.k
    width, height = float(sheet.width) * k, float(sheet.height) * k
    body = TagWriter(ctx.limits, counter)
    T.write_classes(body)
    view = ((width / 2.0, height / 2.0), height * 1.05, sheet.width / sheet.height)
    T.write_tables(body, structure, unit=ctx.unit, sheet_scale=ctx.sheet_scale, view=view)

    body.tags([(0, "SECTION"), (2, "BLOCKS")])
    every = [
        (Block("*Model_Space", 0, (0.0, 0.0), []), False),
        (Block("*Paper_Space", 0, (0.0, 0.0), []), True),
        *((b, False) for b in blocks),
    ]
    for block, paper in every:
        record = structure.block_records[block.name]
        body.tags([(0, "BLOCK"), (5, handles.new()), (330, record), (100, "AcDbEntity")])
        if paper:
            body.tag(67, 1)
        body.tags([(8, "0"), (100, "AcDbBlockBegin"), (2, block.name), (70, block.flags)])
        body.point(10, block.base)
        body.tags([(3, block.name), (1, "")])
        for ent in block.ents:
            E.write_entity(body, ent, handles.new(), record)
        body.tags([(0, "ENDBLK"), (5, handles.new()), (330, record), (100, "AcDbEntity")])
        if paper:
            body.tag(67, 1)
        body.tags([(8, "0"), (100, "AcDbBlockEnd")])
    body.tag(0, "ENDSEC")

    body.tags([(0, "SECTION"), (2, "ENTITIES")])
    owner = structure.block_records["*Model_Space"]
    for ent in model:
        E.write_entity(body, ent, handles.new(), owner)
    body.tag(0, "ENDSEC")

    T.write_objects(body, structure, paper=(float(sheet.width), float(sheet.height)))
    body.tag(0, "EOF")

    head = TagWriter(ctx.limits, counter)
    head.tag(999, f"SolidSeas {__version__}")
    T.write_header(
        head,
        unit=ctx.unit,
        sheet_scale=ctx.sheet_scale,
        extents=((0.0, 0.0), (width, height)),
        handseed=handles.seed(),
        text_height=ctx.heights.note * k,
    )
    return (head.text() + body.text()).encode("ascii")


def dxf_bytes(
    drawing_or_sheet: Any,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
    symbol_words: bool = False,
    units: str | None = None,
) -> bytes:
    """The DXF of a drawing's sheet (or a sheet) as bytes; see :func:`write_dxf`."""
    if not isinstance(limits, DrawingLimits):
        raise _bad("limits must be DrawingLimits", "limits")
    if not isinstance(symbol_words, bool):
        raise _bad("symbol_words must be true or false", "symbol_words")
    sheet, unit = _sheet_and_unit(drawing_or_sheet, units)
    _check_sheet(sheet)
    ctx = E.Context(unit, _sheet_scale(sheet), symbol_words, limits)
    try:
        blocks, model = _content(sheet, ctx)
    except InvalidArgumentError:
        raise
    except (TypeError, ValueError, AttributeError, IndexError, KeyError) as exc:
        # an item whose fields are not what the display list says (a hostile sheet)
        raise _bad(
            f"the sheet holds an item the DXF writer cannot write ({type(exc).__name__})", "sheet"
        ) from None
    return _serialise(sheet, ctx, blocks, model)


def write_dxf(
    drawing_or_sheet: Any,
    fh,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
    symbol_words: bool = False,
    units: str | None = None,
) -> int:
    """Write a drawing's sheet (a ``Drawing`` or a ``display.Sheet``) as ASCII DXF R2000
    to the binary file object ``fh``; returns the bytes written.

    Model space is in ``units`` (``mm`` or ``in``; by default the drawing's unit, else
    millimetres) at the part's true size. ``symbol_words`` writes CBORE, CSK and
    DEEP for the symbols CAD fonts lack. Nothing reaches ``fh`` when the sheet is
    refused (``InvalidArgumentError``) or the file would pass ``limits.output_bytes``
    (``SldLimitError``)."""
    if not callable(getattr(fh, "write", None)):
        raise _bad("fh must be a binary file object", "fh")
    data = dxf_bytes(drawing_or_sheet, limits=limits, symbol_words=symbol_words, units=units)
    fh.write(data)
    return len(data)


__all__ = ["dxf_bytes", "write_dxf"]
