"""Notes, title fields and the tolerance block (``docs/DRAWINGS.md`` 10.6, 10.9,
10.10, 11.4).

The note list comes from the manufacturing type's templates in Drawing Settings,
each token filled from the drawing: a template whose token has no value is left
out rather than printed half empty. Under the datum scheme the general profile
note comes first; a part with unclaimed faces adds the model-governs note.

Title fields come from the wizard, else the part's properties under the
configured names, else the file name; the material through the mapping table;
the weight from the volume and the material's density, labelled CALC WT.
"""

from __future__ import annotations

import os
import re

from .. import numbers, standards
from ..numbers import plain_sum
from ..types import NoteLine
from . import gdt
from .context import Context
from .values import length_text

_TOKEN = re.compile(r"\{([a-z_]+)\}")
PROFILE_WORDS = "UNLESS OTHERWISE SPECIFIED, ALL SURFACES"
MODEL_NOTE_WORDS = "REDUCED-DIMENSION DRAWING OF MODEL"
# the notes an Express drawing keeps, by how they start: the model-governs note, and a
# printed part's general tolerance note, which its tolerance block points at
EXPRESS_NOTES = (MODEL_NOTE_WORDS, "GENERAL TOLERANCES")


def upper(text: str) -> str:
    """Capitals for a note, keeping the micro sign (its capital is a Greek letter the
    sheet's font does not have) and the units it leads (µm, µin) as they are written."""
    out = "".join(c if c == "\u00b5" else c.upper() for c in text)
    return out.replace("\u00b5M", "\u00b5m").replace("\u00b5IN", "\u00b5in")


TITLE_GROUPS = ("number", "part_number", "title", "revision", "model_revision", "material", "finish")


