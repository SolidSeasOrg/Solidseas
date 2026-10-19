"""The golden drawings (``docs/DRAWINGS.md`` 19.4) and the checks every golden must
pass (19.5). ``docs/drawings/goldens.md`` lists the goldens, what each proves and
the open findings.

Each golden is a file under ``tests/goldens/drawings/`` with three members:

- ``expected``, written by hand from the rules and reviewed once by the user: the
  dimension set (requirement key, kind, the value as the sheet shows it in the
  drawing's unit, the tolerance kind, a callout's further lines and its frame), and
  for some goldens the views, what the sheet must and must not say, and what a
  regeneration matched. The tests compare it in full. Nothing ever rewrites it.
- ``findings``, written by hand: where a golden shows the drawing is wrong by the
  rules, the finding in words and the exact problems the check reports. That check
  is marked ``xfail(strict=True)``: it fails as long as the problems are exactly
  these, fails outright when they change, and passes (so fails as strict) once the
  drawing is right, when the finding is taken out.
- ``snapshot``, recorded: the plan in short, the SVG's numbers by layer, the PDF's
  content and text, and the DXF's tags.

Refreshing the snapshots: run this module with ``SOLIDSEAS_REFRESH_GOLDENS=1`` set,
for example ``SOLIDSEAS_REFRESH_GOLDENS=1 python -m pytest -q
tests/test_drawing_golden.py -k snapshot``. Each snapshot test then writes its
golden's ``snapshot`` member and passes; the hand-written members are written
back unchanged. Review the diff before committing it.

The 19.5 checks, one test each per golden: (1) every requirement covered by one
shown dimension and no key twice; (2) every graph complete and acyclic; (3) the
reconstruction oracle (``tests/drawing_reconstruct.py``) finds nothing missing,
redundant or wrong; (4) no hard layout conflict; (5) no error among the drawing's
checks (``checks.run_checks``) but those the golden's ``expected.errors`` says the
rules give it, which runs when ``pipeline.available()["checks"]`` and skips with
that reason otherwise; (6) writing twice gives the same bytes, and regenerating
against an unchanged model changes nothing. Checks 1 to 3 read the plan stage's run
the pipeline keeps (``Run.orchestrated``); checks 4 and 5 the drawing's own checks.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

import drawing_golden_support as G
from drawing_reconstruct import reconstruct
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import pipeline, release
from solidseas.drawing.source import DrawingSource, open_source

NAMES = [g.name for g in G.GOLDENS]
REFRESH = os.environ.get(G.REFRESH_VARIABLE, "") not in ("", "0")
CHECKS = (
    "dimensions",
    "views",
    "sheet",
    "merge",
    "requirements",
    "graphs",
    "oracle",
    "layout",
    "automated",
    "repeatable",
)


@pytest.fixture(scope="module", autouse=True)
def golden_folder(tmp_path_factory):
    """Where o07's golden saves o02's drawing before loading it."""
    G.FOLDER = str(tmp_path_factory.mktemp("goldens"))
    yield G.FOLDER


class GoldenFinding(AssertionError):
    """A check failed with exactly the problems its golden's finding records."""


def _findings(name: str) -> dict:
    try:
        return G.read_golden(name).get("findings", {})
    except FileNotFoundError:
        return {}


def params(check: str, names=NAMES):
    """The goldens as test parameters, a golden whose ``findings`` name ``check`` marked
    ``xfail(strict=True)`` with the finding."""
    out = []
    for name in names:
        found = _findings(name).get(check)
        marks = ()
        if found:
            marks = (pytest.mark.xfail(strict=True, raises=GoldenFinding, reason=found["finding"]),)
        out.append(pytest.param(name, marks=marks, id=name))
    return out


