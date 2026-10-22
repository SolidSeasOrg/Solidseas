"""The drawings cross-check (``docs/DRAWINGS.md`` section 25): SolidSeas' views against
Open CASCADE's two hidden-line algorithms, as a three-way vote, and its planned
dimensions against Open CASCADE's lines (``drawing_occt``).

The vote and the dimension check are plain Python and tested here with drawn line
sets. The tests that run Open CASCADE are marked ``occt`` and skip unless
``SOLIDSEAS_OCCT_PYTHON`` names an interpreter where ``import OCP`` works, as the OCCT
oracle's do (``tests/README.md``); Open CASCADE runs only in ``occt_hlr_child.py``,
never in this process, and ``solidseas.drawing`` never imports it.
"""

import ast
import dataclasses
import math
import sys
from pathlib import Path

import pytest

import drawing_occt as C
import occt_support as O
from solidseas.drawing import types as T
from support import fixture_path

SRC = Path(__file__).resolve().parent.parent / "src"
SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
NOTHING = {"visible": [], "hidden": []}


def _sets(ours=None, exact=None, poly=None) -> dict:
    full = {"visible": [SQUARE], "hidden": []}
    return {"ours": ours or full, "exact": exact or full, "poly": poly or full}


def _odd(result, name, kind="visible") -> float:
    return result[kind]["odd"][name]["missed"] + result[kind]["odd"][name]["alone"]


# --------------------------------------------------------------------------- the vote, without OCCT
def test_three_sets_that_draw_the_same_lines_agree():
    r = C.vote(_sets(), 0.01)
    assert r["visible"]["length"] == pytest.approx(40.0) and r["visible"]["agreed"] == pytest.approx(40.0)
    assert C.odd_one_out(r) is None and all(v == 1.0 for v in r["visible"]["covered"].values())
    assert r["hidden"]["length"] == 0.0 and C.odd_one_out(r, "hidden") is None


def test_the_vote_names_the_set_that_misses_a_line_or_draws_one_alone():
    three_sides = {"visible": [SQUARE[:4]], "hidden": []}
    r = C.vote(_sets(ours=three_sides), 0.01)
    # the side ours leaves out, but for its ends, which lie within 0.01 of the other sides
    assert C.odd_one_out(r) == "ours"
    assert r["visible"]["odd"]["ours"]["missed"] == pytest.approx(10.0, abs=0.02)
    # ours' precision against exact is whole, its recall three quarters
    assert r["visible"]["covered"]["ours_exact"] == 1.0
    assert r["visible"]["covered"]["exact_ours"] == pytest.approx(0.75, abs=0.001)
    with_diagonal = {"visible": [SQUARE, [(0.0, 0.0), (10.0, 10.0)]], "hidden": []}
    r = C.vote(_sets(exact=with_diagonal), 0.01)
    assert C.odd_one_out(r) == "exact"
    assert r["visible"]["odd"]["exact"]["alone"] == pytest.approx(math.sqrt(200), abs=0.03)
    assert _odd(r, "ours") == _odd(r, "poly") == 0.0
    # within the tolerance a line is the same line; past it, another
    shifted = {"visible": [[(x + 0.004, y) for x, y in SQUARE]], "hidden": []}
    assert C.odd_one_out(C.vote(_sets(poly=shifted), 0.01)) is None
    assert C.odd_one_out(C.vote(_sets(poly=shifted), 0.001)) == "poly"


def test_a_hidden_line_on_a_visible_line_is_never_drawn():
    """Open CASCADE gives a box's back edges as hidden lines where they lie behind its
    front edges; a drawing never draws them, so the vote leaves them out of every set."""
    behind = {"visible": [SQUARE], "hidden": [SQUARE]}
    r = C.vote(_sets(exact=behind, poly=behind), 0.01)
    assert r["hidden"]["length"] == 0.0 and C.odd_one_out(r, "hidden") is None
    # a hidden line of its own, a hole's side, must be drawn by each
    hole = [(4.0, 0.0), (4.0, 10.0)]
    seen = {"visible": [SQUARE], "hidden": [SQUARE, hole]}
    r = C.vote(_sets(exact=seen, poly=seen), 0.01)
    assert C.odd_one_out(r, "hidden") == "ours"
    assert r["hidden"]["odd"]["ours"]["missed"] == pytest.approx(10.0, abs=0.02)
    # and a line one set draws visible where the others draw it hidden is at odd in both kinds
    shown = {"visible": [SQUARE, hole], "hidden": []}
    r = C.vote(_sets(ours=shown, exact=seen, poly=seen), 0.01)
    assert C.odd_one_out(r) == "ours" and C.odd_one_out(r, "hidden") == "ours"


