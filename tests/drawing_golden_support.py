"""What the golden drawings are made from and how they are summarised
(``docs/DRAWINGS.md`` 19.4 and 19.5; ``tests/test_drawing_golden.py`` runs them and
``docs/drawings/goldens.md`` lists them).

Each golden is one part drawn one way: a SOLIDWORKS fixture through
``make_drawing``, a synthetic part of ``drawing_parts`` through ``pipeline.run``
with a stand-in for the ``source`` stage (the part is a transmit, not a file), or a
drawing regenerated against a changed model. :func:`made` builds a golden once per
test session and keeps everything the checks read: the drawing with its checks, the
pipeline run with the plan stage's own run (``Run.orchestrated``: the plan with its
detail and the layout), the model and the feature set, and for a regeneration the
merge report.

The summaries are what a golden file records as its snapshot: the plan (one record a
dimension, the graphs' verdicts, the notes and title fields, the drawing's checks), the SVG's numbers by
layer (rounded to a hundredth of a millimetre, 12.4), the PDF's inflated content and
text, and the DXF's tags. The SolidSeas version, which the plot stamp, the PDF's
content and the DXF's ``999`` comment carry, is written as ``{version}`` so a version
bump changes no snapshot.

Nothing here writes a file but o07's golden, which saves o02's drawing in
:data:`FOLDER` (a pytest temporary folder the test module sets), and
:func:`write_golden`, which the refresh run of the test module calls
(``SOLIDSEAS_REFRESH_GOLDENS=1``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import drawing_parts
import dxf_reader
import pdf_reader
from drawing_support import COMPANY, fixture
from solidseas import __version__, drawing
from solidseas.drawing import display as D
from solidseas.drawing import document as doc
from solidseas.drawing import edit, pipeline, svg
from solidseas.drawing import merge as merge_mod
from solidseas.drawing import settings as S
from solidseas.drawing.dxf import dxf_bytes
from solidseas.drawing.pdf import to_pdf
from solidseas.drawing.source import DrawingSource, SourceBody, SourceUnits
from solidseas.drawing.types import DrawingOptions
from solidseas.formats.solidworks.parasolid import ParasolidBody

GOLDENS_DIR = os.path.join(os.path.dirname(__file__), "goldens", "drawings")
REFRESH_VARIABLE = "SOLIDSEAS_REFRESH_GOLDENS"
VERSION_TOKEN = "{version}"
# Where o07's golden saves o02's drawing before loading it: the test module points it at
# a pytest temporary folder, since tests write nowhere else.
FOLDER: str | None = None
# The hard layout conflicts (R11.collisions): text over text and an item layout could
# not place clear, which the checklist files under R11.collisions, and text outside the
# border or in the title, revision or notes block, which it files under R8.sheet with
# the layout's own words. A leader's angle and a cramped span are warnings.
HARD_LAYOUT = ("L.overlap", "L.outside", "L.reserved", "L.placement")
HARD_SHEET_WORDS = ("lies outside the border", "lies in the title, revision or notes block")


# --------------------------------------------------------------------------- the goldens


@dataclass(frozen=True)
class Golden:
    """One golden: how it is made. ``kind`` is ``fixture`` (a SOLIDWORKS part through
    ``make_drawing``), ``synthetic`` (a part of ``drawing_parts`` through
    ``pipeline.run``), ``regenerated`` (o02's drawing, saved, loaded and regenerated
    against o07) or ``pair`` (a regeneration pair of ``drawing_parts``)."""

    name: str
    kind: str
    part: str
    unit: str
    process: str = "machined"


GOLDENS: tuple[Golden, ...] = (
    Golden("o02-mm", "fixture", "o02_boxA.SLDPRT", "mm"),
    Golden("o02-in", "fixture", "o02_boxA.SLDPRT", "in"),
    Golden("o07-from-o02", "regenerated", "o07_boxB_h31.SLDPRT", "mm"),
    Golden("o11-mm", "fixture", "o11_curved.SLDPRT", "mm"),
    Golden("o11-in", "fixture", "o11_curved.SLDPRT", "in"),
    Golden("hole-kinds", "synthetic", "hole_kinds_plate", "in"),
    Golden("patterns", "synthetic", "patterns_plate", "in"),
    Golden("arc-pattern", "synthetic", "arc_pattern_plate", "mm"),
    Golden("four-holes", "synthetic", "four_holes_plate", "in"),
    Golden("link", "synthetic", "link_plate", "in"),
    Golden("boss", "synthetic", "boss_block", "in"),
    Golden("pocket-tab", "synthetic", "pocket_tab_block", "in"),
    Golden("sixteen-holes", "synthetic", "sixteen_holes_plate", "in"),
    Golden("inclined-face", "synthetic", "inclined_hole_block", "in"),
    Golden("printed-bracket", "synthetic", "printed_bracket", "mm", "printed"),
    Golden("pair-midplane", "pair", "pair_midplane", "mm"),
    Golden("pair-origin-moved", "pair", "pair_origin_moved", "mm"),
    Golden("pair-pattern-grew", "pair", "pair_pattern_grew", "mm"),
    Golden("pair-datum-changes", "pair", "pair_datum_changes", "mm"),
)
BY_NAME = {g.name: g for g in GOLDENS}


def settings() -> S.DrawingSettings:
    """The ASME defaults with the fictional company every test uses."""
    return S.with_value(S.DrawingSettings(), "company", "name", COMPANY)


def options(g: Golden) -> DrawingOptions:
    return DrawingOptions(units=g.unit, process=g.process)


def source_stage(name: str, xt, truth: dict):
    """A stand-in for the pipeline's ``source`` stage that hands a synthetic transmit on
    as a part's one solid body: a real ``DrawingSource`` whose body is the transmit, so
    the ``model`` stage and everything after it run as they would on a file. The
    geometry digest is a hash of the part's ground truth, which changes exactly when
    the part does, and the file's SHA-256 a hash of the name and that digest: the
    file the part would be, so the title block's MODEL and the model-governs note can
    name it."""
    digest = hashlib.sha256(json.dumps(truth, sort_keys=True, default=repr).encode("utf-8")).hexdigest()
    sha = hashlib.sha256(f"{name}.SLDPRT {digest}".encode()).hexdigest()

    def stage(part=None, *, configuration=None, bodies=None, units=None, title_names=(), limits=None):
        body = ParasolidBody("Config-0/body1", 0, "Default", "partition", None, "solid", xt)
        unit = SourceUnits(units, "user", None, "mm") if units else SourceUnits("mm", "file", None, "mm")
        return DrawingSource(
            name=f"{name}.SLDPRT",
            format="sldprt",
            kind="brep",
            configuration="Default",
            bodies=(SourceBody("Config-0/body1", "solid", truth["faces"], True),),
            units=unit,
            material=None,
            properties=(),
            hints=(),
            sha256=sha,
            geometry_digest=digest,
            properties_digest="0" * 64,
            _bodies=(body,),
        )

    return stage


# --------------------------------------------------------------------------- making a golden


@dataclass
class Made:
    """Everything one golden's checks read. ``drawing`` is the drawing the golden shows,
    with its checks; ``run`` the pipeline run of the part as drawn (for a regeneration,
    of the new model) and ``orchestrated`` its plan stage's run (the plan with its
    detail, the layout with its checks); ``fresh`` makes a new drawing of that model,
    for check 6; ``source`` is the model, to regenerate against; ``same`` says whether
    ``fresh`` makes the very drawing the golden shows (not so for a regeneration,
    whose ids are inherited)."""

    golden: Golden
    drawing: Any
    run: pipeline.Run
    orchestrated: Any
    fresh: Any
    source: Any
    same: bool = True
    report: merge_mod.MergeReport | None = None


def _synthetic(name: str, xt, truth: dict, g: Golden) -> tuple[pipeline.Run, Any]:
    stage = source_stage(name, xt, truth)
    run = pipeline.run(None, options=options(g), settings=settings(), stages={"source": stage})
    return run, stage


def _o07(g: Golden) -> Made:
    """o02's millimetre drawing as a user leaves it in the editor (``edit.remove`` takes
    the 10.0 width off, ``edit.move`` moves the height), saved to :data:`FOLDER` and
    loaded, then regenerated against o07 (the height 30 to 31)."""
    if FOLDER is None:
        raise RuntimeError("set drawing_golden_support.FOLDER to a temporary folder first")
    first = drawing.make_drawing(fixture("o02_boxA.SLDPRT"), options=options(g), settings=settings())
    ids = {d.key: d.id for d in first.dimensions}
    edited, _checks = edit.remove(first, ids["size/f-1"])
    edited, _checks = edit.move(edited, ids["size/f-3"], 4.0, 6.0)
    path = os.path.join(FOLDER, "o02_boxA.ssdrw")
    if os.path.exists(path):
        os.remove(path)
    drawing.save(edited, path)
    loaded = drawing.load(path)
    merged, report = drawing.regenerate(loaded, source=fixture(g.part))
    run = pipeline.run(fixture(g.part), options=options(g), settings=settings())
    fresh = functools.partial(drawing.make_drawing, fixture(g.part), options=options(g), settings=settings())
    return Made(g, merged, run, run.orchestrated, fresh, fixture(g.part), False, report)


@functools.cache
def made(name: str) -> Made:
    """The golden ``name``, made once per session."""
    g = BY_NAME[name]
    if g.kind == "fixture":
        path = fixture(g.part)
        d = drawing.make_drawing(path, options=options(g), settings=settings())
        run = pipeline.run(path, options=options(g), settings=settings())
        fresh = functools.partial(drawing.make_drawing, path, options=options(g), settings=settings())
        return Made(g, d, run, run.orchestrated, fresh, path)
    if g.kind == "regenerated":
        return _o07(g)
    if g.kind == "synthetic":
        xt, truth = getattr(drawing_parts, g.part)()
        run, stage = _synthetic(g.part, xt, truth, g)
        fresh = lambda: _synthetic(g.part, xt, truth, g)[0].drawing  # noqa: E731
        return Made(g, run.drawing, run, run.orchestrated, fresh, stage())
    (xa, ta), (xb, tb) = getattr(drawing_parts, g.part)()
    before, _stage = _synthetic(g.part, xa, ta, g)
    after_source = source_stage(g.part, xb, tb)()
    merged, report = drawing.regenerate(before.drawing, after_source)
    after, _s = _synthetic(g.part, xb, tb, g)
    fresh = lambda: _synthetic(g.part, xb, tb, g)[0].drawing  # noqa: E731
    return Made(g, merged, after, after.orchestrated, fresh, after_source, False, report)


def check_lines(checks, levels=("error", "warning", "information")) -> list[str]:
    """A drawing's checks in words, one a line: level, code, item and message."""
    return [_unversioned(f"{c.level} {c.code} {c.item}: {c.message}") for c in checks if c.level in levels]


