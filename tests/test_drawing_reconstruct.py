"""The reconstruction oracle (docs/DRAWINGS.md 19.3, docs/drawings/conventions.md) on
the synthetic parts of 19.1.

The planner does not exist yet, so each part's dimensions are written here by hand
from its ground truth, as an engineer would draw them: baseline from the datums,
sizes once, patterns once with nX. A complete set gives no finding; taking a
location away makes it missing, a closing dimension makes it redundant (and as a
reference gives nothing), a value 0.1 mm off makes it wrong.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field, replace

import pytest

import drawing_parts as P
from drawing_reconstruct import AXES, DEFAULT_CONVENTIONS, Coincident, Conventions, Report, reconstruct
from drawing_support import model
from solidseas.drawing import facegraph
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.types import (
    Datum,
    Descriptor,
    FeatureSet,
    Frame,
    Hole,
    Pattern,
    PlannedDimension,
    Position,
    Width,
)
from solidseas.errors import InvalidArgumentError, SldLimitError

MM = 1e-3
OFF = 0.1 * MM  # the wrong value of the tests: 0.1 mm off


# --------------------------------------------------------------------------- the engineer's tools


def at(axis: str, value: float, *features: str) -> Position:
    """A face (or a round's tangent extreme) at ``value`` along ``axis``."""
    return Position(value, False, 0.0, features)


def mid(value: float, radius: float, *features: str) -> Position:
    """An axis or centre plane at ``value``."""
    return Position(value, True, radius, features)


@dataclass
class Sheet:
    """A drawing written by hand: the frame, the feature table, the dimensions in the
    order they are drawn, and the centre lines shown without a value."""

    model: facegraph.BrepModel
    frame: Frame
    features: dict[str, tuple[int, ...]]
    dims: list[PlannedDimension] = field(default_factory=list)
    coincident: list[Coincident] = field(default_factory=list)

    def _add(self, **kw) -> PlannedDimension:
        n = len(self.dims) + 1
        d = PlannedDimension(key=f"{kw['kind']}/{n}", id=f"d-{n}", view="v-1", **kw)
        self.dims.append(d)
        return d

    def lin(self, axis, a, b, value=None, *, tol="block", prefix="", kind="linear") -> PlannedDimension:
        value = abs(b.value - a.value) if value is None else value
        return self._add(kind=kind, value=value, axis=axis, positions=(a, b), tolerance=tol, prefix=prefix)

    def size(self, kind, value, features, *, radius, prefix="", tol="block", anchor=None) -> PlannedDimension:
        return self._add(
            kind=kind,
            value=value,
            features=tuple(features),
            radius=radius,
            prefix=prefix,
            tolerance=tol,
            anchor=anchor,
        )

    def callout(self, diameter, *features, prefix="", anchor=None) -> PlannedDimension:
        return self.size(
            "hole_callout", diameter, features, radius=diameter / 2, prefix=prefix, anchor=anchor
        )

    def angle(self, degrees, *features, axis=None, prefix="", anchor=None, tol="block") -> PlannedDimension:
        return self._add(
            kind="angle",
            value=math.radians(degrees),
            features=tuple(features),
            axis=axis,
            prefix=prefix,
            anchor=anchor,
            tolerance=tol,
        )

    def chamfer(self, leg, *features, prefix="", axis=None) -> PlannedDimension:
        return self._add(kind="chamfer", value=leg, features=tuple(features), prefix=prefix, axis=axis)

    def run(self, dims=None, conventions=DEFAULT_CONVENTIONS, **kw) -> Report:
        return reconstruct(
            self.model,
            self.frame,
            self.dims if dims is None else dims,
            conventions,
            features=kw.pop("features", self.features),
            coincident=kw.pop("coincident", self.coincident),
            **kw,
        )

    def get(self, did: str) -> PlannedDimension:
        return next(d for d in self.dims if d.id == did)

    def without(self, *ids: str) -> list[PlannedDimension]:
        assert all(any(d.id == i for d in self.dims) for i in ids)
        return [d for d in self.dims if d.id not in ids]

    def changed(self, did: str, **kw) -> list[PlannedDimension]:
        return [replace(d, **kw) if d.id == did else d for d in self.dims]

    def plus(self, *extra: PlannedDimension) -> list[PlannedDimension]:
        return [*self.dims, *extra]

    def extra(self, **kw) -> PlannedDimension:
        """A dimension drawn after the set, not kept in it."""
        d = self._add(**kw)
        self.dims.pop()
        return d

    def extra_lin(self, axis, a, b, value=None, *, tol="block", prefix="") -> PlannedDimension:
        value = abs(b.value - a.value) if value is None else value
        return self.extra(
            kind="linear", value=value, axis=axis, positions=(a, b), tolerance=tol, prefix=prefix
        )


def planes(m, axis: str, value: float) -> tuple[int, ...]:
    """The planar faces square to ``axis`` at ``value``."""
    k = AXES.index(axis)
    out = []
    for f in m.faces:
        if f.kind == "plane" and abs(abs(f.surface.normal[k]) - 1.0) < 1e-9:
            if abs(f.surface.origin[k] - value) < 1e-9:
                out.append(f.index)
    assert out, (axis, value)
    return tuple(out)


def plane(m, axis: str, value: float, sign: int) -> int:
    """The one planar face at ``value`` along ``axis`` whose outward normal points ``sign``."""
    k = AXES.index(axis)
    (face,) = [f for f in planes(m, axis, value) if m.faces[f].surface.normal[k] * sign > 0]
    return face


def rounds(m, x: float, y: float) -> tuple[int, ...]:
    """The round faces on the vertical axis through (x, y)."""
    for g in m.axis_groups:
        if abs(g.point[0] - x) < 1e-9 and abs(g.point[1] - y) < 1e-9:
            return g.faces
    raise AssertionError((x, y))


def hole(m, x: float, y: float) -> tuple[int, ...]:
    """A hole's faces: its round faces and the planar faces bounded by its circles alone
    (shoulders and floors)."""
    faces = set(rounds(m, x, y))
    for f in m.faces:
        if f.kind == "plane" and f.index not in faces:
            edges = [m.edges[k] for lp in f.loops for k in lp]
            if edges and all(e.curve.kind == "circle" and set(e.faces) & faces for e in edges):
                faces.add(f.index)
    return tuple(sorted(faces))


def frame(a: int, b: int, c: int) -> Frame:
    return Frame(
        datums=(Datum("A", a, "largest face"), Datum("B", b, "square to A"), Datum("C", c, "square to both"))
    )


def box_features(m, x, y, z) -> dict[str, tuple[int, ...]]:
    """The envelope's walls as three width features."""
    return {
        "f-env-x": planes(m, "x", 0.0) + planes(m, "x", x),
        "f-env-y": planes(m, "y", 0.0) + planes(m, "y", y),
        "f-env-z": planes(m, "z", 0.0) + planes(m, "z", z),
    }


def envelope(s: Sheet, x, y, z) -> None:
    s.lin("x", at("x", 0.0, "f-env-x"), at("x", x, "f-env-x"))
    s.lin("y", at("y", 0.0, "f-env-y"), at("y", y, "f-env-y"))
    s.lin("z", at("z", 0.0, "f-env-z"), at("z", z, "f-env-z"))


def datums(m) -> Frame:
    """A on the bottom, B on the front, C on the left."""
    return frame(plane(m, "z", 0.0, -1), plane(m, "y", 0.0, -1), plane(m, "x", 0.0, -1))


@functools.cache
def built(name: str, *args) -> facegraph.BrepModel:
    """Parts drawing_support.model does not hold (it takes drawing_parts.PARTS only)."""
    xt, _truth = getattr(P, name)(*args)
    return facegraph.from_transmit(xt, name=name)


# --------------------------------------------------------------------------- the parts, drawn


def four_holes() -> Sheet:
    m = model("four_holes")
    s = Sheet(m, datums(m), box_features(m, 100 * MM, 60 * MM, 10 * MM))
    spots = [(12, 10), (37, 48), (71, 15), (88, 44)]
    s.features["f-holes"] = tuple(f for x, y in spots for f in hole(m, x * MM, y * MM))
    envelope(s, 100 * MM, 60 * MM, 10 * MM)
    for x, y in spots:
        s.lin("x", at("x", 0.0, "f-env-x"), mid(x * MM, 3.3 * MM, "f-holes"))
        s.lin("y", at("y", 0.0, "f-env-y"), mid(y * MM, 3.3 * MM, "f-holes"))
    s.callout(6.6 * MM, "f-holes", prefix="4X")
    return s


HOLE_KINDS = {
    "simple": (15, 20),
    "cbore": (40, 20),
    "spot": (65, 20),
    "csk82": (90, 20),
    "csk90": (115, 20),
    "blind": (30, 55),
    "drill": (70, 55),
    "step": (110, 55),
}


def hole_kinds() -> Sheet:
    m = model("hole_kinds")
    s = Sheet(m, datums(m), box_features(m, 160 * MM, 80 * MM, 20 * MM))
    for name, (x, y) in HOLE_KINDS.items():
        s.features[f"f-{name}"] = hole(m, x * MM, y * MM)
    envelope(s, 160 * MM, 80 * MM, 20 * MM)
    for name, (x, y) in HOLE_KINDS.items():
        r = 3.3 * MM
        s.lin("x", at("x", 0.0, "f-env-x"), mid(x * MM, r, f"f-{name}"))
        s.lin("y", at("y", 0.0, "f-env-y"), mid(y * MM, r, f"f-{name}"))
    top = at("z", 20 * MM, "f-env-z")
    s.callout(6.6 * MM, "f-simple")
    # counterbore and spotface: the bore, then the counterbore's diameter and depth
    s.callout(6.6 * MM, "f-cbore")
    s.callout(11 * MM, "f-cbore")
    s.lin("z", top, at("z", 13.5 * MM, "f-cbore"), kind="hole_callout")
    s.callout(6.6 * MM, "f-spot")
    s.callout(13 * MM, "f-spot")
    s.lin("z", top, at("z", 19.5 * MM, "f-spot"), kind="hole_callout")
    # countersinks: the bore, the diameter at the surface and the included angle
    for name, degrees in (("csk82", 82), ("csk90", 90)):
        s.callout(6.6 * MM, f"f-{name}")
        s.callout(12 * MM, f"f-{name}")
        s.angle(degrees, f"f-{name}")
    # blind holes: the depth to the full diameter, never the drill point
    s.callout(8 * MM, "f-blind")
    s.lin("z", top, at("z", 8 * MM, "f-blind"), kind="hole_callout")
    s.callout(6.8 * MM, "f-drill")
    s.lin("z", top, at("z", 6 * MM, "f-drill"), kind="hole_callout")
    s.callout(10 * MM, "f-step")
    s.lin("z", top, at("z", 12 * MM, "f-step"), kind="hole_callout")
    s.callout(5 * MM, "f-step")
    return s


CIRCLE_CENTRE = (150 * MM, 60 * MM)


def circle_member(k: int) -> tuple[float, float, float]:
    a = math.radians(15 + 60 * k)
    return (CIRCLE_CENTRE[0] + 20 * MM * math.cos(a), CIRCLE_CENTRE[1] + 20 * MM * math.sin(a), 10 * MM)


def patterns() -> Sheet:
    m = model("patterns")
    s = Sheet(m, datums(m), box_features(m, 200 * MM, 120 * MM, 10 * MM))
    s.features["f-row"] = tuple(f for k in range(5) for f in hole(m, (20 + 20 * k) * MM, 20 * MM))
    s.features["f-grid"] = tuple(
        f for i in range(3) for j in range(2) for f in hole(m, (20 + 15 * i) * MM, (70 + 12 * j) * MM)
    )
    s.features["f-bore"] = hole(m, *CIRCLE_CENTRE)
    s.features["f-circ"] = tuple(f for k in range(6) for f in hole(m, *circle_member(k)[:2]))
    envelope(s, 200 * MM, 120 * MM, 10 * MM)
    x0, y0 = at("x", 0.0, "f-env-x"), at("y", 0.0, "f-env-y")
    # the row: callout with 5X, the first member located, 4X the pitch
    s.callout(5.5 * MM, "f-row", prefix="5X")
    s.lin("x", x0, mid(20 * MM, 2.75 * MM, "f-row"))
    s.lin("y", y0, mid(20 * MM, 2.75 * MM, "f-row"))
    s.lin("x", mid(20 * MM, 2.75 * MM, "f-row"), mid(40 * MM, 2.75 * MM, "f-row"), prefix="4X")
    # the grid: 6X, the first member, 2X 15 across and 12 up
    s.callout(4.5 * MM, "f-grid", prefix="6X")
    s.lin("x", x0, mid(20 * MM, 2.25 * MM, "f-grid"))
    s.lin("y", y0, mid(70 * MM, 2.25 * MM, "f-grid"))
    s.lin("x", mid(20 * MM, 2.25 * MM, "f-grid"), mid(35 * MM, 2.25 * MM, "f-grid"), prefix="2X")
    s.lin("y", mid(70 * MM, 2.25 * MM, "f-grid"), mid(82 * MM, 2.25 * MM, "f-grid"))
    # the bore and the pitch circle round it: 6X, the diameter and the first angle
    s.callout(16 * MM, "f-bore")
    s.lin("x", x0, mid(150 * MM, 8 * MM, "f-bore"))
    s.lin("y", y0, mid(60 * MM, 8 * MM, "f-bore"))
    s.callout(5.5 * MM, "f-circ", prefix="6X")
    s.size("diameter", 40 * MM, ("f-circ",), radius=20 * MM, anchor=(*CIRCLE_CENTRE, 10 * MM))
    s.angle(15, "f-circ", axis="x", anchor=circle_member(0))
    return s


def link() -> Sheet:
    m = model("link")
    holes = rounds(m, 15 * MM, 15 * MM) + rounds(m, 105 * MM, 15 * MM)
    feats = {
        "f-env-y": planes(m, "y", 0.0) + planes(m, "y", 30 * MM),
        "f-env-z": planes(m, "z", 0.0) + planes(m, "z", 8 * MM),
        "f-holes": tuple(f for f in holes if m.faces[f].surface.concave),
        "f-rounds": tuple(f for f in holes if not m.faces[f].surface.concave),
    }
    first = next(f for f in rounds(m, 15 * MM, 15 * MM) if m.faces[f].surface.concave)
    s = Sheet(m, frame(plane(m, "z", 0.0, -1), plane(m, "y", 0.0, -1), first), feats)
    s.lin("y", at("y", 0.0, "f-env-y"), at("y", 30 * MM, "f-env-y"))
    s.lin("z", at("z", 0.0, "f-env-z"), at("z", 8 * MM, "f-env-z"))
    s.lin("x", mid(15 * MM, 6 * MM, "f-holes"), mid(105 * MM, 6 * MM, "f-holes"))
    s.callout(12 * MM, "f-holes", prefix="2X")
    s.size("radius", 15 * MM, ("f-rounds",), radius=15 * MM, prefix="2X", tol="derived")
    return s


def boss() -> Sheet:
    m = model("boss")
    axis = rounds(m, 30 * MM, 30 * MM)
    feats = {
        "f-env-x": planes(m, "x", 0.0) + planes(m, "x", 60 * MM),
        "f-env-y": planes(m, "y", 0.0) + planes(m, "y", 60 * MM),
        "f-block": planes(m, "z", 0.0) + planes(m, "z", 20 * MM),
        "f-boss": tuple(f for f in axis if not m.faces[f].surface.concave) + planes(m, "z", 35 * MM),
        "f-hole": tuple(f for f in axis if m.faces[f].surface.concave),
    }
    s = Sheet(m, datums(m), feats)
    s.lin("x", at("x", 0.0, "f-env-x"), at("x", 60 * MM, "f-env-x"))
    s.lin("y", at("y", 0.0, "f-env-y"), at("y", 60 * MM, "f-env-y"))
    s.lin("z", at("z", 0.0, "f-block"), at("z", 20 * MM, "f-block"))
    s.lin("z", at("z", 20 * MM, "f-block"), at("z", 35 * MM, "f-boss"))
    s.lin("x", at("x", 0.0, "f-env-x"), mid(30 * MM, 15 * MM, "f-boss"))
    s.lin("y", at("y", 0.0, "f-env-y"), mid(30 * MM, 15 * MM, "f-boss"))
    s.size("diameter", 30 * MM, ("f-boss",), radius=15 * MM)
    s.callout(10 * MM, "f-hole")
    return s


def pocket_tab() -> Sheet:
    m = built("pocket_tab_block")
    y20 = planes(m, "y", 20 * MM)
    left = next(f for f in y20 if m.faces[f].box[0][0] < 1e-9)
    feats = {
        "f-env-x": planes(m, "x", 0.0) + planes(m, "x", 80 * MM),
        "f-env-z": planes(m, "z", 0.0) + planes(m, "z", 50 * MM),
        "f-base": planes(m, "y", 0.0) + (left,),
        "f-right": tuple(f for f in y20 if f != left),
        "f-tab": planes(m, "x", 66 * MM) + planes(m, "x", 72 * MM) + planes(m, "y", 35 * MM),
        "f-pocket": planes(m, "x", 15 * MM)
        + planes(m, "x", 55 * MM)
        + planes(m, "y", 4 * MM)
        + planes(m, "y", 16 * MM)
        + planes(m, "z", 42 * MM),
    }
    s = Sheet(m, datums(m), feats)
    x0 = at("x", 0.0, "f-env-x")
    s.lin("x", x0, at("x", 80 * MM, "f-env-x"))
    s.lin("x", x0, at("x", 66 * MM, "f-tab"))
    s.lin("x", at("x", 66 * MM, "f-tab"), at("x", 72 * MM, "f-tab"))  # the tab's thickness, directly
    s.lin("x", x0, at("x", 15 * MM, "f-pocket"))
    s.lin("x", at("x", 15 * MM, "f-pocket"), at("x", 55 * MM, "f-pocket"))  # the pocket's length
    s.lin("y", at("y", 0.0, "f-base"), at("y", 20 * MM, "f-base"))
    s.lin("y", at("y", 20 * MM, "f-base"), at("y", 35 * MM, "f-tab"))
    s.lin("y", at("y", 0.0, "f-base"), at("y", 4 * MM, "f-pocket"))
    s.lin("y", at("y", 4 * MM, "f-pocket"), at("y", 16 * MM, "f-pocket"))  # the pocket's width
    s.lin("z", at("z", 0.0, "f-env-z"), at("z", 50 * MM, "f-env-z"))
    s.lin("z", at("z", 50 * MM, "f-env-z"), at("z", 42 * MM, "f-pocket"))  # depth from the open face
    return s


def step_slot() -> Sheet:
    m = model("step_slot")
    ends1 = rounds(m, 15 * MM, 20 * MM) + rounds(m, 45 * MM, 20 * MM)
    ends2 = rounds(m, 60 * MM, 15 * MM) + rounds(m, 60 * MM, 35 * MM)
    feats = box_features(m, 100 * MM, 60 * MM, 30 * MM)
    feats.update(
        {
            "f-step": planes(m, "x", 80 * MM) + planes(m, "y", 40 * MM),
            "f-slot1": planes(m, "y", 16 * MM) + planes(m, "y", 24 * MM) + ends1,
            "f-slot1-ends": ends1,
            "f-slot2": planes(m, "x", 57 * MM) + planes(m, "x", 63 * MM) + ends2 + planes(m, "z", 25 * MM),
            "f-slot2-ends": ends2,
            "f-chamfers": tuple(
                f.index
                for f in m.faces
                if f.kind == "plane" and max(abs(c) for c in f.surface.normal) < 1 - 1e-9
            ),
        }
    )
    s = Sheet(m, datums(m), feats)
    envelope(s, 100 * MM, 60 * MM, 30 * MM)
    x0, y0 = at("x", 0.0, "f-env-x"), at("y", 0.0, "f-env-y")
    s.lin("x", x0, at("x", 80 * MM, "f-step"))
    s.lin("y", y0, at("y", 40 * MM, "f-step"))
    # the through slot: width, 2X R, centre distance, one end along, the centre line across
    s.lin("y", at("y", 16 * MM, "f-slot1"), at("y", 24 * MM, "f-slot1"))
    s.size("radius", 4 * MM, ("f-slot1-ends",), radius=4 * MM, prefix="2X", tol="derived")
    s.lin("x", mid(15 * MM, 4 * MM, "f-slot1"), mid(45 * MM, 4 * MM, "f-slot1"))
    s.lin("x", x0, mid(15 * MM, 4 * MM, "f-slot1"))
    s.lin("y", y0, mid(20 * MM, 4 * MM, "f-slot1"))
    # the blind slot, running along y, and its depth from the top
    s.lin("x", at("x", 57 * MM, "f-slot2"), at("x", 63 * MM, "f-slot2"))
    s.size("radius", 3 * MM, ("f-slot2-ends",), radius=3 * MM, prefix="2X", tol="derived")
    s.lin("y", mid(15 * MM, 3 * MM, "f-slot2"), mid(35 * MM, 3 * MM, "f-slot2"))
    s.lin("x", x0, mid(60 * MM, 3 * MM, "f-slot2"))
    s.lin("y", y0, mid(15 * MM, 3 * MM, "f-slot2"))
    s.lin("z", at("z", 30 * MM, "f-env-z"), at("z", 25 * MM, "f-slot2"))
    s.chamfer(3 * MM, "f-chamfers", prefix="5X")
    return s


def random_plate(seed: int) -> Sheet:
    m = built("random_plate", seed)
    _xt, truth = P.random_plate(seed)
    w, d, t = (truth["box"][1][i] for i in range(3))
    s = Sheet(m, datums(m), box_features(m, w, d, t))
    envelope(s, w, d, t)
    sizes: dict[float, list[str]] = {}
    for k, h in enumerate(truth["holes"]):
        fid = f"f-h{k}"
        x, y, _z = h["at"]
        s.features[fid] = hole(m, x, y)
        sizes.setdefault(h["diameter"], []).append(fid)
    for dia in sorted(sizes):
        ids = sizes[dia]
        group = f"f-dia{len(s.features)}"
        s.features[group] = tuple(f for fid in ids for f in s.features[fid])
        s.callout(dia, group, prefix=f"{len(ids)}X" if len(ids) > 1 else "")
    for k, h in enumerate(truth["holes"]):
        x, y, _z = h["at"]
        s.lin("x", at("x", 0.0, "f-env-x"), mid(x, h["diameter"] / 2, f"f-h{k}"))
        s.lin("y", at("y", 0.0, "f-env-y"), mid(y, h["diameter"] / 2, f"f-h{k}"))
    return s


DRAWN = {
    "four_holes": (four_holes, 18),
    "hole_kinds": (hole_kinds, 42),
    "patterns": (patterns, 61),
    "link": (link, 12),
    "boss": (boss, 11),
    "pocket_tab": (pocket_tab, 14),
    "step_slot": (step_slot, 35),
}


def kinds(report: Report) -> list[tuple[str, str, str | None]]:
    return [(f.kind, f.what, f.axis) for f in report.findings]


# --------------------------------------------------------------------------- complete sets


@pytest.mark.parametrize("name", sorted(DRAWN))
def test_a_complete_set_gives_no_finding(name):
    make, targets = DRAWN[name]
    report = make().run()
    assert report.findings == (), [str(f) for f in report.findings]
    assert report.targets == targets
    assert report.recovered == targets
    assert report.uncovered == ()
    assert report.counts()["missing"] == 0 and report.ok


@pytest.mark.parametrize("seed", [1, 7, 23])
def test_a_seeded_random_plate_drawn_baseline_gives_no_finding(seed):
    s = random_plate(seed)
    report = s.run()
    assert report.findings == (), [str(f) for f in report.findings]
    holes = len(P.random_plate(seed)[1]["holes"])
    assert report.targets == 6 + 3 * holes  # six faces, two axis positions and a diameter a hole


# --------------------------------------------------------------------------- missing, redundant, wrong


def find(s: Sheet, axis: str, value: float, start: float | None = None) -> PlannedDimension:
    """The linear dimension along ``axis`` whose far end is at ``value`` (and near end at
    ``start``)."""
    (d,) = [
        d
        for d in s.dims
        if d.axis == axis
        and len(d.positions) == 2
        and abs(d.positions[1].value - value) < 1e-9
        and (start is None or abs(d.positions[0].value - start) < 1e-9)
    ]
    return d


# For each part: a location to take away and what goes missing; a closing dimension
# and what it makes redundant; a dimension to put 0.1 mm off and what comes out wrong.
CASES = {
    "four_holes": (
        ("x", 71 * MM, None),
        [("missing", "axis", "x")],
        lambda s: s.extra_lin("x", mid(12 * MM, 3.3 * MM, "f-holes"), mid(37 * MM, 3.3 * MM, "f-holes")),
        ("redundant", "axis", "x"),
        ("y", 48 * MM, None),
        [("wrong", "axis", "y")],
    ),
    "hole_kinds": (
        ("x", 30 * MM, None),  # the blind hole's location along
        [("missing", "axis", "x")],
        lambda s: s.extra_lin("z", at("z", 0.0, "f-env-z"), at("z", 13.5 * MM, "f-cbore")),
        ("redundant", "plane", "z"),
        ("z", 13.5 * MM, None),  # the counterbore's depth
        [("wrong", "plane", "z")],
    ),
    "patterns": (
        ("y", 20 * MM, 0.0),  # the row's location across: all five members go
        [("missing", "axis", "y")] * 5,
        lambda s: s.extra_lin("x", at("x", 0.0, "f-env-x"), mid(100 * MM, 2.75 * MM, "f-row")),
        ("redundant", "axis", "x"),
        ("x", 35 * MM, 20 * MM),  # the grid's pitch across: the second and third columns move
        [("wrong", "axis", "x")] * 4,
    ),
    "link": (
        ("x", 105 * MM, None),  # the centre distance
        [("missing", "axis", "x")],
        # the overall length, between the two ends' tangent extremes
        lambda s: s.extra_lin("x", at("x", 0.0, "f-rounds"), at("x", 120 * MM, "f-rounds")),
        ("redundant", "extreme", "x"),
        ("y", 30 * MM, None),  # the width: the far side, both centres and both derived radii move
        [("wrong", "radius", None)] * 2 + [("wrong", "axis", "y")] * 2 + [("wrong", "plane", "y")],
    ),
    "boss": (
        ("x", 30 * MM, None),
        [("missing", "axis", "x")],
        lambda s: s.extra_lin("x", mid(30 * MM, 15 * MM, "f-boss"), at("x", 60 * MM, "f-env-x")),
        ("redundant", "plane", "x"),
        ("z", 35 * MM, None),  # the boss's height
        [("wrong", "plane", "z")],
    ),
    "pocket_tab": (
        ("x", 72 * MM, None),  # the tab's thickness
        [("missing", "plane", "x")],
        lambda s: s.extra_lin("x", at("x", 0.0, "f-env-x"), at("x", 72 * MM, "f-tab")),
        ("redundant", "plane", "x"),
        ("z", 42 * MM, None),  # the pocket's depth
        [("wrong", "plane", "z")],
    ),
    "step_slot": (
        ("y", 15 * MM, 0.0),  # the blind slot's end along: both ends go
        [("missing", "axis", "y")] * 2,
        lambda s: s.extra_lin("x", at("x", 0.0, "f-env-x"), mid(45 * MM, 4 * MM, "f-slot1")),
        ("redundant", "axis", "x"),
        ("x", 80 * MM, None),  # the step
        [("wrong", "plane", "x")],
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_taking_a_location_away_makes_it_missing(name):
    s = DRAWN[name][0]()
    (axis, value, start), expected, *_ = CASES[name]
    gone = find(s, axis, value, start)
    report = s.run(s.without(gone.id))
    assert kinds(report) == expected, [str(f) for f in report.findings]
    assert report.recovered == report.targets - len(expected)


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_closing_dimension_is_redundant_and_as_a_reference_is_not(name):
    s = DRAWN[name][0]()
    _gone, _missing, close, expected, *_ = CASES[name]
    extra = close(s)
    report = s.run(s.plus(extra))
    assert kinds(report) == [expected], [str(f) for f in report.findings]
    (finding,) = report.findings
    assert extra.id in finding.dimensions and len(finding.dimensions) >= 2
    assert report.recovered == report.targets  # everything is still recovered, once too often
    reference = replace(extra, tolerance="reference")
    assert s.run(s.plus(reference)).findings == ()
    wrong = replace(reference, value=reference.value + OFF)
    (finding,) = s.run(s.plus(wrong)).findings
    assert (finding.kind, finding.what, finding.dimensions) == ("wrong", "dimension", (extra.id,))


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_value_off_by_a_tenth_of_a_millimetre_is_wrong(name):
    s = DRAWN[name][0]()
    *_, (axis, value, start), expected = CASES[name]
    off = find(s, axis, value, start)
    report = s.run(s.changed(off.id, value=off.value + OFF))
    assert sorted(kinds(report), key=repr) == sorted(expected, key=repr), [str(f) for f in report.findings]
    for f in report.findings:
        assert off.id in f.dimensions
        assert f.found is not None and f.expected is not None
        # a half, the whole or a multiple of it: a derived radius takes half, a pitch's
        # second space twice
        steps = abs(f.found - f.expected) / (OFF / 2)
        assert steps == pytest.approx(round(steps), abs=1e-6) and round(steps) >= 1


def test_findings_name_the_face_the_axis_and_the_dimensions():
    s = four_holes()
    loc = find(s, "y", 48 * MM)
    report = s.run(s.changed(loc.id, value=48 * MM + OFF))
    (f,) = report.findings
    assert f.faces == hole(s.model, 37 * MM, 48 * MM)
    assert (f.axis, f.dimensions) == ("y", (loc.id,))
    assert f.expected == pytest.approx(48 * MM) and f.found == pytest.approx(48.1 * MM)
    assert str(f).startswith("wrong: axis of faces") and loc.id in str(f)
    gone = find(s, "x", 71 * MM)
    (f,) = s.run(s.without(gone.id)).findings
    assert f.faces == hole(s.model, 71 * MM, 15 * MM) and "do not determine" in f.words


def test_a_size_stated_twice_is_redundant_and_a_size_left_out_is_missing():
    s = four_holes()
    again = s.extra(
        kind="hole_callout",
        value=6.6 * MM,
        features=("f-holes",),
        radius=3.3 * MM,
        anchor=(12 * MM, 10 * MM, 0.0),
    )
    (f,) = s.run(s.plus(again)).findings
    assert (f.kind, f.what) == ("redundant", "radius") and f.faces == hole(s.model, 12 * MM, 10 * MM)
    callout = s.dims[-1]
    assert kinds(s.run(s.without(callout.id))) == [("missing", "radius", None)] * 4
    report = s.run(s.changed(callout.id, value=6.7 * MM))
    assert kinds(report) == [("wrong", "radius", None)] * 4


def test_nx_on_holes_that_are_not_equally_spaced_is_wrong():
    s = four_holes()
    pitch = s.extra_lin(
        "x", mid(12 * MM, 3.3 * MM, "f-holes"), mid(37 * MM, 3.3 * MM, "f-holes"), prefix="3X"
    )
    report = s.run(s.plus(pitch))
    relations = [f for f in report.of_kind("wrong") if f.what == "relation"]
    assert len(relations) == 2 and all("spaces its pattern equally" in f.words for f in relations)
    assert all(pitch.id in f.dimensions for f in report.findings)


def test_nx_must_equal_the_count():
    s = four_holes()
    callout = s.dims[-1]
    (f,) = s.run(s.changed(callout.id, prefix="3X")).findings
    assert (f.kind, f.what, f.expected, f.found) == ("wrong", "count", 4.0, 3.0)  # the model's, the drawing's
    (f,) = s.run(s.changed(callout.id, prefix="")).findings
    assert (f.kind, f.what) == ("wrong", "count")


# --------------------------------------------------------------------------- hole kinds


def test_hole_depths_floors_and_countersinks_are_recovered_from_their_callouts():
    s = hole_kinds()
    for value, what in ((13.5, "plane"), (19.5, "plane"), (8, "plane"), (6, "end"), (12, "end")):
        depth = find(s, "z", value * MM, 20 * MM)
        assert kinds(s.run(s.without(depth.id))) == [("missing", what, "z")], value
    angle = next(d for d in s.dims if d.kind == "angle")
    (f,) = s.run(s.without(angle.id)).findings
    assert (f.kind, f.what, f.faces) == ("missing", "angle", f.faces) and "countersink angle" in f.words
    (f,) = s.run(s.changed(angle.id, value=math.radians(83))).findings
    assert (f.kind, f.what) == ("wrong", "angle")
    assert math.degrees(f.expected) == pytest.approx(82) and math.degrees(f.found) == pytest.approx(83)
    csk = next(d for d in s.dims if d.kind == "hole_callout" and d.value == 12 * MM)
    (f,) = s.run(s.without(csk.id)).findings
    assert (f.kind, f.what) == ("missing", "radius") and "countersink diameter" in f.words
    cbore = next(d for d in s.dims if d.kind == "hole_callout" and d.value == 11 * MM)
    (f,) = s.run(s.changed(cbore.id, value=11 * MM + OFF)).findings
    assert (f.kind, f.what, f.found - f.expected) == ("wrong", "radius", pytest.approx(OFF / 2))


def test_the_drill_point_and_the_step_cone_are_implied_and_not_dimensioned():
    report = hole_kinds().run()
    assert report.ok and report.uncovered == ()
    # the drill point and the step's cone are no target: 42 is every face, axis and size else
    assert report.targets == 42


# --------------------------------------------------------------------------- patterns


def test_a_pattern_drawn_once_with_nx_and_its_pitch_recovers_every_member():
    s = patterns()
    report = s.run()
    assert report.ok
    pitch = find(s, "x", 40 * MM, 20 * MM)
    assert pitch.prefix == "4X"
    # without nX the pitch is only the distance between the first two members
    plain = s.run(s.changed(pitch.id, prefix=""))
    assert kinds(plain) == [("missing", "axis", "x")] * 3
    assert {f.faces for f in plain.findings} == {hole(s.model, x * MM, 20 * MM) for x in (60, 80, 100)}
    # nX counts the spaces
    (f,) = s.run(s.changed(pitch.id, prefix="5X")).findings
    assert (f.kind, f.what, f.expected, f.found) == ("wrong", "count", 4.0, 5.0)


def test_a_grid_is_located_by_its_first_member_and_a_pitch_each_way():
    s = patterns()
    across = find(s, "x", 35 * MM, 20 * MM)
    up = find(s, "y", 82 * MM, 70 * MM)
    assert kinds(s.run(s.without(up.id))) == [("missing", "axis", "y")] * 3
    assert kinds(s.run(s.without(across.id))) == [("missing", "axis", "x")] * 4
    report = s.run(s.changed(up.id, value=12 * MM + OFF))
    assert kinds(report) == [("wrong", "axis", "y")] * 3


def test_a_circular_patterns_pitch_circle_count_and_first_angle_recover_every_member():
    s = patterns()
    angle = next(d for d in s.dims if d.kind == "angle")
    pcd = next(d for d in s.dims if d.kind == "diameter")
    members = {hole(s.model, *circle_member(k)[:2]) for k in range(6)}
    report = s.run()
    assert report.ok
    # without the first angle no member can be placed: the angle and all twelve positions
    report = s.run(s.without(angle.id))
    assert sorted(kinds(report)) == sorted(
        [("missing", "angle", None)] + [("missing", "axis", a) for a in "xy" * 6]
    )
    assert {f.faces for f in report.findings if f.what == "axis"} == members
    # a reference angle states nothing
    report = s.run(s.changed(angle.id, tolerance="reference"))
    assert ("missing", "angle", None) in kinds(report)
    # without the pitch circle's diameter every member is missing
    report = s.run(s.without(pcd.id))
    assert kinds(report) == [("missing", "axis", a) for a in "xxxxxxyyyyyy"]
    # a wrong angle puts every member in the wrong place
    report = s.run(s.changed(angle.id, value=math.radians(15.1)))
    assert sorted(kinds(report)) == sorted(
        [("wrong", "angle", None)] + [("wrong", "axis", a) for a in "xy" * 6]
    )
    assert all(angle.id in f.dimensions for f in report.findings)
    # a wrong diameter too
    report = s.run(s.changed(pcd.id, value=40 * MM + OFF))
    assert len(report.of_kind("wrong")) == 12 and all(pcd.id in f.dimensions for f in report.findings)


def test_the_angle_may_be_measured_from_either_frame_axis():
    s = patterns()
    angle = next(d for d in s.dims if d.kind == "angle")
    # member 1 sits at 75 degrees: 15 degrees from the y axis
    from_y = replace(angle, axis="y", value=math.radians(15), anchor=circle_member(1))
    assert s.run(s.changed(angle.id, axis="y", value=math.radians(15), anchor=circle_member(1))).ok
    twice = s.run(s.plus(replace(from_y, id="d-99")))
    assert kinds(twice) == [("redundant", "angle", None)]


def square_circle():
    """Four holes on a 40 mm pitch circle at 0, 90, 180 and 270 degrees round a bore."""
    t = 10 * MM
    p = P.box(100 * MM, 100 * MM, t)
    p = P.cut_hole(p, (50 * MM, 50 * MM, t), "-z", [("bore", 16 * MM, None)], "bore")
    for k in range(4):
        a = math.radians(90 * k)
        at_ = (50 * MM + 20 * MM * math.cos(a), 50 * MM + 20 * MM * math.sin(a), t)
        p = P.cut_hole(p, at_, "-z", [("bore", 5 * MM, None)], f"c{k}")
    return P.build(p)


def test_a_member_on_a_centre_line_needs_no_angle():
    xt, _truth = square_circle()
    m = facegraph.from_transmit(xt, name="square_circle")
    s = Sheet(m, datums(m), box_features(m, 100 * MM, 100 * MM, 10 * MM))
    s.features["f-bore"] = hole(m, 50 * MM, 50 * MM)
    s.features["f-circ"] = tuple(
        f for x, y in ((70, 50), (50, 70), (30, 50), (50, 30)) for f in hole(m, x * MM, y * MM)
    )
    envelope(s, 100 * MM, 100 * MM, 10 * MM)
    s.callout(16 * MM, "f-bore")
    s.lin("x", at("x", 0.0, "f-env-x"), mid(50 * MM, 8 * MM, "f-bore"))
    s.lin("y", at("y", 0.0, "f-env-y"), mid(50 * MM, 8 * MM, "f-bore"))
    s.callout(5 * MM, "f-circ", prefix="4X")
    s.size("diameter", 40 * MM, ("f-circ",), radius=20 * MM, anchor=(50 * MM, 50 * MM, 10 * MM))
    assert s.run().ok
    zero = s.extra(
        kind="angle", value=0.0, features=("f-circ",), axis="x", anchor=(70 * MM, 50 * MM, 10 * MM)
    )
    assert kinds(s.run(s.plus(zero))) == [("redundant", "angle", None)]
    report = s.run(conventions=Conventions(square=False))
    assert sorted(kinds(report)) == sorted(
        [("missing", "angle", None)] + [("missing", "axis", a) for a in "xy" * 4]
    )


def arc_point(deg: float) -> tuple[float, float, float]:
    a = math.radians(deg)
    return (50 * MM + 30 * MM * math.cos(a), 50 * MM + 30 * MM * math.sin(a), 10 * MM)


def arc_sheet(angles, first: float | None, step: float, axis="x") -> Sheet:
    """``arc_plate``'s holes drawn as a drafter draws an arc pattern: the bore located,
    the callout with nX, the 60 mm pitch circle, the first end's angle from ``axis`` the
    nearer way (none when ``first`` is None, the end being on a centre line) and the
    step from the first end to the second with the count of spaces."""
    m = built("arc_plate", tuple(angles))
    s = Sheet(m, datums(m), box_features(m, 100 * MM, 100 * MM, 10 * MM))
    s.features["f-bore"] = hole(m, 50 * MM, 50 * MM)
    s.features["f-arc"] = tuple(f for a in angles for f in hole(m, *arc_point(a)[:2]))
    envelope(s, 100 * MM, 100 * MM, 10 * MM)
    s.callout(16 * MM, "f-bore")
    s.lin("x", at("x", 0.0, "f-env-x"), mid(50 * MM, 8 * MM, "f-bore"))
    s.lin("y", at("y", 0.0, "f-env-y"), mid(50 * MM, 8 * MM, "f-bore"))
    n = len(angles)
    s.callout(5 * MM, "f-arc", prefix=f"{n}X")
    s.size("diameter", 60 * MM, ("f-arc",), radius=30 * MM, anchor=(50 * MM, 50 * MM, 10 * MM))
    if first is not None:
        s.angle(first, "f-arc", axis=axis, anchor=arc_point(angles[0]), tol="basic")
    s._add(
        kind="angle",
        value=math.radians(step),
        features=("f-arc",),
        prefix=f"{n - 1}X ",
        anchor=arc_point(angles[1]),
        radius=30 * MM,
        tolerance="basic",
    )
    return s


def test_an_arc_patterns_pitch_circle_first_angle_and_step_recover_every_member():
    """Five holes 30 degrees apart from 20 degrees: the step (4X 30°) is an angle with no
    axis, read as the arc's step and not as a countersink's angle."""
    s = arc_sheet([20, 50, 80, 110, 140], 20, 30)
    angle = next(d for d in s.dims if d.kind == "angle" and d.axis == "x")
    step = next(d for d in s.dims if d.kind == "angle" and d.axis is None)
    report = s.run()
    assert report.ok, report.summary()
    # without the step only the first end is placed, and the step is missing
    report = s.run(s.without(step.id))
    assert sorted(kinds(report)) == sorted(
        [("missing", "angle", None)] + [("missing", "axis", a) for a in "xy" * 4]
    )
    # a wrong step puts every member past the first in the wrong place
    report = s.run(s.changed(step.id, value=math.radians(30.1)))
    assert sorted(kinds(report)) == sorted(
        [("wrong", "angle", None)] + [("wrong", "axis", a) for a in "xy" * 4]
    )
    assert all(step.id in f.dimensions for f in report.findings)
    # a wrong first angle moves them all
    report = s.run(s.changed(angle.id, value=math.radians(20.1)))
    assert sorted(kinds(report)) == sorted(
        [("wrong", "angle", None)] + [("wrong", "axis", a) for a in "xy" * 5]
    )
    # nX counts the spaces
    (f,) = s.run(s.changed(step.id, prefix="5X ")).findings
    assert (f.kind, f.what, f.expected, f.found) == ("wrong", "count", 4.0, 5.0)
    # without nX the step places only the second member
    report = s.run(s.changed(step.id, prefix=""))
    assert sorted(kinds(report)) == sorted([("missing", "axis", a) for a in "xy" * 3])
    # the step stated twice is redundant
    twice = replace(step, id="d-99")
    assert kinds(s.run(s.plus(twice))) == [("redundant", "angle", None)]


def test_an_arcs_first_angle_is_measured_the_nearer_way_along_the_axis():
    """An arc from 200 degrees is 20 degrees below the X axis's negative side."""
    assert arc_sheet([200, 230, 260, 290], 20, 30).run().ok


def test_an_arc_ending_on_a_centre_line_needs_no_first_angle():
    """From 90 degrees down to 30: the end on the Y centre line is the first, and the
    step drawn from it to the 60 degree hole runs the arc clockwise. A centre line
    through a middle hole implies nothing."""
    assert arc_sheet([90, 60, 30], None, 30).run().ok
    s = arc_sheet([60, 90, 120, 150], 60, 30)
    assert s.run().ok
    angle = next(d for d in s.dims if d.kind == "angle" and d.axis == "x")
    report = s.run(s.without(angle.id))
    assert sorted(kinds(report)) == sorted(
        [("missing", "angle", None)] + [("missing", "axis", a) for a in "xy" * 4]
    )


# --------------------------------------------------------------------------- derived radii, tangency


def test_a_derived_full_round_end_recovers_its_radius_from_the_width():
    s = link()
    derived = next(d for d in s.dims if d.tolerance == "derived")
    assert s.run().ok
    # without "2X R" the ends' form is not stated
    report = s.run(s.without(derived.id))
    assert kinds(report) == [("missing", "radius", None)] * 2
    assert all("not stated" in f.words for f in report.findings)
    # a value on a derived radius repeats the width: R15 closes the loop
    stated = s.changed(derived.id, tolerance="block")
    assert kinds(s.run(stated)) == [("redundant", "radius", None)] * 2
    # with the derived convention off, "R" alone says nothing
    assert kinds(s.run(conventions=Conventions(derived=False))) == [("missing", "radius", None)] * 2


def test_a_derived_radius_on_a_round_that_is_not_a_full_round_is_wrong():
    s = boss()
    dia = next(d for d in s.dims if d.kind == "diameter")
    derived = replace(dia, kind="radius", value=15 * MM, tolerance="derived")
    report = s.run(s.changed(dia.id, kind="radius", value=15 * MM, tolerance="derived"))
    assert ("wrong", "radius", None) in kinds(report)
    assert derived.id in report.of_kind("wrong")[0].dimensions


def test_the_link_needs_no_datum_on_x_when_a_round_can_be_the_origin():
    s = link()
    s.frame = Frame(datums=s.frame.datums[:2])
    report = s.run()
    assert report.ok
    assert dict(report.origins)["x"].startswith("the largest round feature")


def test_a_boss_located_by_its_tangent_extreme_is_recovered_through_its_diameter():
    s = boss()
    loc = find(s, "x", 30 * MM)
    edge = replace(loc, positions=(loc.positions[0], at("x", 15 * MM, "f-boss")), value=15 * MM)
    swapped = [edge if d.id == loc.id else d for d in s.dims]
    assert s.run(swapped).ok
    both = s.run([*swapped, replace(loc, id="d-99")])
    assert kinds(both) == [("redundant", "axis", "x")]
    # the extreme needs the radius: without the diameter neither is known
    dia = next(d for d in s.dims if d.kind == "diameter")
    report = s.run([d for d in swapped if d.id != dia.id])
    assert sorted(kinds(report)) == sorted([("missing", "axis", "x"), ("missing", "radius", None)])


def test_the_slots_walls_follow_their_ends_and_their_width():
    s = step_slot()
    width = find(s, "y", 24 * MM, 16 * MM)
    report = s.run(s.without(width.id))
    assert sorted(kinds(report)) == sorted(
        [("missing", "plane", "y")] * 2 + [("missing", "radius", None)] * 2
    )
    report = s.run(s.changed(width.id, value=8 * MM + OFF))
    assert sorted(kinds(report)) == sorted([("wrong", "plane", "y")] * 2 + [("wrong", "radius", None)] * 2)


def test_chamfers_are_sized_by_leg_once_with_nx():
    s = step_slot()
    chamfer = next(d for d in s.dims if d.kind == "chamfer")
    assert kinds(s.run(s.without(chamfer.id))) == [("missing", "leg", a) for a in "xxxxxyyyyy"]
    assert kinds(s.run(s.changed(chamfer.id, value=3 * MM + OFF))) == [
        ("wrong", "leg", a) for a in "xxxxxyyyyy"
    ]
    (f,) = s.run(s.changed(chamfer.id, prefix="4X")).findings
    assert (f.kind, f.what) == ("wrong", "count")
    # one leg along an axis states that leg only
    report = s.run(s.changed(chamfer.id, axis="x"))
    assert kinds(report) == [("missing", "leg", "y")] * 5


# --------------------------------------------------------------------------- coplanar, coaxial, symmetric


def test_faces_in_line_are_one_position_unless_the_convention_is_off():
    s = pocket_tab()
    assert s.run().ok
    report = s.run(conventions=Conventions(coplanar=False))
    (f,) = report.findings
    assert (f.kind, f.what, f.axis, f.faces) == ("missing", "plane", "y", s.features["f-right"])
    # an extension line to each face joins them again
    height = find(s, "y", 20 * MM, 0.0)
    both = replace(height, positions=(height.positions[0], at("y", 20 * MM, "f-base", "f-right")))
    assert s.run(
        [both if d.id == height.id else d for d in s.dims], conventions=Conventions(coplanar=False)
    ).ok


def test_round_faces_on_one_axis_are_coaxial_unless_the_convention_is_off():
    s = boss()
    report = s.run(conventions=Conventions(coaxial=False))
    assert kinds(report) == [("missing", "axis", "x"), ("missing", "axis", "y")]
    assert all(f.faces == s.features["f-hole"] for f in report.findings)


def test_a_boss_drawn_symmetric_needs_no_location_and_a_location_besides_is_redundant():
    s = boss()
    xloc, yloc = find(s, "x", 30 * MM), find(s, "y", 30 * MM)
    centred = [
        Coincident("x", (mid(30 * MM, 0.0, "f-env-x"), mid(30 * MM, 15 * MM, "f-boss")), "c-1"),
        Coincident("y", (mid(30 * MM, 0.0, "f-env-y"), mid(30 * MM, 15 * MM, "f-boss")), "c-2"),
    ]
    unlocated = s.without(xloc.id, yloc.id)
    assert kinds(s.run(unlocated)) == [("missing", "axis", "x"), ("missing", "axis", "y")]
    assert s.run(unlocated, coincident=centred).ok
    report = s.run(coincident=centred)
    assert kinds(report) == [("redundant", "axis", "x"), ("redundant", "axis", "y")]
    assert "c-1" in report.findings[0].dimensions and xloc.id in report.findings[0].dimensions
    # a centre line through features that are not in line breaks the relation
    off = [
        Coincident(
            "x", (mid(30 * MM, 0.0, "f-env-x"), mid(30 * MM, 15 * MM, "f-boss"), at("x", 0.0, "f-env-x"))
        )
    ]
    report = s.run(unlocated + [xloc], coincident=off)
    assert ("wrong", "relation", None) in kinds(report)


def test_one_position_naming_several_holes_puts_them_on_one_centre_line():
    s = hole_kinds()
    ids = [f"f-{n}" for n, (_x, y) in HOLE_KINDS.items() if y == 20]
    across = [
        d
        for d in s.dims
        if d.axis == "y" and abs(d.positions[1].value - 20 * MM) < 1e-9 and d.positions[0].value == 0.0
    ]
    assert len(across) == 5
    one = replace(across[0], positions=(across[0].positions[0], mid(20 * MM, 3.3 * MM, *ids)))
    dims = [one if d.id == across[0].id else d for d in s.dims if d not in across[1:]]
    assert s.run(dims).ok


# --------------------------------------------------------------------------- what counts and how


def test_ordinate_and_basic_dimensions_count_like_toleranced_ones():
    s = four_holes()
    ordinate = [replace(d, kind="ordinate") if d.kind == "linear" else d for d in s.dims]
    assert s.run(ordinate).ok
    basic = [replace(d, tolerance="basic") if d.kind == "linear" else d for d in s.dims]
    assert s.run(basic).ok
    close = replace(CASES["four_holes"][2](s), tolerance="basic")
    assert kinds(s.run([*basic, close])) == [("redundant", "axis", "x")]


def test_a_leader_note_states_a_diameter_or_with_r_a_radius_or_a_depth():
    s = boss()
    dia = next(d for d in s.dims if d.kind == "diameter")
    assert s.run(s.changed(dia.id, kind="leader_note", prefix="\u00d8")).ok
    assert s.run(s.changed(dia.id, kind="leader_note", prefix="R", value=15 * MM)).ok
    (f,) = s.run(s.changed(dia.id, kind="leader_note", prefix="R")).findings  # 30 as a radius
    assert (f.kind, f.what) == ("wrong", "radius")
    k = hole_kinds()
    depth = find(k, "z", 8 * MM, 20 * MM)
    assert k.run(k.changed(depth.id, kind="leader_note")).ok
    # nX on a callout's depth line counts holes; only a linear dimension's nX is a pitch
    assert k.run(k.changed(depth.id, prefix="1X")).ok


def test_removed_dimensions_and_datum_symbols_are_not_read():
    s = four_holes()
    loc = find(s, "x", 71 * MM)
    report = s.run(s.changed(loc.id, state="removed"))
    assert kinds(report) == [("missing", "axis", "x")] and report.dimensions == len(s.dims) - 1
    symbol = s.extra(kind="datum_feature", value=0.0, features=("f-env-x",))
    box = s.extra(kind="frame", value=0.0, features=("f-holes",))
    report = s.run(s.plus(symbol, box))
    assert report.ok and report.dimensions == len(s.dims)


def test_what_cannot_be_attached_is_unresolved():
    s = four_holes()
    loc = find(s, "x", 71 * MM)

    def swap(position):
        return [replace(d, positions=(d.positions[0], position)) if d.id == loc.id else d for d in s.dims]

    report = s.run(swap(mid(70 * MM, 3.3 * MM, "f-holes")))
    assert sorted(kinds(report)) == [("missing", "axis", "x"), ("unresolved", "dimension", "x")]
    assert "no axis or centre plane at 70.0000 mm along x" in report.of_kind("unresolved")[0].words
    report = s.run(swap(mid(71 * MM, 3.3 * MM, "f-nothing")))
    assert "f-nothing" in report.of_kind("unresolved")[0].words
    report = s.run(swap(Position(math.nan, True, 0.0, ("f-holes",))))
    assert len(report.of_kind("unresolved")) == 1
    odd = [
        s.extra(kind="diameter", value=5 * MM, features=("f-env-x",), radius=2.5 * MM),  # nothing round
        s.extra(kind="linear", value=10 * MM, axis="x"),  # no positions
        s.extra(kind="diameter", value=5 * MM),  # names nothing
        s.extra(kind="linear", value=-1.0, axis="x", positions=loc.positions),  # a negative value
        s.extra(kind="angle", value=1.0, features=("f-holes",)),  # no countersink
        s.extra(kind="angle", value=1.0, features=("f-holes",), axis="x"),  # no pitch circle
        s.extra(kind="chamfer", value=1.0, features=("f-holes",)),  # no chamfer
        s.extra_lin("w", at("x", 0.0), at("x", 0.1)),  # no such axis
        s.extra_lin("x", at("x", 0.0, "f-env-x"), at("x", 0.0, "f-env-x")),  # one position twice
    ]
    report = s.run(s.plus(*odd))
    unresolved = report.of_kind("unresolved")
    assert len(unresolved) == len(odd) and {f.dimensions[0] for f in unresolved} == {d.id for d in odd}
    assert len(report.findings) == len(odd)
    bad = Coincident("x", (mid(12 * MM, 0.0, "f-holes"),))
    assert kinds(s.run(coincident=[bad])) == [("unresolved", "relation", "x")]


def rename(dims, names: dict[str, str]):
    def pos(p):
        return replace(p, features=tuple(names.get(f, f) for f in p.features))

    return [
        replace(
            d,
            features=tuple(names.get(f, f) for f in d.features),
            positions=tuple(pos(p) for p in d.positions),
        )
        for d in dims
    ]


def test_a_feature_set_gives_its_features_ids_in_recognition_order():
    s = four_holes()
    m = s.model
    walls = [Width(s.features[f"f-env-{a}"], Descriptor("width"), axis=a, role="envelope") for a in "xyz"]
    spots = ((12, 10), (37, 48), (71, 15), (88, 44))
    holes = [Hole(hole(m, x * MM, y * MM), Descriptor("hole")) for x, y in spots]
    group = Pattern((), Descriptor("pattern"), members=(3, 4, 5, 6))  # its members' faces are its own
    fs = FeatureSet(features=(*walls, *holes, group))
    dims = rename(s.dims, {"f-env-x": "f-1", "f-env-y": "f-2", "f-env-z": "f-3", "f-holes": "f-8"})
    assert reconstruct(m, s.frame, dims, features=fs).ok


def test_without_a_feature_table_positions_are_matched_by_value():
    s = four_holes()
    assert s.run(features=None).ok
    # sizes match by radius alone; an angle or a chamfer needs the feature it belongs to
    k = hole_kinds()
    report = k.run(features=None)
    unresolved = report.of_kind("unresolved")
    assert {d.kind for d in k.dims if d.id in {f.dimensions[0] for f in unresolved}} == {"angle"}


def flipped(s: Sheet, axis: str):
    """The sheet in a frame whose ``axis`` runs the other way: positions negate."""
    k = AXES.index(axis)
    dirs = [list(v) for v in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    dirs[k][k] = -1.0
    out = []
    for d in s.dims:
        if d.axis == axis:
            d = replace(d, positions=tuple(replace(p, value=-p.value) for p in d.positions))
        out.append(d)
    return Frame(directions=tuple(tuple(v) for v in dirs), datums=s.frame.datums), out


def test_the_frame_may_run_the_model_axes_in_another_order_or_sense():
    s = four_holes()
    turned = Frame(directions=((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)), datums=s.frame.datums)
    relabel = {"x": "z", "y": "x", "z": "y"}
    dims = [replace(d, axis=relabel[d.axis]) if d.axis else d for d in s.dims]
    assert reconstruct(s.model, turned, dims, features=s.features).ok
    for name, axis in (("four_holes", "x"), ("patterns", "y"), ("step_slot", "x")):
        sheet = DRAWN[name][0]()
        frame_, dims = flipped(sheet, axis)
        assert reconstruct(sheet.model, frame_, dims, features=sheet.features).ok, name


def test_an_origin_can_be_given_where_the_frame_has_none():
    s = link()
    end1 = next(f for f in rounds(s.model, 105 * MM, 15 * MM) if s.model.faces[f].surface.concave)
    s.frame = Frame(datums=s.frame.datums[:2])
    report = s.run(conventions=Conventions(origins=(("x", end1),)))
    assert report.ok and dict(report.origins)["x"].startswith("the origin given for x")


@pytest.mark.parametrize("name", sorted(P.PARTS))
def test_every_synthetic_part_runs_and_says_what_it_leaves_out(name):
    report = reconstruct(model(name), Frame(), [])
    assert report.recovered == len(report.origins) == 3
    assert {f.kind for f in report.findings} == {"missing"}
    assert len(report.findings) == report.targets - 3
    reasons = {r for _f, r in report.uncovered}
    expected = {
        # the inclined hole's floor; the 45 degree face itself is judged
        "inclined_hole": {"an axis on no frame direction", "angled face"},
    }.get(name, set())
    assert reasons == expected


def test_an_angled_face_needs_its_angle_and_one_of_its_meet_lines_located():
    """Conventions 2: the 30 degree face of angled_round, stated by its angle and by a
    line it meets a principal face on. Past the R5 at the top that line is a virtual
    sharp at X 55; at the right face, a sharp edge at Y 15.566."""
    m = model("angled_round")
    (face,) = [f.index for f in m.faces if f.kind == "plane" and min(f.surface.normal[:2]) > 0.4]
    s = Sheet(
        m, datums(m), {"f-cut": (face,), "f-env-x": planes(m, "x", 0.0), "f-env-y": planes(m, "y", 0.0)}
    )

    def about(dims):
        return sorted((f.kind, f.what) for f in s.run(dims).findings if face in f.faces)

    assert about([]) == [("missing", "angle"), ("missing", "sharp")]
    angle = s.extra(kind="angle", value=math.radians(30.0), features=("f-cut",), tolerance="basic")
    x55 = s.extra_lin("x", at("x", 0.0, "f-env-x"), mid(55 * MM, 0.0, "f-cut"))
    assert about([angle, x55]) == []
    y = 30 * MM - (80 - 55) * MM * math.tan(math.radians(30.0))
    assert about([angle, s.extra_lin("y", at("y", 0.0, "f-env-y"), mid(y, 0.0, "f-cut"))]) == []
    assert about([angle]) == [("missing", "sharp")]
    assert about([x55]) == [("missing", "angle")]
    assert about([replace(angle, value=math.radians(31.0)), x55]) == [("wrong", "angle")]
    assert about([angle, angle, x55]) == [("redundant", "angle")]
    assert about([angle, replace(x55, value=55 * MM + OFF)]) == [("wrong", "sharp")]


def test_a_fillet_note_states_the_rounds_no_dimension_sizes():
    """Rule 14: a 60 x 40 x 10 mm plate whose corner at (60, 40) is rounded R5, the round
    stated by a fillet note and placed by its tangency to the two faces it joins; a
    note of another radius states nothing."""
    pts = [(0.0, 0.0), (60 * MM, 0.0), (60 * MM, 40 * MM), (0.0, 40 * MM)]
    xt, _truth = P.build(P.prism(P.rounded(pts, [0, 0, 5 * MM, 0]), 10 * MM))
    m = facegraph.from_transmit(xt, name="rounded_corner")
    (rnd,) = [f.index for f in m.faces if f.kind == "cylinder"]
    s = Sheet(m, datums(m), box_features(m, 60 * MM, 40 * MM, 10 * MM))
    envelope(s, 60 * MM, 40 * MM, 10 * MM)

    def about(**kw):
        return sorted({(f.kind, f.what) for f in s.run(**kw).findings if rnd in f.faces})

    assert about() == [("missing", "axis"), ("missing", "radius")]
    assert about(fillet_radius=5 * MM) == []
    assert s.run(fillet_radius=5 * MM).ok
    assert about(fillet_radius=4 * MM) == [("missing", "axis"), ("missing", "radius")]
    with pytest.raises(InvalidArgumentError):
        s.run(fillet_radius=float("nan"))


@pytest.mark.parametrize("name", sorted(DRAWN))
def test_the_report_is_the_same_every_time_and_whatever_the_order(name):
    s = DRAWN[name][0]()
    first = s.run()
    assert s.run() == first
    assert s.run(list(reversed(s.dims))).counts() == first.counts()
    gone = s.run(s.dims[1:])
    assert s.run(s.dims[1:]) == gone


def test_counts_only_is_what_the_corpus_sweep_prints():
    s = patterns()
    angle = next(d for d in s.dims if d.kind == "angle")
    report = s.run(s.without(angle.id))
    counts = report.counts()
    assert list(counts) == [
        "targets",
        "recovered",
        "missing",
        "redundant",
        "wrong",
        "unresolved",
        "uncovered",
        "dimensions",
    ]
    assert all(isinstance(v, int) for v in counts.values())
    assert report.summary() == (
        "targets 61, recovered 48, missing 13, redundant 0, wrong 0, unresolved 0, uncovered 0, dimensions 17"
    )


# --------------------------------------------------------------------------- arguments and bounds


@pytest.mark.parametrize(
    "change, parameter",
    [
        ({"model": "part"}, "model"),
        ({"frame": None}, "frame"),
        ({"frame": Frame(directions=((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 0.0, 1.0)))}, "frame"),
        ({"frame": Frame(directions=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))}, "frame"),
        ({"frame": Frame(directions=((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))}, "frame"),
        ({"frame": Frame(datums=(Datum("A", 999, "none"),))}, "frame"),
        ({"dimensions": "d-1"}, "dimensions"),
        ({"dimensions": [1, 2]}, "dimensions"),
        ({"conventions": None}, "conventions"),
        ({"conventions": Conventions(origins=(("x", 999),))}, "conventions"),
        ({"features": 42}, "features"),
        ({"features": {"f-1": (999,)}}, "features"),
        ({"features": {"f-1": "abc"}}, "features"),
        ({"coincident": [1]}, "coincident"),
        ({"coincident": "c"}, "coincident"),
        ({"limits": "small"}, "limits"),
    ],
)
def test_bad_arguments_name_the_parameter(change, parameter):
    s = four_holes()
    kw = {"model": s.model, "frame": s.frame, "dimensions": s.dims, "features": s.features, **change}
    with pytest.raises(InvalidArgumentError) as err:
        reconstruct(
            kw.pop("model"), kw.pop("frame"), kw.pop("dimensions"), kw.pop("conventions", Conventions()), **kw
        )
    assert err.value.detail == {"parameter": parameter}


@pytest.mark.parametrize(
    "kw, parameter",
    [
        ({"share": 0}, "share"),
        ({"share": 2.0}, "share"),
        ({"angle_tolerance": True}, "angle_tolerance"),
        ({"coplanar": 1}, "coplanar"),
        ({"origins": (("w", 1),)}, "origins"),
        ({"origins": (("x", True),)}, "origins"),
    ],
)
def test_conventions_are_checked_when_made(kw, parameter):
    with pytest.raises(InvalidArgumentError) as err:
        Conventions(**kw)
    assert err.value.detail == {"parameter": parameter}


def test_the_oracle_is_bounded():
    s = four_holes()
    with pytest.raises(SldLimitError) as err:
        s.run(limits=DrawingLimits(dimensions=5))
    assert err.value.detail["limit"] == "dimensions"
    with pytest.raises(SldLimitError) as err:
        s.run(limits=DrawingLimits(requirements=10))
    assert err.value.detail["limit"] == "requirements"


def test_the_elimination_has_a_fixed_budget(monkeypatch):
    import drawing_reconstruct

    monkeypatch.setattr(drawing_reconstruct, "_WORK", 10)
    with pytest.raises(SldLimitError) as err:
        patterns().run()
    assert err.value.detail["limit"] == "requirements"