def title_fields(ctx: Context, source, fields: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Each title field's text and where it came from (``typed``, ``part`` or
    ``list``), by name: number, part_number, title, revision, model_revision,
    material, finish, weight, model."""
    out: dict[str, tuple[str, str]] = {}
    sources = ctx.settings.title_sources
    for group in TITLE_GROUPS:
        if fields.get(group):
            out[group] = (fields[group], "typed")
            continue
        names = getattr(sources, group)
        value = source.property(*names) if source is not None else None
        if value:
            out[group] = (value.strip(), "part")
    name = os.path.splitext(getattr(source, "name", "") or ctx.model.name or "PART")[0]
    out.setdefault("number", (name, "part"))
    out.setdefault("title", (name, "part"))
    out.setdefault("part_number", (out["number"][0], out["number"][1]))
    out.setdefault("revision", (ctx.settings.people.first_revision, "list"))
    material_name = out.get("material", (getattr(source, "material", None) or "", "part"))[0]
    entry = ctx.settings.material(material_name) if material_name else None
    if entry is not None:
        out["material"] = (entry["callout"], "list")
    elif material_name:
        out["material"] = (upper(material_name), "part")
    finish = out.get("finish")
    listed = ctx.settings.finish(finish[0]) if finish is not None else None
    if listed is not None:
        out["finish"] = (listed["callout"], "list")
    if ctx.settings.title_sources.show_weight and entry is not None and entry.get("density"):
        volume = plain_sum(b.volume for b in ctx.model.bodies)
        if volume > 0:
            kg = volume * entry["density"]
            if ctx.unit == "in":
                out["weight"] = (f"{kg / 0.45359237:.3f} LB", "list")
            else:
                out["weight"] = (f"{kg:.3f} KG", "list")
    sha = getattr(source, "sha256", None)
    if sha:
        model_rev = out.get("model_revision", ("", ""))[0]
        model = " ".join(t for t in (out["part_number"][0], model_rev, sha[:16].upper()) if t)
        out["model"] = (model, "part")
    if ctx.settings.standard.upper_case_notes:
        out = {k: ((upper(v) if k != "model" else v), s) for k, (v, s) in out.items()}
    return out


def _tokens(
    ctx: Context, title: dict[str, tuple[str, str]], fields: dict[str, str], fillet: float | None
) -> dict:
    s = ctx.settings
    inch = ctx.unit == "in"
    out = {
        "edge_break": s.notes.edge_break_in if inch else s.notes.edge_break_mm,
        "surface_finish": s.notes.surface_finish_in if inch else s.notes.surface_finish_mm,
        "material": title.get("material", ("", ""))[0],
        "finish": title.get("finish", ("", ""))[0],
        "process": _process_name(ctx, fields),
        "layer_height": fields.get("layer_height", ""),
        "model": title.get("part_number", ("", ""))[0],
        "model_rev": title.get("model_revision", ("", ""))[0],
        "model_hash": title.get("model", ("", ""))[0].split(" ")[-1] if "model" in title else "",
        "fillet_radius": ("R" + length_text(ctx, fillet, "width")) if fillet else "",
    }
    prof = gdt.profile(ctx)
    out["profile"] = gdt.zone_text(ctx, prof.value) if prof is not None else ""
    return out


def fill(template: str, tokens: dict[str, str]) -> str | None:
    """A template with its tokens filled, or None when one has no value."""
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        v = tokens.get(m.group(1), "")
        if not v:
            missing = True
        return v

    text = _TOKEN.sub(sub, template)
    return None if missing else text


def notes(
    ctx: Context,
    title: dict[str, tuple[str, str]],
    fields: dict[str, str],
    *,
    fillet: float | None,
    reduced: bool,
) -> tuple[NoteLine, ...]:
    """The numbered notes (10.6, 10.9, 10.10)."""
    out: list[NoteLine] = []
    capitals = ctx.settings.standard.upper_case_notes
    if ctx.scheme == "datum":
        prof = gdt.profile(ctx)
        if prof is not None:
            out.append(NoteLine(PROFILE_WORDS, (prof,)))
    if ctx.process == "printed":
        out.append(NoteLine(_process_note(ctx, fields)))
    tokens = _tokens(ctx, title, fields, fillet)
    templates = ctx.settings.notes.printed if ctx.process == "printed" else ctx.settings.notes.machined
    for t in templates:
        text = fill(t, tokens)
        if text:
            out.append(NoteLine(upper(text) if capitals else text))
    if reduced:
        out.append(model_note(ctx, title))
    return tuple(out)


def _process(ctx: Context, fields: dict[str, str]) -> dict | None:
    """The printing process a printed part names in ``fields``, else the first the
    settings list (the one the general tolerance note states)."""
    name = (fields.get("process") or "").casefold()
    chosen = None
    for p in ctx.settings.printing.processes:
        if p["name"].casefold() == name or (not name and chosen is None):
            chosen = p
            if name:
                break
    return chosen


def _process_name(ctx: Context, fields: dict[str, str]) -> str:
    """The process the notes name: the one given, else the settings' first for a
    printed part, so the process note and the tolerance note agree (R15.process)."""
    if fields.get("process"):
        return fields["process"]
    chosen = _process(ctx, fields) if ctx.process == "printed" else None
    return chosen["name"].upper() if chosen is not None else ""


def _process_note(ctx: Context, fields: dict[str, str]) -> str:
    """The printed part's general tolerance note from the process figures (10.6), each
    figure with its unit."""
    chosen = _process(ctx, fields)
    if chosen is None:
        return "GENERAL TOLERANCES PER THE PROCESS'S PUBLISHED FIGURES."
    inch = ctx.unit == "in"

    def amount(mm: float) -> str:
        if inch:
            return numbers.number(mm / 25.4, 3, "in") + " IN"
        return numbers.number(mm, max(1, numbers.places_needed(mm, 3)), "mm") + " MM"

    pm = standards.SYMBOL_PLUS_MINUS
    rate = f"{chosen['rate'] * 100:g} %"
    if chosen["xy_fixed_mm"] == chosen["z_fixed_mm"]:
        body = f"{pm}{amount(chosen['xy_fixed_mm'])} PLUS {rate} OF THE NOMINAL"
    else:
        body = (
            f"{pm}{amount(chosen['xy_fixed_mm'])} ALONG X AND Y AND {pm}{amount(chosen['z_fixed_mm'])} "
            f"ALONG Z, EACH PLUS {rate} OF THE NOMINAL"
        )
    if chosen.get("floor_mm"):
        body += f", NOT LESS THAN {pm}{amount(chosen['floor_mm'])}"
    return f"GENERAL TOLERANCES ({chosen['name'].upper()}): {body}."


def model_note(ctx: Context, title: dict[str, tuple[str, str]]) -> NoteLine:
    """The model-governs note of a reduced-dimension drawing (10.10), in our words."""
    # the model is named in capitals, as every note is lettered (R10.text), whatever case
    # the part's own number or file name has
    model = upper(title.get("model", ("", ""))[0] or title.get("part_number", ("", ""))[0])
    if ctx.options.detail == "simplified" or ctx.options.express:  # no GD&T: no profile frame
        return NoteLine(
            f"{MODEL_NOTE_WORDS} {model}. DIMENSIONS SHOWN TAKE PRECEDENCE OVER "
            "THE MODEL. FEATURES NOT DIMENSIONED ARE DEFINED BY THE MODEL."
        )
    text = (
        f"{MODEL_NOTE_WORDS} {model}. DIMENSIONS SHOWN TAKE PRECEDENCE OVER "
        "THE MODEL. SURFACES NOT DIMENSIONED ARE DEFINED BY THE MODEL WITHIN"
    )
    prof = gdt.profile(ctx, undimensioned=True)
    return NoteLine(text, (prof,) if prof is not None else ())


def tolerance_block(ctx: Context, note_numbers: dict[str, int] | None = None) -> tuple[str, ...]:
    """The title block's tolerance lines (11.4): the units statement, the decimal rows
    (or SEE NOTE n on a printed part), angles, and the interpretation, once."""
    unit_words = numbers.UNIT_WORDS[ctx.unit]
    lines = [f"UNLESS OTHERWISE SPECIFIED: DIMENSIONS ARE IN {unit_words}"]
    if ctx.process == "printed":
        n = (note_numbers or {}).get("process", 1)
        lines.append(f"GENERAL TOLERANCES: SEE NOTE {n}")
    else:
        rows = []
        for row in ctx.settings.block(ctx.unit):
            pattern = (
                ("." + "X" * row.places)
                if ctx.unit == "in"
                else ("X" + ("." + "X" * row.places if row.places else ""))
            )
            rows.append(f"{pattern} {numbers.band_text(row.plus_minus, ctx.unit)}")
        lines.append("TOLERANCES: " + "  ".join(rows))
        angle = numbers.angle_text(ctx.settings.tolerances.angle, 1)
        lines.append(f"ANGLES {standards.SYMBOL_PLUS_MINUS}{angle}")
    lines.append(standards.interpretation(ctx.settings))
    return tuple(lines)


__all__ = ["PROFILE_WORDS", "fill", "model_note", "notes", "title_fields", "tolerance_block"]