def hard_conflicts(checks) -> list[str]:
    """The hard layout conflicts among a drawing's checks (see :data:`HARD_SHEET_WORDS`)."""
    return [
        f"{c.code} {c.item}: {c.message}"
        for c in checks
        if c.code == "R11.collisions" or (c.code == "R8.sheet" and c.message.endswith(HARD_SHEET_WORDS))
    ]


# --------------------------------------------------------------------------- what the drawing shows


def _frame_text(item: D.FrameItem) -> str:
    zone = ("Ø" if item.diameter else "") + item.zone + (f" {item.modifier.upper()}" if item.modifier else "")
    return " | ".join([item.characteristic, zone, *item.datums])


def _text_of(t: D.DimText) -> str:
    value = f"[{t.value}]" if t.boxed else t.value
    out = t.prefix + value
    if t.after:
        out += " " + t.after.strip()
    if t.upper or t.lower:
        out += f" {t.upper}/{t.lower}"
    return out.strip()


def shown_set(d, *, ids: bool = False) -> list[dict]:
    """The drawing's dimensions as its sheet shows them: requirement key, kind, the value
    as shown (prefix, value, what follows it, a basic value in brackets), the tolerance
    kind, the callout's further lines, the frame, a datum symbol's letter and the axis of
    its face; with ``ids``, the dimension id and whether the user moved it."""
    sheet = d.sheet
    texts = {a.id: a.text for a in sheet.annotations if isinstance(a, D.Dimension)}
    frames = {
        a.owner[: -len("-frame")]: a.frame
        for a in sheet.annotations
        if isinstance(a, D.FeatureControlFrame) and a.owner.endswith("-frame")
    }
    letters = Counter(a.letter for a in sheet.annotations if isinstance(a, D.DatumFeature))
    out = []
    for dim in d.dimensions:
        e: dict[str, Any] = {}
        if ids:
            e["id"] = dim.id
        e["key"] = dim.key
        e["kind"] = dim.kind
        if dim.kind == "datum_feature":
            letter = dim.suffix[0] if dim.suffix else ""
            e["value"] = letter if letters.get(letter) else None
            e["axis"] = dim.axis
        else:
            t = texts.get(dim.id)
            e["value"] = None if t is None else _text_of(t)
            e["tolerance"] = dim.tolerance
            if t is not None and t.suffix:
                e["lines"] = list(t.suffix)
            if dim.id in frames:
                e["frame"] = _frame_text(frames[dim.id])
        if dim.state != "shown":
            e["state"] = dim.state
        placement = getattr(dim, "placement", None)
        if ids and placement is not None and placement.moved:
            e["moved"] = True
        out.append(e)
    return out


