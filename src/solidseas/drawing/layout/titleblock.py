"""The title block and the revision block (``docs/DRAWINGS.md`` 11.4).

The ASME block, one layout for B to E and a compact one for A, in the lower right:
on the right the company with its logo, the title, then size, CAGE, drawing number
and revision; scale, calculated weight and sheet; status and the model with its
revision and short hash; material and finish. On the left the tolerance block
(units, the decimal rows or SEE NOTE n, angles, the interpretation, once), the
projection symbol, the approval rows, each empty until signed except DRAWN, and
the proprietary statement and DO NOT SCALE DRAWING. A text too long for its cell
is set smaller, down to a floor, then cut with an ellipsis; the model's is cut in its
part number, so its revision and short hash stay whole. The title and the
drawing number are kept at the lettering minimum where they can be (22 rule 10):
a long title goes on two lines, its row taller, before it is set smaller; a long
drawing number takes the CAGE cell's width when the company has no CAGE code. The
revision block in the upper right holds one row per revision.
"""

from __future__ import annotations

from .. import display as D
from .. import standards
from ..images import PngRefused, png_size
from .glyphs import THICK, THIN, Pen, text_width
from .index import Box

LABEL = 1.6  # label text height, millimetres
FLOOR = 1.8  # the smallest value text
LOGO_SHARE = 0.5  # the most of the company cell's width the logo takes


def fit_text(
    pen: Pen,
    box: Box,
    text: str,
    height: float,
    *,
    bold: bool = False,
    anchor: str = "left",
    owner: str = "title",
    least: float | None = None,
    keep: str = "",
) -> Box:
    """``text`` in ``box``, its baseline a little above the bottom, smaller or cut
    when it does not fit; ``least`` is a height tried on the way down, so a text
    that fits at the lettering minimum is set at it, never just below. ``keep``, an
    end of ``text``, is not cut: the ellipsis goes before it."""
    if not text:
        return box
    h = _fitting(text, box.width - 2.0, height, bold, least)
    room = box.width - 2.0
    shown = _cut(text, room, h, bold, keep)
    x = {"left": box.x0 + 1.0, "centre": (box.x0 + box.x1) / 2, "right": box.x1 - 1.0}[anchor]
    y = box.y0 + max(0.8, (box.height - LABEL - 0.6 - h) / 2 + 0.4)
    return pen.text(x, y, h, shown, bold=bold, anchor=anchor, layer="title", owner=owner, keep=False)


def _cut(text: str, room: float, h: float, bold: bool, keep: str = "") -> str:
    """``text`` cut with an ellipsis to fit ``room`` at ``h``. ``keep``, an end of
    ``text``, stays whole after the ellipsis, unless even it does not fit."""
    end = keep if keep and len(keep) < len(text) and text.endswith(keep) else ""
    shown = text[: len(text) - len(end)]
    while text_width(shown + end, h, bold) > room and len(shown) > 1:
        shown = shown[:-2] + "…"
    if end and text_width(shown + end, h, bold) > room:
        return _cut(text, room, h, bold)
    return shown + end


def _model_end(model: str, part_number: str) -> str:
    """The end of the MODEL value the cell keeps whole: what follows the part
    number (the model's revision and short hash, 10.10), else its last word."""
    if part_number and model.startswith(part_number + " "):
        return model[len(part_number) :]
    return model[model.rfind(" ") :] if " " in model.strip() else ""


def _fitting(text: str, room: float, height: float, bold: bool, least: float | None = None) -> float:
    """The height ``text`` is set at to fit ``room``: ``height``, else smaller in steps
    of 0.1 mm (``least`` among them) down to :data:`FLOOR`."""
    h = height
    while h > FLOOR and text_width(text, h, bold) > room:
        step = h - 0.1
        if least is not None and h > least + 1e-9 and step < least:
            step = least
        h = max(FLOOR, step)
    return h


def _cell(
    pen: Pen,
    box: Box,
    label: str,
    text: str,
    height: float,
    *,
    bold: bool = False,
    owner: str = "title",
    least: float | None = None,
    keep: str = "",
) -> None:
    pen.rect(box, width=THIN, layer="title", owner=owner)
    if label:
        pen.text(box.x0 + 0.8, box.y1 - LABEL - 0.6, LABEL, label, layer="title", owner=owner, keep=False)
        # the value stays under its label: no taller than the cell leaves below it
        height = min(height, max(FLOOR, box.height - LABEL - 2.2))
    fit_text(pen, box, text, height, bold=bold, owner=owner, least=least, keep=keep)


