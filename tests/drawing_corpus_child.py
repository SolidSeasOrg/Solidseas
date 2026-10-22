"""One part of the drawing corpus sweep (``test_drawing_corpus``) in a child process of its
own, and the counts the sweep keeps of its hard layout conflicts.

Run as ``python drawing_corpus_child.py PART SETTINGS``, it draws the part exactly as
``solidseas drawing check PART --settings SETTINGS --json`` does, with the title block
filled the sweep's way (:data:`FIELDS`, the material only where the part names none, and
the company in :data:`SETTINGS`), and prints one JSON object: ``envelope``, the envelope
that command prints; ``conflicts``, the drawing's hard conflicts (``R11.collisions``)
counted by what collides with what and by the views they are in (:func:`breakdown`),
with its sheet and scale and each hard conflict as layout's measure gives it
(:func:`measured`: the layout runs with ``measure`` on, which changes nothing on the
sheet), or null when no drawing was made; and ``title``, whether the title block shows a
calculated weight. Not a test module: the sweep runs it as a child process.

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


def _pair(check) -> str:
    """The kinds of the items a hard conflict is about (``dimension-note``), or of the
    item that found no clear place (``balloon-no_clear_place``)."""
    other = getattr(check, "other", "")
    names = sorted(item_kind(o) for o in ([check.item, other] if other else [check.item]))
    return "-".join(names if other else [*names, NO_PLACE])


def _view_type(check, views: dict[str, str], kinds: dict[str, str]) -> str:
    """The kinds of view a hard conflict's items are in (``base-projected``), ``sheet``
    for an item outside every view."""
    other = getattr(check, "other", "")
    found = set()
    for owner in [check.item, other] if other else [check.item]:
        view = views.get(owner)
        kind = "sheet" if view is None else kinds.get(view)
        found.add(kind if kind in (*VIEW_KINDS, "sheet") else "other")
    return "-".join(sorted(found))


def breakdown(drawing, kinds: dict[str, str]) -> dict:
    """The hard conflicts of ``drawing`` (its ``R11.collisions`` checks): ``conflicts``,
    how many; ``by_kind``, by the pair of item kinds that collide (``dimension-note``),
    or by the item that found no clear place (``balloon-no_clear_place``); and
    ``by_view_type``, by the kinds of view the items are in (``projected``,
    ``base-projected``, with ``sheet`` for an item outside every view). ``kinds`` maps
    view ids to their kinds (:func:`view_kinds`)."""
    views = _views_of_items(drawing.sheet)
    by_kind: Counter = Counter()
    by_view: Counter = Counter()
    total = 0
    for c in drawing.checks:
        if c.code != HARD_CONFLICT:
            continue
        total += 1
        by_kind[_pair(c)] += 1
        by_view[_view_type(c, views, kinds)] += 1
    return {"conflicts": total, "by_kind": dict(by_kind), "by_view_type": dict(by_view)}


# --------------------------------------------------------------------------- the measure
# What layout says of how it came to each hard conflict (solidseas.drawing.layout.measure):
# every layout of the child's process measures, and the drawing's own layout is the one that
# made its sheet.

LAYOUT_CODES = ("L.overlap", "L.placement")
DETAILED = 40  # drawings whose hard conflicts the sweep saves one by one, the most first
DETAILS = 40  # of each, the hard conflicts saved


def measuring() -> list:
    """Have every layout from now on in this process measure its conflicts
    (``layout(..., measure=True)``, which changes nothing on the sheet); returns the list
    each layout's result is added to."""
    from solidseas.drawing import orchestrate

    made: list = []
    real = orchestrate.layout

    def layout(*args, **kwargs):
        result = real(*args, **{**kwargs, "measure": True})
        made.append(result)
        return result

    orchestrate.layout = layout
    return made


def layout_of(drawing, made: list):
    """The layout result among ``made`` (:func:`measuring`) that made ``drawing``'s sheet,
    or None."""
    return next((r for r in reversed(made) if r.sheet is drawing.sheet), None)