def sheet_facts(sheet: D.Sheet) -> list[str]:
    """What the sheet shows in words: every text run, and one line for each projection
    symbol, centre mark, datum symbol and stamp."""
    out = [p.text for p in sheet.painted if isinstance(p, D.TextRun)]
    for a in sheet.annotations:
        if isinstance(a, D.ProjectionSymbol):
            out.append(f"projection symbol: {a.angle} angle")
        elif isinstance(a, D.CentreMark):
            out.append("centre mark")
        elif isinstance(a, D.DatumFeature):
            out.append(f"datum symbol {a.letter}")
        elif isinstance(a, D.Stamp):
            out.append(f"stamp: {a.text}")
    return [_unversioned(t) for t in out]


def view_counts(views) -> dict[str, int]:
    """How many orthographic views and isometrics a plan keeps."""
    kinds = Counter(v.kind for v in views)
    return {"orthographic": kinds["base"] + kinds["projected"], "isometric": kinds["isometric"]}


# --------------------------------------------------------------------------- the snapshots


def _unversioned(text: str) -> str:
    return text.replace(__version__, VERSION_TOKEN)


def _mm(v: float) -> float:
    return round(v * 1000.0, 4)


def _frame_cell(f) -> str | None:
    if f is None:
        return None
    zone = ("Ø" if f.diameter else "") + f"{_mm(f.value)}mm" + (f" {f.modifier}" if f.modifier else "")
    return " | ".join([f.characteristic, zone, *f.datums])