def verdict(name: str, check: str, problems: list[str]) -> None:
    """Pass when there is no problem and no finding; fail as the finding (the xfail) when
    the problems are exactly the finding's; fail outright otherwise."""
    found = _findings(name).get(check)
    if found is None:
        assert not problems, f"{name}: {check}:\n  " + "\n  ".join(problems)
        return
    if problems == found["problems"]:
        raise GoldenFinding(f"{name}: {found['finding']}")
    assert problems, f"{name}: the {check} finding is fixed; take it out of the golden's findings"
    raise AssertionError(
        f"{name}: {check}: the problems are no longer the recorded finding's:\n  "
        + "\n  ".join(problems)
        + "\nrecorded:\n  "
        + "\n  ".join(found["problems"])
    )


def expected(name: str) -> dict:
    return G.read_golden(name)["expected"]


# --------------------------------------------------------------------------- the hand-written sets


def _line(e: dict) -> str:
    return json.dumps(e, ensure_ascii=False, sort_keys=True)


def compare_sets(want: list[dict], got: list[dict]) -> list[str]:
    """Every difference between two dimension sets, by requirement key (and id when the
    set gives ids), in words."""
    problems = []

    def ident(e):
        return (e.get("id", ""), e["key"])

    want_by = {}
    for e in want:
        want_by.setdefault(ident(e), []).append(e)
    got_by = {}
    for e in got:
        got_by.setdefault(ident(e), []).append(e)
    for k in sorted(set(want_by) | set(got_by)):
        w, g = want_by.get(k, []), got_by.get(k, [])
        label = " ".join(x for x in k if x)
        if len(g) > 1:
            problems.append(f"{label}: shown {len(g)} times")
        if not g:
            problems.append(f"missing {label}: {_line(w[0])}")
        elif not w:
            problems.append(f"extra {label}: {_line(g[0])}")
        elif _line(w[0]) != _line(g[0]):
            diff = sorted(f for f in set(w[0]) | set(g[0]) if w[0].get(f) != g[0].get(f))
            problems.append(
                f"{label}: "
                + ", ".join(f"{f} {g[0].get(f)!r} where the rules give {w[0].get(f)!r}" for f in diff)
            )
    return problems


@pytest.mark.parametrize("name", params("dimensions"))
def test_the_dimension_set_is_the_one_the_rules_give(name):
    m = G.made(name)
    ids = m.golden.kind in ("regenerated", "pair")
    verdict(name, "dimensions", compare_sets(expected(name)["dimensions"], G.shown_set(m.drawing, ids=ids)))


def _with(member: str):
    out = []
    for n in NAMES:
        try:
            if member in expected(n):
                out.append(n)
        except FileNotFoundError:
            continue
    return out


@pytest.mark.parametrize("name", params("views", _with("views")))
def test_the_views_are_the_fewest_that_define_the_part(name):
    m = G.made(name)
    got = G.view_counts(m.orchestrated.planned.plan.views)
    want = expected(name)["views"]
    verdict(
        name,
        "views",
        [f"{k}: {got.get(k)} views where the rules give {v}" for k, v in want.items() if got.get(k) != v],
    )


def sheet_problems(want: list, facts: list[str]) -> list[str]:
    text = " ".join(facts)
    problems = []
    for item in want:
        if isinstance(item, str):
            if item not in text:
                problems.append(f"the sheet does not say {item!r}")
        elif "absent" in item:
            if item["absent"] in text:
                problems.append(f"the sheet says {item['absent']!r}, which it must not")
        else:
            n = sum(1 for f in facts if f == item["of"])
            if n != item["count"]:
                problems.append(
                    f"the sheet shows {item['of']!r} {n} times where the rules give {item['count']}"
                )
    return problems


@pytest.mark.parametrize("name", params("sheet", _with("sheet")))
def test_the_sheet_says_what_the_rules_ask(name):
    m = G.made(name)
    verdict(name, "sheet", sheet_problems(expected(name)["sheet"], G.sheet_facts(m.drawing.sheet)))


