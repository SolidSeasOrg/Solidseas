"""Turned (lathe) parts: what makes a part one, and its profile along the axis
(``docs/DRAWINGS.md`` 10.5 and 10.6; stage 2's ``dwg-turned``).

:func:`turned_profile` reads the faces alone. The axis is the one whose faces of
revolution (cylinders, cones and tori by their axis lines, spheres by their centres)
hold the most area, and it lies along a frame axis. A part is **turned** when every
face of revolution lies on that axis and every plane is square to it (the "looks
turned" rule of 10.6, which 6.9 % of sampled corpus parts meet, measured), and
**mixed** when the faces on the axis and the planes square to it hold at least
:data:`MIXED_SHARE` of its area and other faces remain: flats, holes across the axis
and keyseats, which the machined rules draw. A part needs an outside or inside
cylinder on the axis to have a profile; anything else has none.

The profile orders the faces of revolution along the axis from the **larger end**:
the end whose nearest outside cylinder is the larger, else the end with the larger
planar end face, else the low end of the frame axis. Its default datums are those of
10.5: A on the longest outside cylindrical segment (a bore's when the part has no
outside cylinder), B on the planar end face at the larger end.

:func:`for_process` gives a feature set those datums when the drawing is of a turned
part, in place of the planar datums of 9, which every other drawing keeps.
"""

from __future__ import annotations

import math
from dataclasses import replace

from ..facegraph import BrepModel, Cone, Cylinder, Plane, Sphere, Torus
from ..types import Axis, Datum, FeatureSet, Frame, TurnedProfile, TurnedSegment
from ._common import AXIS_NAMES, SQUARE_TOL, Vec3, along, cross, dot, extent, norm, sub

MIXED_SHARE = 0.8  # of the area on the axis and the planes square to it (10.6: 6.4 % of parts)
DATUM_A_REASON = "the longest cylindrical segment"
DATUM_A_BORE_REASON = "the longest bore (the part has no outside cylinder)"
DATUM_B_REASON = "the end face at the larger end"
TURNED_REASON = "every face is a face of revolution about one axis or a plane square to it"


def _distance_to_line(p: Vec3, point: Vec3, direction: Vec3) -> float:
    return norm(cross(sub(p, point), direction))


def _radius_at(cone: Cone, p: Vec3) -> float:
    """A cone's radius at the plane through ``p`` square to its axis."""
    return cone.radius + math.tan(cone.half_angle) * dot(sub(p, cone.point), cone.axis)