def dimension_kinds(drawing) -> dict[str, str]:
    """Each planned dimension's kind (linear, ordinate, hole_callout, radius...) by its id,
    from the run this process keeps beside ``drawing``; empty when there is none."""
    from solidseas.drawing import edit

    live = edit.live_for(drawing)
    planned = getattr(live, "planned", None) if live is not None else None
    if planned is None:
        return {}
    return {d.id: d.kind for d in planned.plan.dimensions}


def _item(owner: str, dims: dict[str, str]) -> str:
    """What an item is, a dimension by its kind (``hole_callout``)."""
    kind = item_kind(owner)
    return dims.get(owner, kind) if kind == "dimension" else kind


def cause(facts: dict) -> str:
    """A hard conflict's cause in two words, the step that placed the item and what
    stopped it, for counting: ``leader.leader_across_line`` (the worst rule its place
    breaks), ``datum.no_room`` (less room past its face than the symbol reaches),
    ``datum.over_text`` (what stopped most of the spots it tried), ``overlap.band-band_frame``
    (the steps that placed two texts that overlap)."""
    from solidseas.drawing.layout.measure import RULES

    if "overlap_mm" in facts:
        return "overlap." + "-".join(sorted(s.split(".")[0] for s in facts.get("steps", ())))
    step = facts.get("step", "other")
    if facts.get("nowhere"):
        return f"{step}.nowhere"
    rules = [r for r in RULES if r in (facts.get("breaks") or {})]
    if step == "leader" and rules:
        return f"leader.{rules[0]}"
    if step == "datum" and facts.get("free_mm", 0) < facts.get("reach_mm", 0):
        return "datum.no_room"
    spots = facts.get("spots") or {}
    if spots:
        return f"{step}.{max(sorted(spots), key=spots.get)}"
    return f"{step}.no_clear_place"


