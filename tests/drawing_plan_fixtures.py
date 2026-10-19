"""Hand-made inputs for the planner and layout tests (docs/DRAWINGS.md 3.2 step 5:
``dwg-plan`` tests on hand-made feature sets and views, so they need neither
``dwg-features`` nor ``dwg-views``).

For a plate from ``drawing_parts`` (a box with holes along -Z from its top) this
builds the feature set from the part's ground truth, and four views by hand: each
view's outline is the box's projection, the holes are circles where they are seen
end on with their centre marks, and centre lines where they are seen side on.
"""

from __future__ import annotations

import math

from drawing_support import model, part
from solidseas.drawing import display as D
from solidseas.drawing.facegraph import Plane
from solidseas.drawing.settings import DrawingSettings
from solidseas.drawing.types import (
    STANDARD_VIEWS,
    Axis,
    Coverage,
    Datum,
    Descriptor,
    DrawingOptions,
    FeatureSet,
    Frame,
    Hole,
    HoleSegment,
    Pattern,
    Run,
    Source,
    Unclaimed,
    ViewGeometry,
    ViewSpec,
    Width,
    Witness,
)

MM = 1e-3
AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _face(m, normal, offset):
    for f in m.faces:
        s = f.surface
        if isinstance(s, Plane) and max(abs(a - b) for a, b in zip(s.normal, normal, strict=True)) < 1e-9:
            if abs(sum(s.origin[k] * abs(normal[k]) for k in range(3)) - offset) < 1e-9:
                return f.index
    raise LookupError(f"no face {normal} at {offset}")


def _inside_hole(f, at, r) -> bool:
    """Whether a face lies within a hole's widest radius of its axis (in plan)."""
    (a, b) = f.box
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    reach = max(b[0] - a[0], b[1] - a[1]) / 2
    return math.hypot(cx - at[0], cy - at[1]) < 1e-6 and reach <= r + 1e-6


def _on_box(f, lo, hi) -> bool:
    s = f.surface
    if not isinstance(s, Plane):
        return False
    return any(
        abs(abs(s.normal[k]) - 1) < 1e-9 and min(abs(s.origin[k] - lo[k]), abs(s.origin[k] - hi[k])) < 1e-9
        for k in range(3)
    )


def _segments(h: dict) -> tuple[HoleSegment, ...]:
    out = []
    for s in h["stack"]:
        if s[0] in ("cbore", "bore", "step"):
            depth = s[2] if len(s) > 2 and s[2] is not None else 0.0
            out.append(HoleSegment("cylinder", s[1], s[1], depth or 0.0))
            if s[0] == "cbore":
                out.append(HoleSegment("annulus", s[1], 0.0))
        elif s[0] == "csk":
            out.append(HoleSegment("cone", s[1], 0.0, 0.0, math.radians(s[2])))
    return tuple(out)


def plate_features(
    name, *, patterns: list[tuple[str, list[int]]] | None = None, unclaimed: int = 0
) -> FeatureSet:
    """The feature set of a plate part, from its truth: its holes, the patterns named
    (kind and member hole indices), the three envelope widths and datums A, B, C on
    the bottom, front and left faces. ``name`` is a part of ``drawing_parts.PARTS`` or
    a (model, truth) pair."""
    m, truth = _resolve(name)
    (lo, hi) = truth["box"]
    feats: list = []
    for h in truth["holes"]:
        d = tuple(float(c) for c in h["axis"])
        through = h["end"] == "thru"
        depth = (hi[2] - lo[2]) if through else h["depth"]
        kind = h["kind"] if h["kind"] in ("counterbore", "spotface", "countersink", "stepped") else "simple"
        widest = max(st[1] for st in h["stack"] if len(st) > 1 and isinstance(st[1], float)) / 2
        own = tuple(f.index for f in m.faces if _inside_hole(f, h["at"], widest) and not _on_box(f, lo, hi))
        feats.append(
            Hole(
                own,
                Descriptor("hole"),
                axis=Axis(tuple(h["at"]), d),
                segments=_segments(h),
                kind=kind,
                ends=("open", "open") if through else ("open", "blind"),
                depth=depth,
            )
        )
    for kind, members in patterns or ():
        first = feats[members[0]]
        extra = {}
        if kind == "circular":
            pts = [feats[k].axis.point for k in members]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            r = math.hypot(pts[0][0] - cx, pts[0][1] - cy)
            extra = {
                "centre": (cx, cy, first.axis.point[2]),
                "pitch_diameter": 2 * r,
                "step": 2 * math.pi / len(members),
                "first_angle": math.atan2(pts[0][1] - cy, pts[0][0] - cx) % (2 * math.pi / len(members)),
            }
        feats.append(
            Pattern(
                (), Descriptor("pattern"), kind=kind, members=tuple(members), counts=(len(members),), **extra
            )
        )
    datums = []
    for k, ax in enumerate("xyz"):
        n_lo = tuple(-c for c in AXES[ax])
        a = _face(m, n_lo, lo[k])
        b = _face(m, AXES[ax], hi[k])
        feats.append(
            Width(
                (a, b),
                Descriptor("width"),
                pair=(a, b),
                axis=ax,
                role="envelope",
                size=hi[k] - lo[k],
                overlap=1.0,
            )
        )
    datums = [
        Datum("A", _face(m, (0.0, 0.0, -1.0), lo[2]), "the largest planar face"),
        Datum("B", _face(m, (0.0, -1.0, 0.0), lo[1]), "the largest planar face square to datum A"),
        Datum("C", _face(m, (-1.0, 0.0, 0.0), lo[0]), "the largest planar face square to datums A and B"),
    ]
    frame = Frame(datums=tuple(datums), extents=tuple((lo[k], hi[k]) for k in range(3)))
    left = tuple(Unclaimed(f, 1e-6, "free_form") for f in range(unclaimed))
    cov = Coverage(len(feats), len(left), len(m.faces), len(m.faces) - len(left), 1.0, 1.0)
    return FeatureSet(tuple(feats), frame, (), left, cov)


