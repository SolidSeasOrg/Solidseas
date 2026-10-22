"""The sheet: size, border, zones and the areas set aside for the title block,
revision block, notes and an assembly's parts list (``docs/DRAWINGS.md`` 11.1,
11.4), the sheets a long parts list goes on to (:func:`continuation_frame`, 11.7),
and the order sheets and scales are tried in.

**Scale and sheet (C24, the slice's answer, the default until the VM decides):** on
each sheet, smallest first, the largest preferred scale at which the views and
their bands fit; a reduced scale is taken only when every dimensioned span stays
at least :data:`MIN_SPAN_MM` on paper, else the next sheet is tried, and when none
does better the first fit is kept and the cramped features are reported.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .. import standards
from .index import Box
from .titleblock import CONTINUATION_SHARE

MIN_SPAN_MM = 8.0
TITLE_SIZE = {"A": (127.0, 50.0)}  # the compact A block; B to E share one layout
TITLE_SIZE_LARGE = (178.0, 64.0)
REVISION_ROW = 6.0
NOTE_LINE = 1.6  # line pitch as a share of the note text height
GAP = 3.0  # between reserved areas and the views
PLOT_WIDTH = 110.0  # the plot stamp, inside the border at the lower left


@dataclass(frozen=True)
class SheetFrame:
    """A sheet laid out: its size, the border, and the reserved boxes."""

    name: str
    width: float
    height: float
    margin: float
    columns: int
    rows: int
    border: Box
    title: Box
    revision: Box
    notes: Box
    stamp: Box
    plot: Box
    parts: Box | None = None  # an assembly's parts list, on the title block

    @property
    def reserved(self) -> list[Box]:
        out = [self.title.grow(GAP), self.revision.grow(GAP), self.notes.grow(GAP), self.plot]
        if self.parts is not None:
            out.append(self.parts.grow(GAP))
        return out

    @property
    def area(self) -> Box:
        """Where views and their dimensions may go: inside the border, less a gap."""
        return self.border.grow(-GAP)


def frame(
    name: str,
    settings,
    *,
    note_height: float = 0.0,
    revisions: int = 0,
    parts_height: float = 0.0,
    parts_width: float = 0.0,
) -> SheetFrame:
    """Sheet ``name`` in the Settings' orientation, with room for ``note_height``
    millimetres of notes above the title block and ``revisions`` revision rows; with
    ``parts_height``, an assembly's parts list stands on the title block and the
    notes above it, ``parts_width`` wide when that is more than the title block (a long
    list's columns, or one whose texts need the room, reaching leftward)."""
    s = standards.SHEETS[name]
    w, h = s.size(settings.sheets.orientation)
    m = s.margin
    border = Box(m, m, w - m, h - m)
    tw, th = TITLE_SIZE.get(name, TITLE_SIZE_LARGE)
    title = Box(border.x1 - tw, border.y0, border.x1, border.y0 + th)
    rev_h = REVISION_ROW * (2 + max(1, revisions))
    revision = Box(border.x1 - tw, border.y1 - rev_h, border.x1, border.y1)
    pw = max(tw, parts_width)
    parts = Box(border.x1 - pw, title.y1, border.x1, title.y1 + parts_height) if parts_height > 0 else None
    base = parts.y1 if parts is not None else title.y1
    notes = Box(border.x1 - tw, base, border.x1, base + note_height)
    stamp = Box(m, h - m, w - m, h)
    plot = Box(border.x0, border.y0, border.x0 + PLOT_WIDTH, border.y0 + 4.0)
    cols, rows = (s.columns, s.rows) if settings.sheets.orientation == "landscape" else (s.rows, s.columns)
    return SheetFrame(name, w, h, m, cols, rows, border, title, revision, notes, stamp, plot, parts)


def continuation_frame(
    name: str, settings, *, parts_height: float = 0.0, parts_width: float = 0.0
) -> SheetFrame:
    """A sheet that continues a drawing's first, holding the rest of a parts list too
    long for it: the same size and border, the continuation title block in the same
    corner and as wide as the first's but lower (:data:`CONTINUATION_SHARE` of its
    height, :func:`.titleblock.continuation_block`), the parts list standing on it as on
    the first, and no revision block or notes, which the first sheet carries for the
    drawing."""
    f = frame(name, settings)
    b = f.border
    title = Box(f.title.x0, f.title.y0, f.title.x1, f.title.y0 + f.title.height * CONTINUATION_SHARE)
    pw = max(title.width, parts_width)
    parts = Box(b.x1 - pw, title.y1, b.x1, title.y1 + parts_height) if parts_height > 0 else None
    base = parts.y1 if parts is not None else title.y1
    return replace(
        f,
        title=title,
        revision=Box(b.x1, b.y1, b.x1, b.y1),
        notes=Box(title.x0, base, title.x1, base),
        parts=parts,
    )


def continuation_room(f: SheetFrame) -> float:
    """The height of the field above the title block of a continuation sheet ``f``,
    which its parts list may take whole."""
    return f.border.y1 - GAP - f.title.y1


def sheet_order(options, settings) -> list[str]:
    """The sheets to try: the drawing's, else the Settings', else every size smallest
    first."""
    if options.sheet != "auto":
        return [options.sheet]
    if settings.sheets.size != "auto":
        return [settings.sheets.size]
    return list(standards.SHEET_ORDER)


def scale_order(options, settings) -> list[tuple[int, int]]:
    """The scales to try, largest first: the drawing's own, else the Settings' list."""
    if options.scale != "auto":
        return [tuple(options.scale)]
    out = []
    for text in settings.sheets.scales:
        sc = standards.parse_scale(text)
        if sc is not None and sc not in out:
            out.append(sc)
    if not out:
        out = list(standards.SCALES)
    return sorted(out, key=lambda sc: -standards.scale_factor(sc))


__all__ = [
    "MIN_SPAN_MM",
    "SheetFrame",
    "continuation_frame",
    "continuation_room",
    "frame",
    "scale_order",
    "sheet_order",
]
