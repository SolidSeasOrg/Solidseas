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

import pytest

import drawing_golden_support as G
from drawing_support import fixture
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing.dxf import entities as E
from solidseas.drawing.layout.glyphs import Pen


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
