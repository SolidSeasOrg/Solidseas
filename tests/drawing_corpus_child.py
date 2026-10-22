"""One part of the drawing corpus sweep (``test_drawing_corpus``) in a child process of its
own, and the counts the sweep keeps of its hard layout conflicts.

Run as ``python drawing_corpus_child.py PART SETTINGS``, it draws the part exactly as
``solidseas drawing check PART --settings SETTINGS --json`` does, with the title block
filled the sweep's way (:data:`FIELDS`, the material only where the part names none, and
the company in :data:`SETTINGS`), and prints one JSON object: ``envelope``, the envelope
that command prints; ``conflicts``, the drawing's hard conflicts (``R11.collisions``)
counted by what collides with what and by the views they are in (:func:`breakdown`), or
null when no drawing was made; and ``title``, whether the title block shows a calculated
weight. Not a test module: the sweep runs it as a child process.

The counts hold only fixed words and numbers, never a name or a text of the part.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from collections import Counter

HARD_CONFLICT = "R11.collisions"
# The title block the sweep's drawings carry. The number, title and part number come
# from the file name, as they do for any part whose properties name none; drawn by,
# finish and the company are typed, and the material too where the part names none
# (:func:`typed_fields`), so check R6.title is about the drawing rather than about what
# the corpus parts leave empty, while a part's own material, the weight it gives and
# the checks of it are measured as they are.
FIELDS = {"drawn_by": "CORPUS SWEEP", "material": "SEE MODEL", "finish": "SEE MODEL"}
SETTINGS = {"schema": "solidseas.drawing-settings/1", "company": {"name": "CORPUS SWEEP"}}

# An item on the sheet by the owner of its text (drawing/layout): d-3, d-3-frame, n-2,
# datum-A, balloon-4, v-2-label and the sheet's own blocks.
_BLOCKS = {
    "title": "title_block",
    "tolerance": "title_block",
    "projection": "title_block",
    "logo": "title_block",
    "revisions": "revision_block",
    "notes": "note",
    "stamp": "stamp",
    "plot": "stamp",
    "border": "border",
    "parts": "parts_list",
    "build": "build_arrow",
}
_HEADS = {"d": "dimension", "n": "note", "datum": "datum", "balloon": "balloon"}
NO_PLACE = "no_clear_place"  # L.placement: an item laid out where nothing was clear
VIEW_KINDS = ("base", "projected", "section", "detail", "isometric")
DIMENSION_BANDS = (
    (24, "0-24"),
    (49, "25-49"),
    (99, "50-99"),
    (199, "100-199"),
    (499, "200-499"),
    (None, "500-up"),
)
CONFLICT_BANDS = ((0, "0"), (4, "1-4"), (19, "5-19"), (99, "20-99"), (None, "100-up"))
WORST = 10


def typed_fields(source, settings) -> dict[str, str]:
    """The fields the sweep types for a part: :data:`FIELDS`, less the material where the
    part names one, through the settings' property names or as its own material
    (``document.part_title_fields``, the title block's own rule), so that its drawing
    shows the part's material."""
    from solidseas.drawing import document

    if document.part_title_fields(source, settings).get("material") is not None:
        return {k: v for k, v in FIELDS.items() if k != "material"}
    return dict(FIELDS)


def shows_weight(drawing) -> bool:
    """Whether the title block on ``drawing``'s sheet shows a calculated weight (CALC WT,
    from the material's density in the settings' list)."""
    from solidseas.drawing import display as D

    sheet = getattr(drawing, "sheet", None)
    for a in getattr(sheet, "annotations", ()) or ():
        if isinstance(a, D.TitleBlock) and str(dict(a.fields).get("weight") or "").strip():
            return True
    return False


MATERIAL_FROM = ("part", "list", "typed")


def title_row(data: dict, title: dict | None) -> dict:
    """One drawing's title measures for :func:`summarise_titles`, from the ``data`` of its
    envelope and the child's ``title``: where its material came from (``part``, ``list``
    or ``typed``, ``none`` when the title block has none), whether it shows a weight,
    and its R6.material findings by level."""
    material = (data.get("drawing") or {}).get("title", {}).get("material") or {}
    origin = material.get("from") if material.get("text") else "none"
    findings = Counter(c["level"] for c in data.get("checks", ()) if c["code"] == "R6.material")
    return {
        "material_from": origin if origin in MATERIAL_FROM or origin == "none" else "other",
        "weight": int(bool(title and title.get("weight"))),
        "material_checks": dict(findings),
    }


def summarise_titles(rows: list[dict]) -> dict:
    """What the sweep measures of the title blocks over its drawings (:func:`title_row`):
    drawings by where their material came from, how many show a calculated weight, and
    the R6.material findings by level."""
    origins: Counter = Counter(r["material_from"] for r in rows)
    findings: Counter = Counter()
    for r in rows:
        findings.update(r["material_checks"])
    return {
        "material_from": dict(sorted(origins.items())),
        "weight_shown": sum(r["weight"] for r in rows),
        "material_checks": dict(sorted(findings.items())),
    }


def item_kind(owner: str) -> str:
    """The kind of item a text's owner is: dimension, frame, datum, note, balloon,
    parts_list, title_block, revision_block, stamp, border, view_label, build_arrow or
    other."""
    if owner.endswith("-frame"):
        return "frame"
    if owner.startswith("v-") and owner.endswith("-label"):
        return "view_label"
    if owner in _BLOCKS:
        return _BLOCKS[owner]
    head, _sep, rest = owner.partition("-")
    return _HEADS.get(head, "other") if rest else "other"


def _views_of_items(sheet) -> dict[str, str]:
    """The view each owner on ``sheet`` belongs to, for the items that have one."""
    out: dict[str, str] = {}
    for a in getattr(sheet, "annotations", ()) or ():
        view = getattr(a, "view", "") or ""
        name = type(a).__name__
        if not view:
            continue
        if name == "Dimension":
            out[a.id] = view
            out[f"{a.id}-frame"] = view
        elif name == "DatumFeature":
            out[f"datum-{a.letter}"] = view
        elif name == "Balloon":
            out[f"balloon-{a.item}"] = view
        elif name == "ViewLabel":
            out[f"{view}-label"] = view
    return out


def view_kinds(drawing) -> dict[str, str]:
    """Each view's kind (base, projected, section, detail, isometric) by its id, from
    the run this process keeps beside ``drawing``; empty when there is none."""
    from solidseas.drawing import edit

    live = edit.live_for(drawing)
    planned = getattr(live, "planned", None) if live is not None else None
    if planned is None:
        return {}
    return {v.id: v.kind for v in planned.plan.views}


def breakdown(drawing, kinds: dict[str, str]) -> dict:
    """The hard conflicts of ``drawing`` (its ``R11.collisions`` checks): ``conflicts``,
    how many; ``by_kind``, by the pair of item kinds that collide (``dimension-note``),
    or by the item that found no clear place (``balloon-no_clear_place``); and
    ``by_view_type``, by the kinds of view the items are in (``projected``,
    ``base-projected``, with ``sheet`` for an item outside every view). ``kinds`` maps
    view ids to their kinds (:func:`view_kinds`)."""
    views = _views_of_items(drawing.sheet)

    def view_type(owner: str) -> str:
        view = views.get(owner)
        if view is None:
            return "sheet"
        kind = kinds.get(view)
        return kind if kind in VIEW_KINDS else "other"

    by_kind: Counter = Counter()
    by_view: Counter = Counter()
    total = 0
    for c in drawing.checks:
        if c.code != HARD_CONFLICT:
            continue
        total += 1
        other = getattr(c, "other", "")
        owners = [c.item, other] if other else [c.item]
        names = sorted(item_kind(o) for o in owners)
        if not other:
            names.append(NO_PLACE)
        by_kind["-".join(names)] += 1
        by_view["-".join(sorted({view_type(o) for o in owners}))] += 1
    return {"conflicts": total, "by_kind": dict(by_kind), "by_view_type": dict(by_view)}


def drawing_row(counts: dict, hard: int, conflicts: dict | None) -> dict:
    """One drawing's row for :func:`summarise`, from the counts of its envelope, its
    number of ``R11.collisions`` checks and the child's :func:`breakdown`. Conflicts the
    breakdown does not account for (no breakdown, or one that counted another number)
    are counted under ``unknown``."""
    by_kind = dict(conflicts["by_kind"]) if conflicts else {}
    by_view = dict(conflicts["by_view_type"]) if conflicts else {}
    if conflicts is None or conflicts["conflicts"] != hard:
        by_kind, by_view = ({"unknown": hard}, {"unknown": hard}) if hard else ({}, {})
    return {
        "dimensions": counts["shown"],
        "views": counts["views"],
        "conflicts": hard,
        "by_kind": by_kind,
        "by_view_type": by_view,
    }


def _band(value: int, bands) -> str:
    for top, name in bands:
        if top is None or value <= top:
            return name
    return bands[-1][1]


def summarise(rows: list[dict]) -> dict:
    """The sweep's saved measures of hard conflicts from one row per drawing
    (``dimensions``, ``views``, ``conflicts``, ``by_kind``, ``by_view_type``): the
    conflicts by kind and by view type over every drawing, the drawings counted by
    their dimensions against their conflicts, and the :data:`WORST` drawings with
    the most conflicts as rows of numbers, in no order a file could be told by."""
    by_kind: Counter = Counter()
    by_view: Counter = Counter()
    grid = {d: {c: 0 for _t, c in CONFLICT_BANDS} for _top, d in DIMENSION_BANDS}
    for r in rows:
        by_kind.update(r["by_kind"])
        by_view.update(r["by_view_type"])
        grid[_band(r["dimensions"], DIMENSION_BANDS)][_band(r["conflicts"], CONFLICT_BANDS)] += 1
    hit = [r for r in rows if r["conflicts"]]
    hit.sort(key=lambda r: (-r["conflicts"], -r["dimensions"], -r["views"], sorted(r["by_kind"].items())))
    worst = [
        {
            "dimensions": r["dimensions"],
            "views": r["views"],
            "conflicts": r["conflicts"],
            "by_kind": dict(sorted(r["by_kind"].items(), key=lambda kv: (-kv[1], kv[0]))),
        }
        for r in hit[:WORST]
    ]
    return {
        "hard_conflicts_by_kind": dict(sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))),
        "hard_conflicts_by_view_type": dict(sorted(by_view.items(), key=lambda kv: (-kv[1], kv[0]))),
        "drawings_by_dimensions_and_conflicts": grid,
        "worst_drawings": worst,
    }