def test_a_smooth_edge_agrees_with_a_line_but_need_not_be_drawn():
    """A drawing shows tangent edges by a setting of its own: a line Open CASCADE gives
    as a smooth edge agrees with a drawn one, and leaving it out is no miss."""
    seam = [(5.0, 0.0), (5.0, 10.0)]
    smooth = {"visible": [SQUARE], "hidden": [], "smooth_visible": [seam]}
    r = C.vote(_sets(exact=smooth, poly=smooth), 0.01)
    assert C.odd_one_out(r) is None
    drawn = {"visible": [SQUARE, seam], "hidden": []}
    r = C.vote(_sets(ours=drawn, exact=smooth, poly=smooth), 0.01)
    assert C.odd_one_out(r) is None and r["visible"]["odd"]["ours"]["alone"] == 0.0


def test_dimensions_are_checked_against_the_lines_open_cascade_draws():
    front = T.ViewSpec("v-1", "base", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), "front")
    mm = C.MM

    def linear(did, axis, *positions):
        return T.PlannedDimension(did, did, "linear", "v-1", 0.0, axis=axis, positions=positions)

    def diameter(did, radius_mm):
        anchor = (5 * mm, 5 * mm, 0.0)
        return T.PlannedDimension(
            did, did, "diameter", "v-1", 2 * radius_mm * mm, anchor=anchor, radius=radius_mm * mm
        )

    circle = [
        (5.0 + 2.0 * math.cos(math.radians(a)), 5.0 + 2.0 * math.sin(math.radians(a)))
        for a in range(0, 361, 5)
    ]
    plan = T.Plan(
        views=(front,),
        dimensions=(
            linear("width", "x", T.Position(0.0), T.Position(10 * mm)),
            linear("height", "y", T.Position(0.0), T.Position(10 * mm)),
            linear("hole", "x", T.Position(0.0), T.Position(5 * mm, centre=True, radius=2 * mm)),
            linear("past", "x", T.Position(0.0), T.Position(15 * mm)),
            linear("deep", "z", T.Position(0.0), T.Position(5 * mm)),  # along the view: not checked here
            diameter("dia", 2.0),
            diameter("off", 3.0),
        ),
    )
    lines = {"v-1": {"exact": {"visible": [SQUARE, circle], "hidden": []}, "poly": NOTHING}}
    got = {d["id"]: d for d in C.dimension_witnesses(plan, lines, 0.01)}
    assert [got[k]["ok"] for k in ("width", "height", "hole", "dia")] == [True] * 4
    assert got["past"]["ok"] is False and got["past"]["missing"] == [15.0]
    assert got["off"]["ok"] is False and got["off"]["missing"] == [6.0]
    assert got["deep"]["checked"] is False
    # a round feature's centre is witnessed by both its sides, not one
    left_only = {"v-1": {"exact": {"visible": [SQUARE, [(3.0, 0.0), (3.0, 10.0)]], "hidden": []}}}
    hole = {d["id"]: d for d in C.dimension_witnesses(plan, left_only, 0.01)}["hole"]
    assert hole["ok"] is False and hole["missing"] == [7.0]


def _imported(path: Path) -> set[str]:
    """The top-level modules a Python file imports."""
    tops = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            tops.add(node.module.split(".")[0])
    return tops


def test_open_cascade_never_reaches_the_drawing_code():
    """The cross-check is a test harness: no module under src imports it or its child,
    nothing in solidseas.drawing imports OCP, and the child imports the standard
    library and OCP alone."""
    for path in SRC.rglob("*.py"):
        assert not _imported(path) & {"drawing_occt", "occt_hlr_child"}, path
    for path in (SRC / "solidseas" / "drawing").rglob("*.py"):
        assert "OCP" not in _imported(path), path
    assert _imported(Path(C.CHILD)) - {"OCP"} <= set(sys.stdlib_module_names)