@pytest.mark.parametrize("name", params("merge", _with("merge")))
def test_a_regeneration_matches_the_features_it_should(name):
    m = G.made(name)
    r = m.report
    got = {
        "resized": sorted(r.features_resized),
        "gone": sorted(r.features_gone),
        "new": sorted(r.features_new),
    }
    want = expected(name)["merge"]
    verdict(
        name,
        "merge",
        [f"{k}: {got[k]} where the rules give {want[k]}" for k in want if got[k] != sorted(want[k])],
    )


# --------------------------------------------------------------------------- 19.5


@pytest.mark.parametrize("name", params("requirements"))
def test_every_requirement_is_covered_once_and_no_key_twice(name):
    """19.5 check 1, on the plan of the part as drawn (the plan stage's run the pipeline
    keeps): each need and each location the graphs ask for is served by exactly one
    shown dimension, and no key is shown twice."""
    m = G.made(name)
    detail = m.orchestrated.planned.detail
    plan = m.orchestrated.planned.plan
    shown = [d for d in plan.dimensions if d.state == "shown"]
    required = [n.req.key for n in detail.req.needs]
    for g in detail.graphs.values():
        for node in g.nodes:
            if node != g.origin:
                required += list(g.keys(node))
    problems = []
    for key in dict.fromkeys(required):
        n = sum(1 for d in shown if key in d.serves)
        if n != 1:
            problems.append(f"{key} is served by {n} dimensions")
    keys = [d.key for d in shown]
    problems += [f"{k} is shown {keys.count(k)} times" for k in dict.fromkeys(keys) if keys.count(k) > 1]
    problems += [f"{k} has no view to draw it" for k in dict.fromkeys(detail.uncovered)]
    verdict(name, "requirements", problems)


@pytest.mark.parametrize("name", params("graphs"))
def test_every_graph_is_complete_and_acyclic(name):
    """19.5 check 2."""
    m = G.made(name)
    problems = []
    for g in m.orchestrated.planned.plan.graphs:
        if not g.complete:
            problems.append(f"{g.graph} is incomplete: {', '.join(g.missing)}")
        if g.redundant:
            problems.append(f"{g.graph} has a loop: {'; '.join(', '.join(loop) for loop in g.loops)}")
    verdict(name, "graphs", problems)


@pytest.mark.parametrize("name", params("oracle"))
def test_the_reconstruction_oracle_finds_nothing_missing_redundant_or_wrong(name):
    """19.5 check 3, on the dimensions the drawing shows and the feature set they name.
    The planner gives the oracle no centre lines of its own (``Plan`` has none yet):
    holes in line are joined by one position naming them all."""
    m = G.made(name)
    run = m.run
    planned = m.orchestrated.planned
    shown = [d for d in planned.plan.dimensions if d.state == "shown"]
    fillet = planned.detail.req.fillet_radius  # the fillet note's radius (rule 14)
    report = reconstruct(run.model, run.features.frame, shown, features=run.features, fillet_radius=fillet)
    verdict(name, "oracle", [str(f) for f in report.findings])


@pytest.mark.parametrize("name", params("layout"))
def test_there_is_no_hard_layout_conflict(name):
    """19.5 check 4, on the drawing's own sheet as its checks report it: no text over
    text and nothing layout could not place clear (R11.collisions), nothing outside the
    border or in a reserved block (the layout's words under R8.sheet)."""
    m = G.made(name)
    verdict(name, "layout", G.hard_conflicts(m.drawing.checks))


# The title fields a golden is made without: no person signs DRAWN and no material or
# finish is typed, so the checklist is right to call those cells empty (R6.title).
NOT_GIVEN = ("R6.title DRAWN", "R6.title material", "R6.title finish")