def turned_profile(model: BrepModel, frame: Frame) -> TurnedProfile | None:
    """The part's :class:`~solidseas.drawing.types.TurnedProfile` when it is turned or
    mixed (see the module notes), else None."""
    faces = model.faces
    total = sum(f.area for f in faces)
    if not faces or total <= 0.0 or not model.axis_groups:
        return None

    def group_area(g) -> float:
        return sum(faces[i].area for i in g.faces)

    best = max(model.axis_groups, key=lambda g: (group_area(g), -min(g.faces)))
    hit = along(best.direction, frame.directions)
    if hit is None:
        return None  # an axis no frame axis runs along: drawn by the machined rules
    frame_axis = hit[0]
    k = AXIS_NAMES.index(frame_axis)
    d = frame.directions[k]
    tol = max(model.tolerance * 10.0, 1e-9)
    on_axis = set(best.faces)
    for f in faces:
        if isinstance(f.surface, Sphere) and _distance_to_line(f.surface.centre, best.point, d) <= tol:
            on_axis.add(f.index)
    cylinders = sorted(i for i in on_axis if isinstance(faces[i].surface, Cylinder))
    if not cylinders:
        return None
    square = {
        f.index
        for f in faces
        if isinstance(f.surface, Plane) and abs(abs(dot(f.surface.normal, d)) - 1.0) <= SQUARE_TOL
    }
    others = [f.index for f in faces if f.index not in on_axis and f.index not in square]
    share = sum(faces[i].area for i in on_axis | square) / total
    if others and share < MIXED_SHARE:
        return None

    spans = {i: extent(model, faces[i], d) for i in on_axis | square}
    if len(frame.extents) == 3:
        low, high = frame.extents[k]
    else:
        low = min(a for a, _b in spans.values())
        high = max(b for _a, b in spans.values())
    outside = [i for i in cylinders if not faces[i].surface.concave] or cylinders

    def nearest(at_low: bool) -> float:
        """The radius of the cylinder nearest one end (the larger first, at a tie)."""
        gaps = []
        for i in outside:
            a, b = spans[i]
            gaps.append((round((a - low if at_low else high - b) / tol), -faces[i].surface.radius))
        return -min(gaps)[1]

    def end_face(at: float) -> int | None:
        hits = [i for i in square if abs(dot(faces[i].surface.origin, d) - at) <= tol]
        return max(hits, key=lambda i: (faces[i].area, -i)) if hits else None

    ends = {True: end_face(low), False: end_face(high)}
    r_low, r_high = nearest(True), nearest(False)
    if abs(r_low - r_high) > tol:
        low_is_larger = r_low > r_high
    else:
        a_low = faces[ends[True]].area if ends[True] is not None else 0.0
        a_high = faces[ends[False]].area if ends[False] is not None else 0.0
        low_is_larger = a_low >= a_high - 1e-12
    sign = 1.0 if low_is_larger else -1.0
    start_at = low if low_is_larger else high
    direction = (d[0] * sign, d[1] * sign, d[2] * sign)
    t0 = dot(best.point, d)
    origin = tuple(best.point[j] + d[j] * (start_at - t0) for j in range(3))

    def from_end(t: float) -> float:
        return (t - start_at) * sign

    segments: list[TurnedSegment] = []
    for i in sorted(on_axis):
        f = faces[i]
        s = f.surface
        a, b = sorted((from_end(spans[i][0]), from_end(spans[i][1])))
        if isinstance(s, Cylinder):
            segments.append(TurnedSegment((i,), "cylinder", a, b, 2.0 * s.radius, 2.0 * s.radius, s.concave))
        elif isinstance(s, Cone):
            pa = tuple(origin[j] + direction[j] * a for j in range(3))
            pb = tuple(origin[j] + direction[j] * b for j in range(3))
            segments.append(
                TurnedSegment(
                    (i,), "cone", a, b, 2.0 * abs(_radius_at(s, pa)), 2.0 * abs(_radius_at(s, pb)), s.concave
                )
            )
        elif isinstance(s, Torus):
            segments.append(TurnedSegment((i,), "torus", a, b, 2.0 * s.major, 2.0 * s.major))
        elif isinstance(s, Sphere):
            segments.append(TurnedSegment((i,), "sphere", a, b, 2.0 * s.radius, 2.0 * s.radius))
    segments = _merged(segments, tol)
    segments.sort(key=lambda g: (g.internal, g.start, g.end, g.diameter, g.faces))

    rounds = [g for g in segments if g.kind == "cylinder" and not g.internal]
    rounds = rounds or [g for g in segments if g.kind == "cylinder"]
    datum = max(rounds, key=lambda g: (round(g.length / tol), round(g.diameter / tol), -g.start))
    if others:
        reason = (
            f"{100.0 * share:.0f} % of its area turns about one axis; the rest (flats, holes across the "
            "axis and the like) is drawn by the machined rules"
        )
    else:
        reason = TURNED_REASON
    near, far = (ends[True], ends[False]) if low_is_larger else (ends[False], ends[True])
    return TurnedProfile(
        axis=Axis(origin, direction),
        frame_axis=frame_axis,
        segments=tuple(segments),
        length=high - low,
        ends=(near, far),
        datum_a=min(datum.faces),
        datum_b=near,
        mixed=bool(others),
        share=share,
        reason=reason,
    )


