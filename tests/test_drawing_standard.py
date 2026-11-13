"""The drawing standard a sheet is drawn to (``docs/DRAWINGS.md`` 7, 11.4, 22 rule 1;
``docs/drawings/iso.md``): the projection symbol shows the drawing's projection angle,
on the sheet and in the DXF alike.

The symbol is a truncated cone seen from the side, with the same cone seen from its
small end (two whole circles) on its right. A third-angle view stands on the side it is
seen from, so the cone's narrow end faces the circles; a first-angle view stands on the
far side, so its wide end does. The tests read which end of the cone is nearer the
circles from the strokes each writer makes.
"""

from __future__ import annotations

import functools
import json
from dataclasses import replace

import pytest

import drawing_golden_support as G
from drawing_support import fixture
from solidseas import drawing
from solidseas.drawing import checks, document, pipeline, standards
from solidseas.drawing import display as D
from solidseas.drawing import settings as S
from solidseas.drawing import types as T
from solidseas.drawing.dxf import entities as E
from solidseas.drawing.layout.glyphs import Pen
from solidseas.errors import InvalidArgumentError


def _points(path) -> list[tuple[float, float]]:
    return [(op[1], op[2]) for op in path if op[0] in ("M", "L")]


def _cone_and_circles(items):
    """The symbol's cone (its four corners) and its circles' centre, from painted strokes."""
    cone, centres = None, []
    for s in items:
        if not isinstance(s, D.Stroke):
            continue
        kinds = [op[0] for op in s.path]
        if kinds == ["M", "L", "L", "L", "Z"]:
            cone = _points(s.path)
        elif "C" in kinds:  # a circle, drawn as Bezier arcs
            xs = [v for op in s.path if op[0] == "C" for v in op[1::2]]
            ys = [v for op in s.path if op[0] == "C" for v in op[2::2]]
            centres.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    return cone, centres


def _end_facing(cone, centre) -> str:
    """Which end of the cone faces the circles: ``narrow`` or ``wide``."""
    xs = sorted({round(p[0], 6) for p in cone})
    assert len(xs) == 2, cone
    height = {}
    for x in xs:
        side = [p[1] for p in cone if round(p[0], 6) == x]
        height[x] = max(side) - min(side)
    near = min(xs, key=lambda x: abs(x - centre[0]))
    far = max(xs, key=lambda x: abs(x - centre[0]))
    assert height[near] != height[far]
    return "narrow" if height[near] < height[far] else "wide"


@pytest.mark.parametrize(("angle", "facing"), [("third", "narrow"), ("first", "wide")])
def test_the_painted_symbol_shows_its_angle(angle, facing):
    pen = Pen()
    box = pen.projection_symbol(10.0, 20.0, 6.0, angle=angle)
    cone, centres = _cone_and_circles(pen.items)
    assert cone is not None and len(centres) == 2
    assert centres[0] == pytest.approx(centres[1])  # concentric
    assert centres[0][0] > max(p[0] for p in cone)  # the end view on the cone's right
    assert _end_facing(cone, centres[0]) == facing
    assert box.x0 <= min(p[0] for p in cone) and box.x1 >= centres[0][0]


def test_a_symbol_asked_for_with_no_angle_is_third_angle():
    pen = Pen()
    pen.projection_symbol(0.0, 0.0, 6.0)
    cone, centres = _cone_and_circles(pen.items)
    assert _end_facing(cone, centres[0]) == "narrow"


@pytest.mark.parametrize(("angle", "facing"), [("third", "narrow"), ("first", "wide")])
def test_the_dxf_symbol_agrees_with_the_painted_one(angle, facing):
    ents = E.furniture_entities(D.ProjectionSymbol((100.0, 50.0), 6.0, angle), E.Context("mm", 1.0))
    circles = [e for e in ents if e.kind == "CIRCLE"]
    polys = [e for e in ents if e.kind == "LWPOLYLINE"]
    assert len(circles) == 2 and len(polys) == 1
    centre = (dict(circles[0].body)[10], dict(circles[0].body)[20])
    xs = [v for k, v in polys[0].body if k == 10]
    ys = [v for k, v in polys[0].body if k == 20]
    cone = list(zip(xs, ys, strict=True))
    assert centre[0] > max(xs)
    assert _end_facing(cone, centre) == facing