def _spec(vid: str, name: str) -> ViewSpec:
    d, up = STANDARD_VIEWS[name]
    kind = {"front": "base", "isometric": "isometric"}.get(name, "projected")
    return ViewSpec(vid, kind, d, up, name, None if kind == "base" else "v-1", hidden=False)


def _resolve(name):
    if isinstance(name, str):
        return model(name), part(name)[1]
    return name


def plate_views(name, fs: FeatureSet, names=("front", "top", "right", "isometric")):
    """Hand-made views of a plate: the box's outline, holes seen end on as circles with
    centre marks, holes seen side on as centre lines."""
    _m, truth = _resolve(name)
    (lo, hi) = truth["box"]
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    out = []
    for k, vname in enumerate(names, 1):
        spec = _spec(f"v-{k}", vname)
        _r, _u, d = spec.frame()
        pts = [spec.project(c) for c in corners]
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        src = Source(0, "edge", "outline", spec.id)
        segs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        runs = [
            Run(D.Segment(a, b, "visible", D.Src(0, "outline", spec.id)), "visible", src) for a, b in segs
        ]
        marks, lines = [], []
        if vname != "isometric":
            for f in fs.features:
                if not isinstance(f, Hole):
                    continue
                c = spec.project(f.axis.point)
                dot = sum(a * b for a, b in zip(f.axis.direction, d, strict=True))
                if abs(abs(dot) - 1.0) < 1e-9:
                    radii = sorted(
                        {s.diameter / 2 for s in f.segments if s.kind == "cylinder"} | {f.diameter / 2}
                    )
                    for r in radii:
                        runs.append(
                            Run(
                                D.Arc(c, r, 0.0, 360.0, "visible", D.Src(0, "hole", spec.id)),
                                "visible",
                                Source(0, "edge", "hole", spec.id),
                            )
                        )
                    marks.append((c, radii[-1]))
                elif abs(dot) < 1e-9:
                    far = tuple(f.axis.point[i] + f.axis.direction[i] * f.depth for i in range(3))
                    lines.append((c, spec.project(far)))
        wit = []
        for a, b in segs:
            if abs(a[0] - b[0]) < 1e-12:
                wit.append(Witness("x", a[0], min(a[1], b[1]), max(a[1], b[1]), src))
            else:
                wit.append(Witness("y", a[1], min(a[0], b[0]), max(a[0], b[0]), src))
        geom = ViewGeometry(spec.id, tuple(runs), tuple(marks), tuple(lines), witnesses=tuple(wit))
        out.append((spec, geom))
    return tuple(out)


def plate(
    name,
    *,
    patterns=None,
    unclaimed: int = 0,
    options: DrawingOptions | None = None,
    settings=None,
    unit="mm",
):
    """(context arguments) for a plate: the model, features, views, options, settings."""
    from solidseas.drawing.plan import Context

    fs = plate_features(name, patterns=patterns, unclaimed=unclaimed)
    views = plate_views(name, fs)
    o = options or DrawingOptions()
    s = settings or DrawingSettings()
    return Context(_resolve(name)[0], fs, views, o, s, unit=unit)


PATTERNS = [
    ("linear", [0, 1, 2, 3, 4]),
    ("grid", [5, 6, 7, 8, 9, 10]),
    ("circular", [12, 13, 14, 15, 16, 17]),
]