def _merged(segments: list[TurnedSegment], tol: float) -> list[TurnedSegment]:
    """Cylinder faces of one diameter, inside or out, whose extents meet or overlap, as
    one segment: a cylinder a reader split into halves, or two faces of one turned
    diameter."""
    out: list[TurnedSegment] = []
    cyl = sorted(
        (g for g in segments if g.kind == "cylinder"), key=lambda g: (g.internal, g.diameter, g.start)
    )
    for g in cyl:
        last = out[-1] if out else None
        if (
            last is not None
            and last.kind == "cylinder"
            and last.internal == g.internal
            and abs(last.diameter - g.diameter) <= 2.0 * tol
            and g.start <= last.end + tol
        ):
            out[-1] = replace(last, faces=tuple(sorted(last.faces + g.faces)), end=max(last.end, g.end))
        else:
            out.append(g)
    return out + [g for g in segments if g.kind != "cylinder"]


def datums_of(profile: TurnedProfile) -> tuple[Datum, ...]:
    """A turned part's default datums (10.5): A on the datum cylinder, B on the end face
    at the larger end when it is a plane."""
    seg = profile.cylinder_of(profile.datum_a)
    why = DATUM_A_BORE_REASON if seg is not None and seg.internal else DATUM_A_REASON
    out = [Datum("A", profile.datum_a, why)]
    if profile.datum_b is not None:
        out.append(Datum("B", profile.datum_b, DATUM_B_REASON))
    return tuple(out)


def for_process(features, process: str):
    """The feature set a drawing of ``process`` plans from. A turned part's (one with a
    profile) gets the datums of :func:`datums_of` in place of the planar ones, and a
    boss on its axis that spans separate cylindrical segments (two Ø16 lengths either
    side of a groove, which recognition takes as one boss of their diameter) becomes a
    boss a segment, so each segment's diameter is stated where it is (10.6). Anything
    else is returned as it is."""
    if process != "turned" or not isinstance(features, FeatureSet) or features.turned is None:
        return features
    features = _bosses_by_segment(features)
    return replace(features, frame=replace(features.frame, datums=datums_of(features.turned)))


def _bosses_by_segment(fs: FeatureSet) -> FeatureSet:
    """``fs`` with each boss on the turned axis that claims faces of several outside
    cylindrical segments split into a boss a segment, in place, and every index that
    names a later feature (pattern members, depths, model-defined and lettering sets)
    moved along. A split boss's descriptor holds its whole position, its place along
    the axis included, so the segments stay apart when a drawing is matched to a new
    version of the part."""
    from .. import keys
    from ..types import Boss, Pattern
    from .holes import _axis_word

    t = fs.turned
    out: list = []
    moved: dict[int, int] = {}
    split = False
    for k, f in enumerate(fs.features):
        moved[k] = len(out)
        segs = []
        if isinstance(f, Boss):
            segs = [
                s
                for s in t.segments
                if s.kind == "cylinder" and not s.internal and set(s.faces) & set(f.faces)
            ]
        if len(segs) < 2:
            out.append(f)
            continue
        split = True
        for s in segs:
            mid = (s.start + s.end) / 2.0
            centre = tuple(t.axis.point[j] + t.axis.direction[j] * mid for j in range(3))
            lows = [lo for lo, _hi in fs.frame.extents] if len(fs.frame.extents) == 3 else [0.0, 0.0, 0.0]
            position = tuple(dot(centre, d) - lo for d, lo in zip(fs.frame.directions, lows, strict=True))
            d = keys.descriptor(
                "Boss",
                {"diameter": s.diameter, "length": s.length},
                {"axis": _axis_word(f.axis.direction, fs.frame)},
                position,
            )
            out.append(Boss(tuple(s.faces), d, f.exact, Axis(centre, f.axis.direction), s.diameter, s.length))
    if not split:
        return fs
    features = []
    for f in out:
        if isinstance(f, Pattern):
            f = replace(f, members=tuple(moved[m] for m in f.members))
        features.append(f)
    depths = tuple(replace(d, feature=moved.get(d.feature, d.feature)) for d in fs.depths)
    return replace(
        fs,
        features=tuple(features),
        depths=depths,
        model_defined=frozenset(moved[k] for k in fs.model_defined),
        lettering=frozenset(moved[k] for k in fs.lettering),
    )


__all__ = ["MIXED_SHARE", "datums_of", "for_process", "turned_profile"]