@functools.cache
def _o02():
    return drawing.make_drawing(fixture("o02_boxA.SLDPRT"), fields={"number": "SS-1"}, settings=G.settings())


def test_an_asme_drawing_carries_the_third_angle_symbol():
    d = _o02()
    symbols = [a for a in d.sheet.annotations if isinstance(a, D.ProjectionSymbol)]
    assert [s.angle for s in symbols] == ["third"]
    painted = [p for p in d.sheet.painted if p.owner == "projection"]
    cone, centres = _cone_and_circles(painted)
    assert cone is not None and centres and _end_facing(cone, centres[0]) == "narrow"
    assert not [c for c in d.checks if c.code == "R1.symbol"]


# --------------------------------------------------------------------------- the ISO switch (slice 1)


def _iso(**values):
    s = S.with_value(G.settings(), "standard", "profile", "iso")
    for key, value in values.items():
        s = S.with_value(s, "standard", key, value)
    return s


@functools.cache
def _drawn(profile: str = "asme", projection: str = "standard"):
    """Two blocks side by side drawn as an assembly, whose drawing keeps every view it is
    given (a part's leaves out a view that carries no dimension)."""
    from drawing_parts import MM, box
    from test_drawing_assembly import _synthetic_assembly

    settings = G.settings() if profile == "asme" else _iso()
    if projection != "standard":
        settings = S.with_value(settings, "standard", "projection", projection)
    parts = [
        ("1", "block", box(100 * MM, 60 * MM, 40 * MM), (0.0, 0.0, 0.0)),
        ("2", "cap", box(30 * MM, 20 * MM, 20 * MM), (110 * MM, 0.0, 0.0)),
    ]
    options = T.DrawingOptions(units="mm", views=("front", "top", "right", "isometric"))
    stages = {"source": _synthetic_assembly(parts)}
    return pipeline.run(None, options=options, fields={"number": "SS-1"}, settings=settings, stages=stages)


def _centres(d) -> dict[str, tuple[float, float]]:
    boxes: dict[str, list[float]] = {}
    for g in d.sheet.geometry:
        b = g.bounds()
        cur = boxes.setdefault(g.src.view, [b[0], b[1], b[2], b[3]])
        cur[0], cur[1] = min(cur[0], b[0]), min(cur[1], b[1])
        cur[2], cur[3] = max(cur[2], b[2]), max(cur[3], b[3])
    return {v: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for v, b in boxes.items()}


def _same_centres(a: dict[str, tuple[float, float]], b: dict[str, tuple[float, float]]) -> bool:
    """The same views at the same centres, within approx's default tolerance."""
    return a.keys() == b.keys() and [c for v in sorted(a) for c in a[v]] == pytest.approx(
        [c for v in sorted(b) for c in b[v]]
    )


def _angles(d) -> list[str]:
    return [a.angle for a in d.sheet.annotations if isinstance(a, D.ProjectionSymbol)]


def _block(d) -> tuple[str, ...]:
    return next(a for a in d.sheet.annotations if isinstance(a, D.ToleranceBlock)).lines


@functools.cache
def _part(profile: str = "asme", projection: str = "standard"):
    """o02 as a part's drawing, which has a tolerance block (an assembly's has none)."""
    settings = G.settings() if profile == "asme" else _iso()
    if projection != "standard":
        settings = S.with_value(settings, "standard", "projection", projection)
    return pipeline.run(fixture("o02_boxA.SLDPRT"), fields={"number": "SS-1"}, settings=settings)


def test_the_settings_name_the_standard_and_the_projection():
    assert standards.projection(S.DrawingSettings()) == "third"
    assert standards.projection(_iso()) == "first"
    assert standards.projection(_iso(projection="third")) == "third"
    asme_first = S.with_value(S.DrawingSettings(), "standard", "projection", "first")
    assert standards.projection(asme_first) == "first"
    iso = S.default_settings("iso")
    assert (iso.standard.profile, iso.standard.units, iso.standard.unit_for_unstated) == ("iso", "mm", "mm")
    assert standards.projection(iso) == "first" and S.default_settings() == S.DrawingSettings()
    with pytest.raises(InvalidArgumentError):
        S.default_settings("din")
    with pytest.raises(InvalidArgumentError):
        S.with_value(S.DrawingSettings(), "standard", "projection", "second")
    back, problems = S.from_dict(S.to_dict(_iso(projection="third")))
    assert problems == [] and (back.standard.profile, back.standard.projection) == ("iso", "third")