# --------------------------------------------------------------------------- with Open CASCADE
FIXTURE_PARTS = ("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT", "o10_import_step_cut.SLDPRT", "o11_curved.SLDPRT",
                 "o12_multibody.SLDPRT")  # fmt: skip
# Where Open CASCADE's exact algorithm is the odd one out, a defect of its own docs/OCCT.md
# 6.1 records: in o11's side views it draws part of the hidden torus outline as visible.
EXACT_AT_ODD = {("o11_curved.SLDPRT", "right"), ("o11_curved.SLDPRT", "left")}


@pytest.mark.parametrize("name", FIXTURE_PARTS)
@pytest.mark.occt
@pytest.mark.skipif(O.occt_python() is None, reason=f"{O.OCCT_PYTHON_ENV} is not set")
def test_solidseas_views_and_dimensions_agree_with_open_cascade(name):
    got = C.cross_check(fixture_path(name))
    assert got["occt"] == O.PINNED["occt"]
    for view, r in got["views"].items():
        assert "error" not in r, (view, r)
        for kind in C.KINDS:
            # SolidSeas is never the odd one out on the fixtures
            assert _odd(r, "ours", kind) <= 1e-3 * max(r[kind]["length"], 1.0), (view, kind, r[kind])
        expected = "exact" if (name, view) in EXACT_AT_ODD else None
        assert C.odd_one_out(r) == expected, (view, r["visible"])
    checked = [d for d in got["dimensions"] if d["checked"]]
    assert checked and all(d["ok"] for d in checked), checked


@pytest.mark.occt
@pytest.mark.skipif(O.occt_python() is None, reason=f"{O.OCCT_PYTHON_ENV} is not set")
def test_the_vote_shows_open_cascade_s_own_defect_on_o11(tmp_path):
    """The defect the evaluation found: OCCT's exact algorithm draws a hidden stretch of
    o11's torus outline as visible in the right view, where SolidSeas and OCCT's polygon
    algorithm agree it is hidden; the vote says so."""
    got = C.cross_check(fixture_path("o11_curved.SLDPRT"), views=("right",), plan=False)
    r = got["views"]["right"]
    assert C.odd_one_out(r) == "exact" and C.odd_one_out(r, "hidden") == "exact"
    assert 1.0 < r["visible"]["odd"]["exact"]["alone"] < 4.0  # 2.5 mm at OCCT 7.9.3
    assert 1.0 < r["hidden"]["odd"]["exact"]["missed"] < 4.0  # 2.4 mm
    assert r["visible"]["covered"]["ours_poly"] == 1.0 and r["visible"]["covered"]["poly_ours"] == 1.0


@pytest.mark.occt
@pytest.mark.skipif(O.occt_python() is None, reason=f"{O.OCCT_PYTHON_ENV} is not set")
def test_the_vote_catches_a_line_solidseas_leaves_out(tmp_path):
    from solidseas import open_document
    from solidseas.drawing import display as D
    from solidseas.drawing import facegraph
    from solidseas.drawing import views as V
    from solidseas.step import step_model, write_step

    part = fixture_path("o11_curved.SLDPRT")
    with open_document(str(part)) as doc:
        model = facegraph.from_document(doc)
        write_step(step_model(doc, name="part"), tmp_path / "part.step")
    spec = T.ViewSpec("v-1", "base", *V.view_frames()["front"], "front", hidden=True)
    occt, _versions = C.occt_views(tmp_path / "part.step", {"front": spec.frame()})
    geometry = V.project(model, spec)
    circles = [run for run in geometry.runs if isinstance(run.primitive, D.Arc) and run.style == "visible"]
    assert circles
    missing = sum(math.radians(c.primitive.sweep()) * c.primitive.radius / C.MM for c in circles)
    without = dataclasses.replace(geometry, runs=tuple(r for r in geometry.runs if r not in circles))
    r = C.vote({"ours": C.ours(without), **occt["front"]}, C.tolerance_mm(model))
    assert C.odd_one_out(r) == "ours"
    assert r["visible"]["odd"]["ours"]["missed"] == pytest.approx(missing, rel=0.02)