def plan_summary(m: Made) -> dict:
    """The drawing's records in short: views, one line a dimension, datums, notes, title
    fields, options and the drawing's checks; the planner's graph verdicts for the part
    as drawn; for a regeneration the merge report."""
    d = m.drawing
    dims = []
    for x in d.dimensions:
        rec = {
            "id": x.id,
            "key": x.key,
            "kind": x.kind,
            "view": x.view,
            "axis": x.axis,
            "mm": _mm(x.value) if x.kind != "angle" else round(x.value, 9),
            "tol": x.tolerance,
            "places": x.places,
            "prefix": x.prefix,
            "suffix": list(x.suffix),
            "role": x.role,
        }
        if x.frame is not None:
            rec["frame"] = _frame_cell(x.frame)
        if x.state != "shown":
            rec["state"] = x.state
        if getattr(x, "flags", ()):
            rec["flags"] = list(x.flags)
        dims.append(rec)
    plan = m.orchestrated.planned.plan
    out = {
        "options": doc.member_values(d)["options"],
        "sheet": f"{d.sheet.name} {d.sheet.scale[0]}:{d.sheet.scale[1]}",
        "views": [f"{v.view} at {v.scale:g}" for v in d.sheet.views],
        "dimensions": dims,
        "datums": [f"{x.letter} face {x.face}: {x.reason}" for x in d.datums],
        "notes": [n.text for _i, n in d.notes],
        "title": {k: _unversioned(f.text) for k, f in d.title},
        "coverage": [
            d.coverage.features,
            d.coverage.features_unclaimed,
            d.coverage.faces,
            d.coverage.faces_claimed,
        ],
        "graphs": [
            f"{g.graph}: {'complete' if g.complete else 'incomplete'}, "
            f"{'redundant' if g.redundant else 'a tree'}"
            + (f", missing {', '.join(g.missing)}" if g.missing else "")
            for g in plan.graphs
        ],
        "bands": [f"{text} x{n}" for text, n in plan.bands],
        "checks": check_lines(d.checks),
    }
    if m.report is not None:
        out["merge"] = {
            "words": m.report.words(),
            "resized": list(m.report.features_resized),
            "gone": list(m.report.features_gone),
            "new": list(m.report.features_new),
            "items": [_unversioned(i) for i in m.report.items],
        }
    return out