def test_an_iso_drawing_is_drawn_in_first_angle():
    asme, iso = _drawn().drawing, _drawn("iso").drawing
    a, i = _centres(asme), _centres(iso)
    views = {s.name: s.id for s, _g in _drawn("iso").views}
    front, top, right = views["front"], views["top"], views["right"]
    # third angle: the view from above above the front, from the right on its right
    assert a[top][1] > a[front][1] and a[right][0] > a[front][0]
    # first angle: each on the far side from where it is seen, still aligned
    assert i[top][1] < i[front][1] and i[right][0] < i[front][0]
    assert i[top][0] == pytest.approx(i[front][0], abs=0.01)
    assert i[right][1] == pytest.approx(i[front][1], abs=0.01)
    # the symbol says so, in the annotation and on the sheet
    assert _angles(iso) == ["first"]
    cone, centres = _cone_and_circles([p for p in iso.sheet.painted if p.owner == "projection"])
    assert _end_facing(cone, centres[0]) == "wide"
    assert not {c.code for c in iso.checks} & {"R1.symbol", "R1.aligned"}


def test_an_iso_part_drawing_names_the_iso_gps_system():
    iso = _part("iso").drawing
    assert _block(iso)[-1] == "TOLERANCING ISO 8015" and "Y14.5" not in " ".join(_block(iso))
    assert _block(_part().drawing)[-1] == standards.INTERPRETATION
    assert _angles(iso) == ["first"]
    assert not {c.code for c in iso.checks} & {"R1.symbol", "R1.aligned", "R3.tolerance"}
    assert all("Y14.5" not in c.message for c in iso.checks)


def test_the_projection_chosen_overrides_the_standards():
    third = _drawn("iso", "third").drawing
    assert _same_centres(_centres(third), _centres(_drawn().drawing))  # placed as ASME places them
    assert _angles(third) == ["third"] and _block(_part("iso", "third").drawing)[-1] == "TOLERANCING ISO 8015"
    first = _drawn("asme", "first").drawing
    assert _same_centres(_centres(first), _centres(_drawn("iso").drawing))
    assert (
        _angles(first) == ["first"] and _block(_part("asme", "first").drawing)[-1] == standards.INTERPRETATION
    )
    assert not {c.code for c in first.checks} & {"R1.symbol", "R1.aligned"}


def test_the_checks_hold_a_drawing_to_its_own_standard():
    run = _drawn("iso")
    # the ISO sheet read as an ASME drawing: its symbol and its projected views are wrong for it
    as_asme = replace(run.drawing, settings=G.settings())
    words = [
        c.message
        for c in checks.run_checks(as_asme, planned=run.orchestrated.planned, layout=run.orchestrated.result)
    ]
    assert "the projection symbol shows first-angle projection; the drawing is third angle" in words
    assert sum("for third-angle projection" in w for w in words) == 2
    clean = checks.run_checks(run.drawing, planned=run.orchestrated.planned, layout=run.orchestrated.result)
    assert not {c.code for c in clean} & {"R1.symbol", "R1.aligned"}
    # and its statement
    part = _part("iso")
    as_asme = replace(part.drawing, settings=G.settings())
    words = [
        c.message
        for c in checks.run_checks(
            as_asme, planned=part.orchestrated.planned, layout=part.orchestrated.result
        )
    ]
    assert "the tolerance block does not name the standard the dimensions are interpreted by" in words


def test_an_iso_drawing_reads_back_as_iso():
    d = _part("iso").drawing
    data = document.dumps(d)
    assert json.loads(data)["options"]["profile"] == "iso"
    back, problems = document.loads(data)
    assert problems == [] and back.settings.standard.profile == "iso" and document.dumps(back) == data
    raw = json.loads(data)
    raw["options"]["profile"] = "din"
    _read, problems = document.loads(json.dumps(raw).encode("utf-8"))
    assert any("options.profile" in p for p in problems)