def main(argv: list[str]) -> int:
    part, settings = argv
    from solidseas import cli
    from solidseas.drawing import source as drawing_source

    seen: dict = {}
    make, checks, opener = cli._make, cli._drawing_checks, drawing_source.open_source

    def make_filled(part, options, settings, fields, **kw):
        # what to type is known once the part is read (open_filled), which the command
        # does before the pipeline reads these fields
        filled = dict(fields)
        seen["fill"] = (filled, settings)
        return make(part, options, settings, filled, **kw)

    def open_filled(*args, **kwargs):
        source = opener(*args, **kwargs)
        fill = seen.pop("fill", None)
        if fill is not None:
            filled, settings_ = fill
            for key, value in typed_fields(source, settings_).items():
                filled.setdefault(key, value)
        return source

    def checks_seen(drawing, run=None):
        seen["drawing"] = drawing
        return checks(drawing, run)

    cli._make, cli._drawing_checks = make_filled, checks_seen
    drawing_source.open_source = open_filled
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["drawing", "check", part, "--settings", settings, "--json"])
    envelope = json.loads(out.getvalue())
    drawing = seen.get("drawing")
    conflicts = title = None
    if drawing is not None and envelope.get("ok"):
        conflicts = breakdown(drawing, view_kinds(drawing))
        title = {"weight": int(shows_weight(drawing))}
    sys.stdout.write(json.dumps({"envelope": envelope, "conflicts": conflicts, "title": title}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