def _two_lines(text: str, room: float, bold: bool) -> tuple[str, str] | None:
    """``text`` broken between two words into the two lines whose longer is shortest,
    or None for a single word."""
    words = text.split()
    if len(words) < 2:
        return None
    best: tuple[float, tuple[str, str]] | None = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        wide = max(text_width(a, 1.0, bold), text_width(b, 1.0, bold))
        if best is None or wide < best[0]:
            best = (wide, (a, b))
    return best[1] if best else None


def _title_wraps(text: str, room: float, height: float, least: float) -> bool:
    """Whether the TITLE goes on two lines: one line would be set below ``least``."""
    return (
        bool(text)
        and _fitting(text, room, height, True, least) < least - 1e-9
        and _two_lines(text, room, True) is not None
    )


def _title_cell(pen: Pen, box: Box, text: str, height: float, least: float) -> None:
    """The TITLE cell with its value on two lines, each as large as the cell allows up
    to ``height``, set smaller (and the second cut) only when two lines at ``least``
    do not fit."""
    pen.rect(box, width=THIN, layer="title", owner="title")
    pen.text(box.x0 + 0.8, box.y1 - LABEL - 0.6, LABEL, "TITLE", layer="title", owner="title", keep=False)
    room = box.width - 2.0
    first, second = _two_lines(text, room, True) or (text, "")
    # two lines a pitch of 1.4 heights apart, under the label: 0.8 + 2.4 h fits below it
    h = min(height, max(FLOOR, (box.height - LABEL - 2.2 - 0.8) / 2.4))
    wider = first if text_width(first, 1.0, True) >= text_width(second, 1.0, True) else second
    h = _fitting(wider, room, h, True, least)
    y = box.y0 + 0.8
    for line in (second, first):
        shown = _cut(line, room, h, True)
        pen.text(box.x0 + 1.0, y, h, shown, bold=True, layer="title", owner="title", keep=False)
        y += h * 1.4


def _logo_box(logo: bytes, cell: Box) -> Box:
    """Where the logo goes in the company cell: in the image's own proportions, as tall
    as the cell less a millimetre above and below, at most :data:`LOGO_SHARE` of the
    cell's width (a wide logo is then less tall, centred top to bottom), against the
    cell's right side. A logo whose header the writers would refuse keeps a box two to
    one, as before, and they report it."""
    try:
        pw, ph = png_size(logo)
        aspect = pw / ph
    except PngRefused:
        aspect = 2.0
    h = max(cell.height - 2.0, 0.0)
    w = h * aspect
    most = cell.width * LOGO_SHARE
    if w > most:
        w, h = most, most / aspect
    x = cell.x1 - 1.0 - w
    y = cell.y0 + (cell.height - h) / 2
    return Box(x, y, x + w, y + h)