@pytest.mark.parametrize("name", params("automated"))
def test_every_automated_check_passes_apart_from_accepted_blockers(name):
    """19.5 check 5: no error-level check among the drawing's checks (``checks.run_checks``
    on the live run, which the pipeline and regeneration attach to every drawing), but
    the empty title cells of :data:`NOT_GIVEN` and those the golden's
    ``expected.errors`` says the rules give it (o07's removed width); a reduced-dimension
    golden is blocked from release by its unclaimed geometry until that is accepted with
    a typed reason (``COV.unclaimed``, 10.10), and not once it is."""
    have = pipeline.available()
    if not have["checks"]:
        pytest.skip('pipeline.available()["checks"] is false: drawing.checks is not built yet')
    m = G.made(name)
    rightly = expected(name).get("errors", [])
    errors = G.check_lines([c for c in m.drawing.checks if f"{c.code} {c.item}" not in NOT_GIVEN], ("error",))
    problems = [e for e in errors if e not in rightly]
    problems += [
        f"the rules give the error {e!r}, which the drawing does not have" for e in rightly if e not in errors
    ]
    if m.drawing.coverage.features_unclaimed:
        run_checks = pipeline.resolve("checks", pipeline.ENTRY_POINTS["checks"])
        o = m.orchestrated
        at_release = run_checks(m.drawing, planned=o.planned, layout=o.result, release=True)
        blockers = [p for p in release.release_problems(m.drawing, checks=at_release) if "COV.unclaimed" in p]
        if not blockers:
            problems.append("a reduced-dimension drawing is not blocked from release by COV.unclaimed")
        accepted = {"COV.unclaimed": "the inclined hole is defined by the model"}
        left = release.release_problems(m.drawing, accepted, checks=at_release)
        if any("COV.unclaimed" in p for p in left):
            problems.append("COV.unclaimed still blocks release once it is accepted with a reason")
    verdict(name, "automated", problems)


MERGE_FLAGS = ("new", "changed", "needs_attention", "placement_reset")  # set afresh by every merge


def _settled(d) -> list:
    """A drawing's dimensions without the flags a merge sets afresh each time."""
    return [replace(x, flags=tuple(f for f in x.flags if f not in MERGE_FLAGS)) for x in d.dimensions]


def _drawn(sheet) -> tuple:
    """What a sheet draws of the part and its dimensions: views, geometry and the
    dimensions, datum symbols, frames and centre marks (not the title block, whose
    MODEL field shows the model's hash)."""
    kinds = (D.Dimension, D.DatumFeature, D.FeatureControlFrame, D.CentreMark, D.CentreLine)
    return (sheet.views, sheet.geometry, tuple(a for a in sheet.annotations if isinstance(a, kinds)))


def regeneration_problems(d, again) -> list[str]:
    problems = []
    old = {x.id: x for x in _settled(d)}
    new = {x.id: x for x in _settled(again)}
    for ident in sorted(set(old) | set(new), key=lambda i: int(i.split("-")[1])):
        a, b = old.get(ident), new.get(ident)
        if a is None or b is None:
            problems.append(f"{ident} {'appeared' if a is None else 'went'}")
            continue
        for f in ("key", "kind", "view", "value", "state", "tolerance", "prefix", "suffix", "placement"):
            if getattr(a, f) != getattr(b, f):
                problems.append(f"{ident} {a.key}: its {f} {getattr(a, f)!r} became {getattr(b, f)!r}")
    views = [v.view for v in d.sheet.views], [v.view for v in again.sheet.views]
    if views[0] != views[1]:
        problems.append(f"the views {', '.join(views[0])} became {', '.join(views[1])}")
    elif _drawn(d.sheet) != _drawn(again.sheet):
        problems.append("the sheet draws the part or its dimensions differently")
    return problems