def _plain(value):
    """``value`` as JSON holds it: tuples as lists."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def details(drawing, result, kinds: dict[str, str], dims: dict[str, str]) -> list[dict]:
    """Each hard conflict of ``drawing``, in numbers and fixed words: its pair of item
    kinds (``kind``) and kinds of view (``view``) as :func:`breakdown` counts them, what
    its items are (``item``, ``other_item``), and what layout's measure says of how it
    came to it (``result``, the layout that made the sheet; :func:`layout_of`) with its
    :func:`cause`, or the cause ``unmeasured`` where the layout said nothing of it."""
    facts_of = {}
    for c in getattr(result, "checks", ()) or ():
        if c.code in LAYOUT_CODES:
            facts_of.setdefault((c.owner, c.other, c.message), c.facts)
    views = _views_of_items(drawing.sheet)
    out = []
    for c in drawing.checks:
        if c.code != HARD_CONFLICT:
            continue
        row = {"kind": _pair(c), "view": _view_type(c, views, kinds), "item": _item(c.item, dims)}
        if c.other:
            row["other_item"] = _item(c.other, dims)
        facts = facts_of.get((c.item, c.other, c.message))
        if facts:
            row.update(_plain(facts))
            row["cause"] = cause(facts)
        else:
            row["cause"] = "unmeasured"
        out.append(row)
    return out


def measured(drawing, result, kinds: dict[str, str]) -> dict:
    """The sheet a drawing is on and its hard conflicts one by one (:func:`details`)."""
    sheet = drawing.sheet
    return {
        "sheet": str(sheet.name).lower(),
        "scale": list(sheet.scale),
        "details": details(drawing, result, kinds, dimension_kinds(drawing)),
    }


def drawing_row(counts: dict, hard: int, conflicts: dict | None) -> dict:
    """One drawing's row for :func:`summarise`, from the counts of its envelope, its
    number of ``R11.collisions`` checks and the child's :func:`breakdown`, with its
    sheet, scale and hard conflicts one by one (:func:`measured`) when the child gives
    them. Conflicts the breakdown does not account for (no breakdown, or one that
    counted another number) are counted under ``unknown``."""
    by_kind = dict(conflicts["by_kind"]) if conflicts else {}
    by_view = dict(conflicts["by_view_type"]) if conflicts else {}
    one_by_one = list((conflicts or {}).get("details") or ())
    if conflicts is None or conflicts["conflicts"] != hard:
        by_kind, by_view = ({"unknown": hard}, {"unknown": hard}) if hard else ({}, {})
        one_by_one = []
    row = {
        "dimensions": counts["shown"],
        "views": counts["views"],
        "conflicts": hard,
        "by_kind": by_kind,
        "by_view_type": by_view,
        "details": one_by_one,
    }
    if conflicts is not None and "sheet" in conflicts:
        row["sheet"], row["scale"] = conflicts["sheet"], conflicts["scale"]
    return row


def _band(value: int, bands) -> str:
    for top, name in bands:
        if top is None or value <= top:
            return name
    return bands[-1][1]


def summarise(rows: list[dict]) -> dict:
    """The sweep's saved measures of hard conflicts from one row per drawing
    (``dimensions``, ``views``, ``conflicts``, ``by_kind``, ``by_view_type``, with
    ``details``, ``sheet`` and ``scale`` where measured: :func:`drawing_row`): the
    conflicts by kind, by view type and by cause over every drawing, the drawings
    counted by their dimensions against their conflicts, the :data:`WORST` drawings
    with the most conflicts as rows of numbers, and for the :data:`DETAILED` drawings
    with the most, each hard conflict as layout's measure gives it (:func:`details`,
    at most :data:`DETAILS` of each), in no order a file could be told by."""
    by_kind: Counter = Counter()
    by_view: Counter = Counter()
    by_cause: Counter = Counter()
    grid = {d: {c: 0 for _t, c in CONFLICT_BANDS} for _top, d in DIMENSION_BANDS}
    for r in rows:
        by_kind.update(r["by_kind"])
        by_view.update(r["by_view_type"])
        details_ = r.get("details") or ()
        by_cause.update(d["cause"] for d in details_)
        if r["conflicts"] > len(details_):
            by_cause["unmeasured"] += r["conflicts"] - len(details_)
        grid[_band(r["dimensions"], DIMENSION_BANDS)][_band(r["conflicts"], CONFLICT_BANDS)] += 1
    hit = [r for r in rows if r["conflicts"]]
    hit.sort(
        key=lambda r: (
            -r["conflicts"],
            -r["dimensions"],
            -r["views"],
            sorted(r["by_kind"].items()),
            json.dumps(r.get("details") or [], sort_keys=True),
        )
    )
    worst = [
        {
            "dimensions": r["dimensions"],
            "views": r["views"],
            "conflicts": r["conflicts"],
            "by_kind": dict(sorted(r["by_kind"].items(), key=lambda kv: (-kv[1], kv[0]))),
        }
        for r in hit[:WORST]
    ]
    detailed = []
    for r in hit[:DETAILED]:
        one = {"dimensions": r["dimensions"], "views": r["views"], "conflicts": r["conflicts"]}
        if "sheet" in r:
            one["sheet"], one["scale"] = r["sheet"], list(r["scale"])
        one["details"] = sorted(r.get("details") or [], key=lambda d: json.dumps(d, sort_keys=True))[:DETAILS]
        detailed.append(one)
    return {
        "hard_conflicts_by_kind": dict(sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))),
        "hard_conflicts_by_view_type": dict(sorted(by_view.items(), key=lambda kv: (-kv[1], kv[0]))),
        "hard_conflicts_by_cause": dict(sorted(by_cause.items(), key=lambda kv: (-kv[1], kv[0]))),
        "drawings_by_dimensions_and_conflicts": grid,
        "worst_drawings": worst,
        "conflict_details": detailed,
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
    made = measuring()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["drawing", "check", part, "--settings", settings, "--json"])
    envelope = json.loads(out.getvalue())
    drawing = seen.get("drawing")
    conflicts = title = None
    if drawing is not None and envelope.get("ok"):
        kinds = view_kinds(drawing)
        conflicts = {**breakdown(drawing, kinds), **measured(drawing, layout_of(drawing, made), kinds)}
        title = {"weight": int(shows_weight(drawing))}
    sys.stdout.write(json.dumps({"envelope": envelope, "conflicts": conflicts, "title": title}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