def title_block(
    pen: Pen,
    area: Box,
    *,
    unit: str,
    fields: dict[str, str],
    tolerance_lines: tuple[str, ...],
    rows: tuple[str, ...],
    signed: dict[str, tuple[str, str]],
    company,
    logo: bytes | None,
    logo_sha: str = "",
) -> list:
    """Paint the title block in ``area`` and return its annotations."""
    t = standards.TEXT[unit]
    x0, y0, x1, y1 = area.x0, area.y0, area.x1, area.y1
    w, h = area.width, area.height
    pen.rect(area, width=THICK, layer="title", owner="title")
    split = x0 + w * 0.45
    out: list = []
    # ----------------------------------------------------------- the right part
    rw = x1 - split
    least = t.dimension
    title = fields.get("title", "")
    # a title on two lines takes a taller row from the company's and the material's
    wraps = _title_wraps(title, rw - 2.0, min(t.title, max(FLOOR, h * 0.19 - LABEL - 2.2)), least)
    r_rows = [0.20, 0.25, 0.16, 0.13, 0.13, 0.13] if wraps else [0.21, 0.19, 0.16, 0.13, 0.13, 0.18]
    ys = [y1]
    for share in r_rows:
        ys.append(ys[-1] - share * h)
    company_box = Box(split, ys[1], x1, ys[0])
    pen.rect(company_box, width=THIN, layer="title", owner="title")
    logo_box = _logo_box(logo, company_box) if logo else None
    name_w = rw - (logo_box.width + 2.0 if logo_box is not None else 0.0)
    fit_text(
        pen,
        Box(split, ys[1] + company_box.height * 0.45, split + name_w, ys[0]),
        company.name,
        t.block_label * 1.6,
        bold=True,
    )
    if company.address:
        fit_text(
            pen,
            Box(split, ys[1], split + name_w, ys[1] + company_box.height * 0.45),
            ", ".join(company.address),
            LABEL * 1.1,
        )
    if logo_box is not None:
        lx, ly, lw, lh = logo_box.x0, logo_box.y0, logo_box.width, logo_box.height
        pen.items.append(D.ImageRun(lx, ly, lw, lh, logo, "title", "logo"))
        out.append(D.Image((lx, ly), lw, lh, logo, logo_sha))
    if wraps:
        _title_cell(pen, Box(split, ys[2], x1, ys[1]), title, t.title, least)
    else:
        _cell(pen, Box(split, ys[2], x1, ys[1]), "TITLE", title, t.title, bold=True, least=least)
    third = [
        ("SIZE", "size", 0.12),
        ("CAGE", "cage", 0.16),
        ("DWG NO", "number", 0.56),
        ("REV", "revision", 0.16),
    ]
    number = fields.get("number", "")
    if not fields.get("cage") and text_width(number, least, True) > rw * 0.56 - 2.0:
        # CAGE is optional (11.4): without a code its width goes to a long number
        third = [("SIZE", "size", 0.12), ("DWG NO", "number", 0.72), ("REV", "revision", 0.16)]
    cx = split
    for label, key, share in third:
        cw = rw * share
        _cell(
            pen,
            Box(cx, ys[3], cx + cw, ys[2]),
            label,
            fields.get(key, ""),
            t.number if key == "number" else t.block_label * 1.4,
            bold=key == "number",
            least=least if key == "number" else None,
        )
        cx += cw
    fourth = [("SCALE", "scale", 0.25), ("CALC WT", "weight", 0.4), ("SHEET", "sheet", 0.35)]
    cx = split
    for label, key, share in fourth:
        cw = rw * share
        _cell(pen, Box(cx, ys[4], cx + cw, ys[3]), label, fields.get(key, ""), t.block_label * 1.2)
        cx += cw
    _cell(
        pen,
        Box(split, ys[5], split + rw * 0.35, ys[4]),
        "STATUS",
        fields.get("status", ""),
        t.block_label * 1.2,
        bold=True,
    )
    model = fields.get("model", "")
    _cell(
        pen,
        Box(split + rw * 0.35, ys[5], x1, ys[4]),
        "MODEL / MODEL REV",
        model,
        t.block_label,
        keep=_model_end(model, fields.get("part_number", "")),
    )
    _cell(
        pen,
        Box(split, y0, split + rw * 0.5, ys[5]),
        "MATERIAL",
        fields.get("material", ""),
        t.block_label * 1.1,
    )
    _cell(pen, Box(split + rw * 0.5, y0, x1, ys[5]), "FINISH", fields.get("finish", ""), t.block_label * 1.1)
    # ----------------------------------------------------------- the left part
    lw_ = split - x0
    tol_h = h * 0.42
    tol_box = Box(x0, y1 - tol_h, split, y1)
    pen.rect(tol_box, width=THIN, layer="title", owner="title")
    proj = 9.0 if w > 150 else 7.0
    room_w = lw_ - 3.0
    line_h = LABEL * 1.15
    while True:
        wrapped = [part for line in tolerance_lines for part in _wrap(line, room_w, line_h)]
        if len(wrapped) * line_h * 1.35 + proj <= tol_h - 1.0 or line_h <= 1.0:
            break
        line_h -= 0.05
    ty = y1 - line_h - 1.2
    for line in wrapped:
        pen.text(x0 + 1.0, ty, line_h, line, layer="title", owner="tolerance", keep=False)
        ty -= line_h * 1.35
    out.append(D.ToleranceBlock((x0 + 1.0, y1 - line_h - 1.2), tuple(tolerance_lines)))
    pb = pen.projection_symbol(
        split - proj * 2.05, tol_box.y0 + 1.5, proj * 0.75, layer="title", owner="projection"
    )
    out.append(D.ProjectionSymbol((pb.x0, pb.y0), proj * 0.75, "third"))
    # approval rows: name and date, empty until signed (DRAWN is signed when made)
    n = max(1, len(rows))
    bottom_h = h * 0.2
    row_h = (tol_box.y0 - (y0 + bottom_h)) / n
    ry = tol_box.y0
    for row in rows:
        name, date = signed.get(row, ("", ""))
        _cell(pen, Box(x0, ry - row_h, x0 + lw_ * 0.3, ry), "", row, LABEL * 1.1)
        _cell(pen, Box(x0 + lw_ * 0.3, ry - row_h, x0 + lw_ * 0.68, ry), "NAME", name, LABEL * 1.1)
        _cell(pen, Box(x0 + lw_ * 0.68, ry - row_h, split, ry), "DATE", date, LABEL * 1.1)
        ry -= row_h
    statement = Box(x0, y0, split, y0 + bottom_h)
    pen.rect(statement, width=THIN, layer="title", owner="title")
    words = " ".join(company.proprietary.split()).replace("{company}", (company.name or "ITS OWNER").upper())
    if company.do_not_scale:
        fit_text(
            pen,
            Box(x0, y0 + bottom_h * 0.55, split, y0 + bottom_h),
            "DO NOT SCALE DRAWING",
            LABEL * 1.2,
            bold=True,
        )
    small = 1.2
    _wrap_into(pen, Box(x0, y0, split, y0 + bottom_h * (0.55 if company.do_not_scale else 1.0)), words, small)
    out.append(D.TitleBlock((x0, y0), w, h, tuple(sorted(fields.items()))))
    return out