def _digest(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def svg_summary(text: str) -> dict:
    """The SVG's numbers layer by layer (each ``<g id="layer-...">``, and ``page`` for
    what lies outside them): how many, their sum, and a digest of them rounded to a
    hundredth of a millimetre (12.4)."""
    out: dict[str, dict] = {}
    current = "page"
    for line in text.splitlines():
        m = re.match(r'<g id="layer-([^"]+)">', line)
        if m:
            current = m.group(1)
            continue
        if line.startswith("</g>"):
            current = "page"
            continue
        nums = svg.numbers(line)
        if not nums:
            continue
        slot = out.setdefault(current, {"n": 0, "sum": 0.0, "_parts": []})
        slot["n"] += len(nums)
        slot["sum"] += sum(nums)
        slot["_parts"].append(" ".join(f"{v:.2f}" for v in nums))
    return {
        k: {"n": v["n"], "sum": round(v["sum"], 2), "digest": _digest("\n".join(v["_parts"]))}
        for k, v in sorted(out.items())
    }


def pdf_summary(data: bytes) -> dict:
    """The PDF's inflated content (12.4): a digest of it, its operators counted, the
    optional content groups and the text it shows, in order."""
    pdf = pdf_reader.PdfDocument(data)
    content = pdf.content().replace(__version__.encode("ascii"), VERSION_TOKEN.encode("ascii"))
    ops = Counter(op for op, _args in pdf.operations())
    return {
        "content": _digest(content),
        "operators": dict(sorted(ops.items())),
        "groups": pdf.ocg_names(),
        "text": [_unversioned(r.text) for r in pdf.text_runs()],
    }


def dxf_summary(data: bytes) -> dict:
    """The DXF's tags (12.4): a digest of them, and its entities counted by type and
    layer, in model space and in the blocks."""
    text = data.decode("ascii").replace(__version__, VERSION_TOKEN)
    doc_ = dxf_reader.read(text.encode("ascii"))
    entities = Counter(f"{e.type} {e.layer}" for e in doc_.entities)
    blocks = Counter(f"{e.type} {e.layer}" for b in doc_.blocks.values() for e in b.entities)
    return {
        "tags": _digest(text),
        "count": doc_.tag_count,
        "entities": dict(sorted(entities.items())),
        "blocks": dict(sorted(blocks.items())),
    }


def outputs(d) -> dict[str, bytes]:
    """The drawing written every way: the ``.ssdrw``, the SVG, the PDF and the DXF."""
    return {
        "ssdrw": doc.dumps(d),
        "svg": svg.to_svg(d.sheet).encode("utf-8"),
        "pdf": to_pdf(d).data,
        "dxf": dxf_bytes(d),
    }


def snapshot(m: Made) -> dict:
    files = outputs(m.drawing)
    return {
        "plan": plan_summary(m),
        "svg": svg_summary(files["svg"].decode("utf-8")),
        "pdf": pdf_summary(files["pdf"]),
        "dxf": dxf_summary(files["dxf"]),
    }


# --------------------------------------------------------------------------- the files


def golden_path(name: str) -> str:
    return os.path.join(GOLDENS_DIR, f"{name}.json")


def read_golden(name: str) -> dict:
    with open(golden_path(name), encoding="utf-8") as fh:
        return json.load(fh)


def _flat(value: Any) -> bool:
    if isinstance(value, dict):
        return all(
            not isinstance(v, (dict, list)) or (isinstance(v, list) and len(v) <= 8) for v in value.values()
        )
    return not isinstance(value, list)


def _dump(value: Any, indent: int = 0) -> str:
    """JSON with one member a line and one record a line: what a golden file looks like,
    so a refreshed snapshot reads as a short diff."""
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, dict) and value and not (indent >= 3 and _flat(value)):
        items = [
            f"{pad}{json.dumps(k, ensure_ascii=False)}: {_dump(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(value, list) and value and not all(isinstance(v, (int, float, bool)) for v in value):
        if all(_flat(v) for v in value):
            items = [pad + json.dumps(v, ensure_ascii=False) for v in value]
        else:
            items = [pad + _dump(v, indent + 1) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(value, ensure_ascii=False)


def golden_text(data: dict) -> str:
    return _dump(data) + "\n"


def write_golden(name: str, snap: dict) -> None:
    """Replace a golden file's ``snapshot`` and nothing else: the hand-written members are
    read and written back as they are."""
    data = read_golden(name)
    data["snapshot"] = snap
    with open(golden_path(name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(golden_text(data))


__all__ = [
    "BY_NAME",
    "GOLDENS",
    "HARD_LAYOUT",
    "HARD_SHEET_WORDS",
    "REFRESH_VARIABLE",
    "Golden",
    "Made",
    "check_lines",
    "golden_path",
    "hard_conflicts",
    "golden_text",
    "made",
    "options",
    "outputs",
    "read_golden",
    "settings",
    "sheet_facts",
    "shown_set",
    "snapshot",
    "source_stage",
    "view_counts",
    "write_golden",
]