@pytest.mark.parametrize("name", params("repeatable"))
def test_writing_twice_gives_the_same_bytes_and_an_unchanged_model_changes_nothing(name):
    """19.5 check 6: the ``.ssdrw``, SVG, PDF and DXF of one drawing written twice are the
    same bytes, and a fresh run on the same model writes the same SVG, PDF and DXF.
    Regenerating against the unchanged model changes nothing: as the hashes say so, and
    when the pipeline runs again (the model's hashes made to differ so regeneration
    runs the frozen options and merges) the dimensions, views and what the sheet
    draws stay as they were."""
    m = G.made(name)
    d = m.drawing
    problems = []
    first, second = G.outputs(d), G.outputs(d)
    problems += [f"the {k} written twice differs" for k in first if first[k] != second[k]]
    if m.same:
        again = G.outputs(m.fresh())
        problems += [f"a fresh run writes another {k}" for k in ("svg", "pdf", "dxf") if again[k] != first[k]]
    same, report = drawing.regenerate(d, m.source)
    if not (report.model_unchanged or report.geometry_unchanged):
        problems.append(f"regenerating against the same model says {report.words()!r}")
    if same.dimensions != d.dimensions or same.sheet != d.sheet:
        problems.append("regenerating against the same model changed the drawing")
    if isinstance(m.source, DrawingSource):
        src = m.source
    else:
        units = d.options.units if d.options.units in ("in", "mm") else None
        src = open_source(m.source, units=units)
    src = replace(src, sha256=None if src.sha256 is None else "f" * 64, geometry_digest="e" * 64)
    again, report = drawing.regenerate(d, src)
    if report.changed or report.new or report.dropped or report.attention:
        problems.append(f"regenerating past the hash shortcuts says {report.words()!r}")
    problems += regeneration_problems(d, again)
    verdict(name, "repeatable", problems)


# --------------------------------------------------------------------------- the snapshots


def _differences(want, got, path="") -> list[str]:
    if isinstance(want, dict) and isinstance(got, dict):
        out = []
        for k in sorted(set(want) | set(got), key=str):
            if k not in got:
                out.append(f"{path}{k}: gone")
            elif k not in want:
                out.append(f"{path}{k}: new, {json.dumps(got[k], ensure_ascii=False)[:200]}")
            else:
                out += _differences(want[k], got[k], f"{path}{k}.")
        return out
    if isinstance(want, list) and isinstance(got, list) and len(want) == len(got):
        out = []
        for i, (a, b) in enumerate(zip(want, got, strict=True)):
            out += _differences(a, b, f"{path}{i}.")
        return out
    if want != got:
        a = json.dumps(want, ensure_ascii=False)[:200]
        b = json.dumps(got, ensure_ascii=False)[:200]
        return [f"{path.rstrip('.')}: recorded {a}, now {b}"]
    return []


@pytest.mark.parametrize("name", NAMES)
def test_the_snapshot_is_the_one_recorded(name):
    """The plan, SVG numbers, PDF content and DXF tags as recorded (12.4). With
    ``SOLIDSEAS_REFRESH_GOLDENS=1`` the snapshot is written instead."""
    m = G.made(name)
    snap = G.snapshot(m)
    if REFRESH:
        G.write_golden(name, snap)
        return
    recorded = G.read_golden(name).get("snapshot") or {}
    problems = _differences(recorded, snap)
    assert not problems, (
        f"{name}: the snapshot changed (refresh with {G.REFRESH_VARIABLE}=1 once the change is meant):\n  "
        + "\n  ".join(problems[:40])
    )


def test_every_golden_has_its_file_and_the_files_are_canonical():
    """Each golden has a file, every file is a golden, the hand-written members are there,
    and the file is written as the refresh writes it, so a refresh changes only the
    snapshot."""
    on_disk = sorted(f[: -len(".json")] for f in os.listdir(G.GOLDENS_DIR) if f.endswith(".json"))
    assert on_disk == sorted(NAMES)
    for name in NAMES:
        with open(G.golden_path(name), encoding="utf-8") as fh:
            text = fh.read()
        data = json.loads(text)
        assert data["golden"] == name
        assert set(data) == {"golden", "part", "profile", "proves", "expected", "findings", "snapshot"}
        assert data["expected"]["dimensions"], name
        assert set(data["findings"]) <= set(CHECKS), name
        for check, found in data["findings"].items():
            assert found["finding"] and found["problems"], (name, check)
        assert text == G.golden_text(data), f"{name}.json is not written as a refresh writes it"