def _wrap(text: str, width: float, h: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if not cur or text_width(trial, h) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


SMALLEST = 0.9  # the proprietary statement's text, at the least, millimetres


def _lines(words: str, width: float, h: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in words.split():
        trial = (cur + " " + word).strip()
        if text_width(trial, h) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _wrap_into(pen: Pen, box: Box, words: str, h: float) -> None:
    """Words wrapped into a box in small text, set smaller (down to :data:`SMALLEST`)
    until every line fits, so the statement is never cut short."""
    lines = _lines(words, box.width - 2.0, h)
    while h > SMALLEST + 1e-9 and 0.8 + h + (len(lines) - 1) * h * 1.3 > box.height - 0.3:
        h = max(SMALLEST, h - 0.05)
        lines = _lines(words, box.width - 2.0, h)
    y = box.y1 - h - 0.8
    for line in lines:
        if y < box.y0 + 0.3:
            break
        pen.text(box.x0 + 1.0, y, h, line, layer="title", owner="title", keep=False)
        y -= h * 1.3


def revision_block(pen: Pen, area: Box, revisions) -> list:
    """The revision block: a header and one row per revision (an empty one first)."""
    pen.rect(area, width=THIN, layer="title", owner="revisions")
    cols = [("ZONE", 0.12), ("REV", 0.1), ("DESCRIPTION", 0.46), ("DATE", 0.16), ("APPROVED", 0.16)]
    row_h = 6.0
    y = area.y1 - row_h
    fit_text(
        pen,
        Box(area.x0, y, area.x1, area.y1),
        "REVISIONS",
        LABEL * 1.2,
        bold=True,
        anchor="centre",
        owner="revisions",
    )
    y -= row_h
    cx = area.x0
    for label, share in cols:
        cw = area.width * share
        _cell(pen, Box(cx, y, cx + cw, y + row_h), "", label, LABEL * 1.1, owner="revisions")
        cx += cw
    for rev in revisions:
        y -= row_h
        if y < area.y0 - 1e-6:
            break
        values = [" ".join(rev.zones), rev.rev, rev.description, rev.date or "", rev.approved or ""]
        cx = area.x0
        for (_label, share), text in zip(cols, values, strict=True):
            cw = area.width * share
            _cell(pen, Box(cx, y, cx + cw, y + row_h), "", text, LABEL * 1.1, owner="revisions")
            cx += cw
    return []


__all__ = ["fit_text", "revision_block", "title_block"]
