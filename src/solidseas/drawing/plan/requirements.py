"""What a drawing must state (``docs/DRAWINGS.md`` 10.1 and 10.2).

:func:`requirements` reads the feature set and gives:

- the **positions** along each frame axis that the linear graph joins: planar faces
  square to the axis (one position for each offset), the axes of holes, bosses,
  slots and grooves, a circular pattern's centre and the meet lines of angled faces;
- the **implied links** between positions that a size states and the graph
  contracts: widths, depths from an open face, pattern pitches, a slot's walls to
  its centre line;
- the **needs**: each size, callout, note or angle the drawing states once, with
  its :class:`~solidseas.drawing.types.Requirement` and what layout needs to draw it.

Locations are not needs: every position the graph cannot reach through an implied
link needs one, and :mod:`.graph` and :mod:`.schemes` give it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from ..facegraph import Cylinder, Plane, Torus
from ..numbers import plain_sum
from ..types import (
    AngledFace,
    Blend,
    Boss,
    Chamfer,
    Depth,
    Groove,
    Hole,
    Pattern,
    Pocket,
    Requirement,
    Slot,
    Step,
    Width,
    requirement_key,
)
from .context import AXES, Context, Vec3, dot

ANGLE_STEP = 1e-6  # radians: angled faces whose angles round to one step are stated together


@dataclass(frozen=True)
class Pos:
    """A position along a frame axis, metres: a planar face (``face``), the axis of a
    round feature (``centre``, with its radius and the direction of its axis) or the
    meet line of an angled face (``sharp``). ``group`` names the axis line a centre
    lies on, so a hole in a boss is one position with it."""

    id: int
    axis: str
    value: float
    kind: str
    features: tuple[str, ...] = ()
    faces: tuple[int, ...] = ()
    radius: float = 0.0
    along: Vec3 | None = None
    point: Vec3 | None = None
    group: str = ""
    seen: tuple[Vec3, ...] = ()  # view directions that see a centre's feature open; () any
    points: tuple[Vec3, ...] = ()  # every axis point of centres in line at this value


@dataclass(frozen=True)
class Link:
    """An implied link: positions ``a`` and ``b`` are joined by a size the drawing
    states as ``key``, so the graph contracts them into one node."""

    a: int
    b: int
    key: str


@dataclass(frozen=True)
class Need:
    """One thing the drawing states once, other than a location: its requirement,
    the dimension kind that states it, and where it attaches. ``a`` and ``b`` are
    position ids of a linear size; ``anchor`` a model point a leader starts on, on a
    circle of ``radius`` square to ``facing``; ``edge_on`` the direction a view must
    look along to show it (a chamfer's edge, an angled face's meet line). A need
    stated once for equal features (``count`` above 1) holds the other members' points
    in ``anchors``, those a view shows as it shows the first: its leader may start at
    any of them. A radius's leader starts on an arc: ``on_face`` holds, for each member
    a view shows as it shows the first, a point in the middle of its arc, that arc's
    centre, which may lie far off the part, and half the angle the arc spans
    (degrees). ``prefix`` goes before the value (Ø for a turned part's diameter, drawn
    across its outline); ``frame`` names the frame a framed size takes when it is not
    a position frame (``runout``, to the datum axis of a turned part)."""

    req: Requirement
    kind: str
    axis: str | None = None
    a: int | None = None
    b: int | None = None
    anchor: Vec3 | None = None
    facing: Vec3 | None = None
    radius: float = 0.0
    features: tuple[int, ...] = ()
    role: str = "width"
    count: int = 1
    edge_on: Vec3 | None = None
    faces: tuple[int, ...] = ()
    derived: bool = False
    anchors: tuple[Vec3, ...] = ()
    on_face: tuple[tuple[Vec3, Vec3, float], ...] = ()
    prefix: str = ""
    frame: str = ""


@dataclass
class Requirements:
    """Everything :func:`requirements` found."""

    needs: list[Need] = field(default_factory=list)
    positions: dict[str, list[Pos]] = field(default_factory=dict)
    links: dict[str, list[Link]] = field(default_factory=dict)
    origins: dict[str, int] = field(default_factory=dict)
    fillet_radius: float | None = None
    holes_in_patterns: frozenset[int] = frozenset()
    notes: list[str] = field(default_factory=list)

    def position(self, axis: str, pid: int) -> Pos:
        return self._by_id[axis][pid]

    def index(self) -> None:
        self._by_id = {ax: {p.id: p for p in ps} for ax, ps in self.positions.items()}

    def all(self) -> list[Requirement]:
        return [n.req for n in self.needs]


# ---------------------------------------------------------------------- positions


class _Positions:
    """Positions along one axis, merged as they are added: faces at one offset are one
    position, and centres on one axis line at one value are one position."""

    def __init__(self, axis: str, tol: float) -> None:
        self.axis = axis
        self.tol = tol
        self.items: list[Pos] = []
        self.next_id = 0

    def _find(self, value: float, kind: str, group: str, along: Vec3 | None = None) -> int | None:
        """The position this one merges with: a face at the same offset; a centre at the
        same value on the same axis line, or on a parallel axis (holes in line, which
        the drawing joins with a centre line); for a sharp (an angled face's meet line),
        a face at its offset, whose plane it lies in, which already locates it."""
        if kind == "sharp":
            for k, p in enumerate(self.items):
                if p.kind == "face" and abs(p.value - value) <= self.tol:
                    return k
        for k, p in enumerate(self.items):
            if p.kind != kind or abs(p.value - value) > self.tol:
                continue
            if kind == "face" or p.group == group:
                return k
            if (
                kind == "centre"
                and along is not None
                and p.along is not None
                and abs(abs(dot(p.along, along)) - 1.0) <= 1e-9
            ):
                return k
        return None

    def add(
        self,
        value: float,
        kind: str,
        *,
        features: tuple[str, ...] = (),
        faces: tuple[int, ...] = (),
        radius: float = 0.0,
        along: Vec3 | None = None,
        point: Vec3 | None = None,
        group: str = "",
        seen: tuple[Vec3, ...] = (),
    ) -> int:
        k = self._find(value, kind, group, along)
        if k is not None:
            p = self.items[k]
            both = tuple(dict.fromkeys(p.seen + seen)) if p.seen and seen else (p.seen or seen)
            pts = p.points
            if point is not None and all(
                max(abs(a - b) for a, b in zip(q, point, strict=True)) > self.tol for q in pts
            ):
                pts = pts + (point,)
            self.items[k] = Pos(
                p.id,
                p.axis,
                p.value,
                p.kind,
                tuple(dict.fromkeys(p.features + features)),
                tuple(sorted(set(p.faces + faces))),
                max(p.radius, radius),
                p.along or along,
                p.point or point,
                p.group,
                both,
                pts,
            )
            return p.id
        pid = self.next_id
        self.next_id += 1
        pts = (point,) if point is not None else ()
        self.items.append(
            Pos(pid, self.axis, value, kind, features, faces, radius, along, point, group, seen, pts)
        )
        return pid


def _line_group(point: Vec3, direction: Vec3, tol: float) -> str:
    """A name for an axis line: its direction made canonical and its point moved to the
    plane through the origin square to it, rounded to ``tol``."""
    d = direction
    for c in d:
        if abs(c) > 1e-9:
            if c < 0:
                d = (-d[0], -d[1], -d[2])
            break
    t = dot(point, d)
    q = tuple(point[k] - t * d[k] for k in range(3))
    step = max(tol, 1e-9)
    return "line:" + ",".join(str(round(v / step)) for v in (*q, *(round(c, 6) for c in d)))


# ---------------------------------------------------------------------- helpers


def _face_point(ctx: Context, face: int) -> Vec3:
    """A point on a face: the middle of its box, moved onto its plane when planar."""
    lo, hi = ctx.model.faces[face].box
    mid = tuple((lo[k] + hi[k]) / 2 for k in range(3))
    s = ctx.model.faces[face].surface
    if isinstance(s, Plane):
        t = dot(mid, s.normal) - s.offset
        mid = tuple(mid[k] - t * s.normal[k] for k in range(3))
    return mid


def _entry_radius(hole: Hole) -> float:
    """The radius a callout's leader starts on: the hole's widest segment at its entry."""
    widest = 0.0
    for seg in hole.segments:
        widest = max(widest, seg.diameter, seg.diameter_end)
    return widest / 2 if widest > 0 else hole.diameter / 2


def _others(ctx: Context, direction: Vec3) -> list[str]:
    """The frame axes square to a direction that lies along a frame axis."""
    ax = ctx.axis_of(direction)
    if ax is None:
        return []
    return [a for a in AXES if a != ax]


def _claimed_faces(ctx: Context, kinds: tuple[type, ...]) -> set[int]:
    out: set[int] = set()
    for f in ctx.features.features:
        if isinstance(f, kinds):
            out.update(f.faces)
    return out


# ---------------------------------------------------------------------- the step


def requirements(ctx: Context) -> Requirements:
    """Positions, implied links and needs of the drawing (10.1, 10.2)."""
    fs = ctx.features
    ids = ctx.ids
    out = Requirements()
    pos = {ax: _Positions(ax, ctx.tol) for ax in AXES}
    links: dict[str, list[Link]] = {ax: [] for ax in AXES}

    def fid(k: int) -> str:
        return ids[k]

    owners: dict[int, list[str]] = {}
    for k, f in enumerate(fs.features):
        if k in fs.model_defined:
            continue
        claimed = set(f.faces)
        if isinstance(f, Width):
            claimed.update(f.pair)
        if isinstance(f, Step):
            claimed.add(f.face)
        for face in sorted(claimed):
            owners.setdefault(face, []).append(fid(k))

    # Planar faces square to a frame axis are positions, except those a callout states
    # (a hole's or groove's shoulders and floors), blend and chamfer faces, and those a
    # key-dimensions drawing leaves to the model (keep.py).
    stated = _claimed_faces(ctx, (Hole, Groove, Blend, Chamfer))
    stated |= {u.face for u in fs.unclaimed if u.reason == "model_defined"}
    face_pos: dict[int, tuple[str, int]] = {}
    for face in ctx.model.faces:
        if not isinstance(face.surface, Plane) or face.index in stated:
            continue
        ax = ctx.plane_axis(face.index)
        if ax is None:
            continue
        pid = pos[ax].add(
            ctx.plane_at(face.index, ax),
            "face",
            features=tuple(owners.get(face.index, ())),
            faces=(face.index,),
        )
        face_pos[face.index] = (ax, pid)

    patterns = fs.of_type(Pattern)
    in_pattern: dict[int, int] = {}
    for pk, p in patterns:
        for m in p.members:
            in_pattern[m] = pk
    out.holes_in_patterns = frozenset(in_pattern)

    def centre(
        k: int,
        point: Vec3,
        direction: Vec3,
        radius: float,
        extra: tuple[str, ...] = (),
        seen: tuple[Vec3, ...] = (),
    ) -> dict:
        group = _line_group(point, direction, ctx.tol)
        made = {}
        for ax in _others(ctx, direction):
            made[ax] = pos[ax].add(
                ctx.along(ax, point),
                "centre",
                features=(fid(k), *extra),
                radius=radius,
                along=direction,
                point=point,
                group=group,
                seen=seen,
            )
        return made

    # ------------------------------------------------------------------ holes and patterns
    for k, h in fs.of_type(Hole):
        if h.needs_auxiliary or ctx.axis_of(h.axis.direction) is None:
            continue
        pk = in_pattern.get(k)
        if pk is not None and fs.features[pk].kind in ("circular", "arc"):
            continue  # located by the pattern's centre, pitch circle and angles
        if pk is not None and fs.features[pk].kind in ("linear", "grid"):
            centre(k, h.axis.point, h.axis.direction, _entry_radius(h), (fid(pk),), _hole_seen(h))
            continue
        centre(k, h.axis.point, h.axis.direction, _entry_radius(h), seen=_hole_seen(h))
        if pk is None:
            _hole_need(ctx, out, k, h, (k,), 1)

    for pk, p in patterns:
        members = [fs.features[m] for m in p.members]
        first = members[0]
        if not isinstance(first, Hole):
            continue
        _hole_need(ctx, out, pk, first, (pk, *p.members), len(p.members))
        if p.kind in ("linear", "grid"):
            # members joined to the first by the pitches (implied)
            for m in p.members[1:]:
                for ax in _others(ctx, first.axis.direction):
                    # with their axes, so each joins the centre the hole already made
                    # there, which another pattern's member may share (holes in line)
                    a = pos[ax].add(
                        ctx.along(ax, first.axis.point),
                        "centre",
                        features=(fid(p.members[0]), fid(pk)),
                        along=first.axis.direction,
                        group=_line_group(first.axis.point, first.axis.direction, ctx.tol),
                    )
                    hm = fs.features[m]
                    b = pos[ax].add(
                        ctx.along(ax, hm.axis.point),
                        "centre",
                        features=(fid(m), fid(pk)),
                        along=hm.axis.direction,
                        group=_line_group(hm.axis.point, hm.axis.direction, ctx.tol),
                    )
                    if a != b:
                        links[ax].append(Link(a, b, requirement_key("pitch", [fid(pk)], ax)))
            _pitch_needs(ctx, out, pk, p, pos)
        elif p.kind in ("circular", "arc") and p.centre is not None:
            centre(pk, p.centre, first.axis.direction, 0.0, seen=_hole_seen(first))
            out.needs.append(
                Need(
                    Requirement(
                        requirement_key("pcd", [fid(pk)]),
                        "size",
                        (fid(pk),),
                        p.pitch_diameter,
                        "pattern",
                        satisfied_by=("diameter",),
                        tolerance_class="basic" if ctx.scheme == "datum" else "block",
                    ),
                    "diameter",
                    anchor=p.centre,
                    facing=first.axis.direction,
                    radius=p.pitch_diameter / 2,
                    features=(pk,),
                    role="basic" if ctx.scheme == "datum" else "hole_location",
                )
            )
            off_axis = abs(math.remainder(p.first_angle, math.pi / 2)) > 1e-6
            if off_axis:
                # measured from the first frame axis square to the pattern's (the
                # recogniser's u), to the first member, where the record's anchor is
                # (conventions.md 8)
                square = ctx.axis_of(first.axis.direction)
                from_axis = next(ax for ax in AXES if ax != square)
                value = p.first_angle
                if p.kind == "arc":
                    # an arc's first end may lie anywhere round the circle: measured
                    # from whichever way along the axis is nearer it
                    half = p.first_angle % math.pi
                    value = min(half, math.pi - half)
                out.needs.append(
                    Need(
                        Requirement(
                            requirement_key("angle", [fid(pk)]),
                            "angle",
                            (fid(pk),),
                            value,
                            "pattern",
                            graph="angular",
                            satisfied_by=("angle",),
                            tolerance_class="basic" if ctx.scheme == "datum" else "block",
                        ),
                        "angle",
                        axis=from_axis,
                        anchor=first.axis.point,
                        facing=first.axis.direction,
                        radius=p.pitch_diameter / 2,
                        features=(pk, p.members[0]),
                        role="basic",
                    )
                )
            if p.kind == "arc":
                # the step between the first two members with the count of spaces (nX),
                # as a pitch along a row is: it spaces the rest along the arc
                second = fs.features[p.members[1]]
                out.needs.append(
                    Need(
                        Requirement(
                            requirement_key("step", [fid(pk)]),
                            "angle",
                            (fid(pk),),
                            p.step,
                            "pattern",
                            graph="angular",
                            satisfied_by=("angle",),
                            tolerance_class="basic" if ctx.scheme == "datum" else "block",
                        ),
                        "angle",
                        anchor=second.axis.point,
                        facing=first.axis.direction,
                        radius=p.pitch_diameter / 2,
                        features=(pk, p.members[0], p.members[1]),
                        role="basic",
                        count=len(p.members) - 1,
                    )
                )

    # ------------------------------------------------------------------ bosses and grooves
    bosses: dict[tuple[str, int], list[int]] = {}
    across = _turned_radial_axis(ctx)
    turned: dict[int, list[tuple[int, int]]] = {}  # a turned part's equal diameters
    for k, b in fs.of_type(Boss):
        ax = ctx.axis_of(b.axis.direction)
        if ax is None:
            continue
        made = centre(k, b.axis.point, b.axis.direction, b.diameter / 2, seen=(b.axis.direction,))
        if across is not None and _on_turned_axis(ctx, b):
            turned.setdefault(round(b.diameter / max(ctx.tol, 1e-12)), []).append((k, made[across]))
            continue
        bosses.setdefault((ax, round(b.diameter / max(ctx.tol, 1e-12))), []).append(k)
    for members in turned.values():
        _turned_diameter(ctx, out, pos, links, members, across)
    # Equal bosses on one axis are sized once, with their count (nX Ø), on the first of
    # them, as a group of equal holes is; each is still located.
    for ks in bosses.values():
        k, b = ks[0], fs.features[ks[0]]
        out.needs.append(
            Need(
                Requirement(
                    requirement_key("size", [fid(k)]),
                    "size",
                    tuple(fid(j) for j in ks),
                    b.diameter,
                    "feature_size",
                    satisfied_by=("diameter",),
                    tolerance_class="frame" if ctx.scheme == "datum" else "block",
                ),
                "diameter",
                anchor=_boss_rim(b),
                facing=b.axis.direction,
                radius=b.diameter / 2,
                features=tuple(ks),
                role="hole_size",
                count=len(ks),
                faces=tuple(f for j in ks for f in fs.features[j].faces),
                anchors=tuple(_boss_rim(fs.features[j]) for j in ks[1:]),
            )
        )
    for k, g in fs.of_type(Groove):
        if ctx.axis_of(g.axis.direction) is None:
            continue
        centre(k, g.axis.point, g.axis.direction, g.outer / 2)
        for name, value in (("inner", g.inner), ("outer", g.outer)):
            out.needs.append(
                Need(
                    Requirement(
                        requirement_key(name, [fid(k)]),
                        "size",
                        (fid(k),),
                        value,
                        "feature_size",
                        satisfied_by=("diameter",),
                    ),
                    "diameter",
                    anchor=g.axis.point,
                    facing=g.axis.direction,
                    radius=value / 2,
                    features=(k,),
                    role="hole_size",
                )
            )

    # ------------------------------------------------------------------ slots
    for k, s in fs.of_type(Slot):
        _slot(ctx, out, pos, links, k, s, face_pos)

    # ------------------------------------------------------------------ widths and depths
    for k, w in fs.of_type(Width):
        a = face_pos.get(w.pair[0])
        b = face_pos.get(w.pair[1])
        if a is None or b is None or a[0] != b[0]:
            continue
        ax = a[0]
        key = requirement_key("size", [fid(k)])
        links[ax].append(Link(a[1], b[1], key))
        out.needs.append(
            Need(
                Requirement(
                    key,
                    "size",
                    (fid(k),),
                    w.size,
                    "envelope" if w.role == "envelope" else "feature_size",
                    axis=ax,
                    satisfied_by=("linear",),
                ),
                "linear",
                axis=ax,
                a=a[1],
                b=b[1],
                features=(k,),
                role="envelope" if w.role == "envelope" else "width",
                faces=w.pair,
            )
        )
    depths: dict[tuple[str, int, int], list[tuple[Depth, str, float]]] = {}
    for d in fs.depths:
        a = face_pos.get(d.open_face)
        b = face_pos.get(d.floor)
        if a is None or b is None or a[0] != b[0]:
            continue
        if d.feature in fs.model_defined and d.feature not in fs.lettering:
            continue
        ax = a[0]
        owner = fid(d.feature) if 0 <= d.feature < len(ids) else None
        if owner is None:
            continue
        value = d.value
        if ctx.decisions.get(owner, {}).get("depth_from") == "floor":
            # 10.12 set_depth_reference: the floor from the far side of the part (the
            # material left under it) rather than the depth from the open face
            floor_at = ctx.plane_at(d.floor, ax)
            sign = 1.0 if floor_at > ctx.plane_at(d.open_face, ax) else -1.0
            beyond = [
                face_pos[i]
                for i in sorted(face_pos)
                if face_pos[i][0] == ax and sign * (ctx.plane_at(i, ax) - floor_at) > ctx.tol
            ]
            if beyond:
                a = max(beyond, key=lambda fp: (sign * ctx.plane_at(_face_of(face_pos, fp), ax), fp[1]))
                value = abs(ctx.plane_at(_face_of(face_pos, a), ax) - floor_at)
        depths.setdefault((ax, a[1], b[1]), []).append((d, owner, value))
    # Depths between the same two planes (a dozen engraved letters cut from one face) are
    # one size, stated once on the first of them, with their count (nX) when a note on
    # its plan view states it, as equal angles are: not a leader to every letter.
    for (ax, pa, pb), members in depths.items():
        d, owner, value = members[0]
        key = requirement_key("depth", [owner])
        links[ax].append(Link(pa, pb, key))
        out.needs.append(
            Need(
                Requirement(
                    key,
                    "size",
                    tuple(o for _d, o, _v in members),
                    value,
                    "feature_size",
                    axis=ax,
                    satisfied_by=("linear", "leader_note"),
                ),
                "linear",
                axis=ax,
                a=pa,
                b=pb,
                anchor=_face_point(ctx, d.floor),
                facing=ctx.direction(ax),
                features=tuple(m.feature for m, _o, _v in members),
                role="step",
                count=len(members),
                anchors=tuple(_face_point(ctx, m.floor) for m, _o, _v in members[1:]),
                faces=tuple(dict.fromkeys(f for m, _o, _v in members for f in (m.floor, m.open_face))),
            )
        )

    # ------------------------------------------------------------------ pockets
    for k, p in fs.of_type(Pocket):
        if p.corner_radius > 0:
            n = max(1, sum(1 for f in p.faces if not isinstance(ctx.model.faces[f].surface, Plane)))
            out.needs.append(
                Need(
                    Requirement(
                        requirement_key("radius", [fid(k)]),
                        "size",
                        (fid(k),),
                        p.corner_radius,
                        "feature_size",
                        satisfied_by=("radius",),
                    ),
                    "radius",
                    anchor=_round_point(ctx, p.faces),
                    facing=ctx.direction(ctx.plane_axis(p.floor) or "z"),
                    radius=p.corner_radius,
                    features=(k,),
                    role="width",
                    count=n,
                )
            )

    # ------------------------------------------------------------------ blends
    _blends(ctx, out)
    _round_centres(ctx, pos, links)

    # ------------------------------------------------------------------ chamfers
    _chamfers(ctx, out)

    # ------------------------------------------------------------------ angled faces
    angled = fs.of_type(AngledFace)
    groups: dict[tuple[int, str | None, str], list[int]] = {}
    for k, a in angled:
        ax_line = ctx.axis_of(a.meet_line.direction) if a.meet_line is not None else None
        if ax_line is not None:
            for ax in AXES:
                if ax == ax_line:
                    continue
                pos[ax].add(
                    ctx.along(ax, a.meet_line.point),
                    "sharp",
                    features=(fid(k),),
                    along=a.meet_line.direction,
                    point=a.meet_line.point,
                    group=_line_group(a.meet_line.point, a.meet_line.direction, ctx.tol),
                )
        groups.setdefault((round(a.angle / ANGLE_STEP), ax_line, _reference(ctx, a.face)), []).append(k)
    # Equal angles to one principal plane, whose meet lines run along one axis, are stated
    # once, with their count (nX), on the first of them, as equal chamfers and fillets
    # are: a part with a dozen faces at one slope gets one angle, not a dozen. Faces at
    # one angle to different planes (complementary slopes) keep an angle each.
    for ks in sorted(groups.values()):
        k, a = ks[0], fs.features[ks[0]]
        out.needs.append(
            Need(
                Requirement(
                    requirement_key("angle", [fid(k)]),
                    "angle",
                    tuple(fid(j) for j in ks),
                    a.angle,
                    "feature_size",
                    graph="angular",
                    satisfied_by=("angle",),
                    tolerance_class="basic" if ctx.scheme == "datum" else "block",
                ),
                "angle",
                anchor=_angle_point(ctx, a),
                edge_on=a.meet_line.direction if a.meet_line else None,
                features=tuple(ks),
                role="basic",
                count=len(ks),
                faces=tuple(fs.features[j].face for j in ks),
                anchors=tuple(_angle_point(ctx, fs.features[j]) for j in ks[1:]),
            )
        )

    # ------------------------------------------------------------------ origins
    out.positions = {ax: list(pos[ax].items) for ax in AXES}
    out.links = links
    for d in fs.frame.datums:
        hit = face_pos.get(d.face)
        if hit is not None and hit[0] not in out.origins:
            out.origins[hit[0]] = hit[1]
    for ax in AXES:
        chosen = chosen_origin(ctx, out.positions[ax], ax)
        if chosen is not None:
            out.origins[ax] = chosen
        if ax not in out.origins and out.positions[ax]:
            faces = [p for p in out.positions[ax] if p.kind == "face"] or out.positions[ax]
            out.origins[ax] = min(faces, key=lambda p: (p.value, p.id)).id
    out.index()
    return out


def _reference(ctx: Context, face: int) -> str:
    """The frame axis square to the principal plane an angled face's angle is measured
    to: the one its normal lies nearest."""
    normal = ctx.model.faces[face].surface.normal
    # rounded, so a face at 45 degrees, equally near two planes, takes the first of them on
    # every platform
    return max(AXES, key=lambda ax: (round(abs(dot(normal, ctx.direction(ax))), 9), -AXES.index(ax)))


def _face_of(face_pos: dict[int, tuple[str, int]], hit: tuple[str, int]) -> int:
    """The lowest face index standing at a position (faces at one offset merge)."""
    return min(i for i, fp in face_pos.items() if fp == hit)


def chosen_origin(ctx: Context, positions: list[Pos], axis: str) -> int | None:
    """The origin the user set on ``axis`` (10.12 ``set_origin``): a feature's decision
    ``origin_<axis>``, ``centre`` for its centre plane or a face index for one of its
    faces. None when no feature carries one, or the one named is not a position."""
    for fid in sorted(ctx.decisions):
        how = ctx.decisions[fid].get(f"origin_{axis}")
        if how is None:
            continue
        mine = [p for p in positions if fid in p.features]
        if how == "centre":
            mine = [p for p in mine if p.kind == "centre"]
        elif isinstance(how, int) and not isinstance(how, bool):
            mine = [p for p in mine if how in p.faces]
        else:
            mine = []
        if mine:
            return min(mine, key=lambda p: (p.value, p.id)).id
    return None


# ---------------------------------------------------------------------- per feature


def _hole_seen(h: Hole) -> tuple[Vec3, ...]:
    """The view directions that see a hole open: from its entry, and from the far side
    too when it goes through. The axis points from the entry into the material."""
    d = h.axis.direction
    back = (-d[0], -d[1], -d[2])
    return (back, d) if h.through else (back,)


def _angle_point(ctx: Context, a: AngledFace) -> Vec3:
    """Where an angled face's angle points: its meet line, else the face."""
    return a.meet_line.point if a.meet_line else _face_point(ctx, a.face)


def _boss_rim(b: Boss) -> Vec3:
    """The centre of a boss's free end, where its diameter's leader goes."""
    d = b.axis.direction
    return tuple(b.axis.point[k] + d[k] * b.length / 2 for k in range(3))


def _round_point(ctx: Context, faces) -> Vec3 | None:
    for f in faces:
        s = ctx.model.faces[f].surface
        if isinstance(s, Cylinder):
            return s.point
    return None


def _hole_need(ctx: Context, out: Requirements, k: int, h: Hole, feats: tuple[int, ...], count: int) -> None:
    fid = ctx.ids[k]
    out.needs.append(
        Need(
            Requirement(
                requirement_key("callout", [fid]),
                "size",
                (fid,),
                h.diameter,
                "feature_size",
                satisfied_by=("hole_callout",),
                tolerance_class="frame" if ctx.scheme == "datum" else "block",
            ),
            "hole_callout",
            anchor=h.axis.point,
            facing=h.axis.direction,
            radius=_entry_radius(h),
            features=feats,
            role="hole_size",
            count=count,
            faces=h.faces,
        )
    )


def _pitch_needs(ctx: Context, out: Requirements, pk: int, p: Pattern, pos) -> None:
    """A linear or grid pattern's pitch per direction, between its first two members
    along that direction, with the count of spaces."""
    fs = ctx.features
    first = fs.features[p.members[0]]
    fid = ctx.ids[pk]
    for ax in _others(ctx, first.axis.direction):
        here = ctx.along(ax, first.axis.point)
        values = sorted({round(ctx.along(ax, fs.features[m].axis.point) / ctx.tol) for m in p.members})
        if len(values) < 2:
            continue
        nxt = min(
            (fs.features[m] for m in p.members),
            key=lambda h, here=here: (
                abs(ctx.along(ax, h.axis.point) - here) <= ctx.tol,
                abs(ctx.along(ax, h.axis.point) - here),
            ),
        )
        group_a = _line_group(first.axis.point, first.axis.direction, ctx.tol)
        group_b = _line_group(nxt.axis.point, nxt.axis.direction, ctx.tol)
        a = pos[ax]._find(here, "centre", group_a, first.axis.direction)
        b = pos[ax]._find(ctx.along(ax, nxt.axis.point), "centre", group_b, nxt.axis.direction)
        if a is None or b is None:
            continue
        pa, pb = pos[ax].items[a], pos[ax].items[b]
        spaces = len(values) - 1
        out.needs.append(
            Need(
                Requirement(
                    requirement_key("pitch", [fid], ax),
                    "size",
                    (fid,),
                    abs(pb.value - pa.value),
                    "pattern",
                    axis=ax,
                    satisfied_by=("linear",),
                    tolerance_class="basic" if ctx.scheme == "datum" else "block",
                ),
                "linear",
                axis=ax,
                a=pa.id,
                b=pb.id,
                features=(pk,),
                role="basic" if ctx.scheme == "datum" else "hole_location",
                count=spaces,
            )
        )


def _slot(ctx: Context, out: Requirements, pos, links, k: int, s: Slot, face_pos) -> None:
    fid = ctx.ids[k]
    along = ctx.axis_of(s.direction)
    if along is None:
        return
    planes: dict[str, list[int]] = {}
    for f in s.faces:
        ax = ctx.plane_axis(f)
        if ax is not None and ax != along:
            planes.setdefault(ax, []).append(f)
    (e0, e1) = s.ends
    radius = s.width / 2
    across = [a for a in AXES if a != along]
    # the walls are a pair of planes; a blind slot's floor is a single plane square to
    # its depth, which runs along the axis neither along the slot nor across it
    wall_axis = next((a for a in across if len(planes.get(a, ())) >= 2), None)
    floor_axis = next((a for a in across if len(planes.get(a, ())) == 1), None)
    if wall_axis is not None:
        across_axis = wall_axis
    elif floor_axis is not None:
        across_axis = next(a for a in across if a != floor_axis)
    else:
        across_axis = across[0]
    depth_axis = next(a for a in across if a != across_axis)
    direction = ctx.direction(depth_axis)
    group0 = _line_group(e0, direction, ctx.tol)
    group1 = _line_group(e1, direction, ctx.tol)
    c_across = pos[across_axis].add(
        ctx.along(across_axis, e0),
        "centre",
        features=(fid,),
        radius=radius,
        along=direction,
        point=e0,
        group=group0,
    )
    a0 = pos[along].add(
        ctx.along(along, e0),
        "centre",
        features=(fid,),
        radius=radius,
        along=direction,
        point=e0,
        group=group0,
    )
    a1 = pos[along].add(
        ctx.along(along, e1),
        "centre",
        features=(fid,),
        radius=radius,
        along=direction,
        point=e1,
        group=group1,
    )
    links[along].append(Link(a0, a1, requirement_key("length", [fid])))
    # the walls, when planar, sit half the width either side of the centre line
    walls = [face_pos[f][1] for f in s.faces if f in face_pos and face_pos[f][0] == across_axis]
    for w in walls:
        links[across_axis].append(Link(c_across, w, requirement_key("size", [fid])))
    out.needs.append(
        Need(
            Requirement(
                requirement_key("size", [fid]),
                "size",
                (fid,),
                s.width,
                "feature_size",
                axis=across_axis,
                satisfied_by=("linear", "leader_note"),
                tolerance_class="frame" if ctx.scheme == "datum" else "block",
            ),
            "linear" if len(walls) == 2 else "leader_note",
            axis=across_axis,
            a=walls[0] if len(walls) == 2 else None,
            b=walls[1] if len(walls) == 2 else None,
            anchor=e0,
            facing=direction,
            radius=radius,
            features=(k,),
            role="width",
            faces=s.faces,
        )
    )
    out.needs.append(
        Need(
            Requirement(
                requirement_key("length", [fid]),
                "size",
                (fid,),
                s.centre_distance,
                "feature_size",
                axis=along,
                satisfied_by=("linear",),
            ),
            "linear",
            axis=along,
            a=a0,
            b=a1,
            features=(k,),
            role="width",
        )
    )
    out.needs.append(
        Need(
            Requirement(
                requirement_key("radius", [fid]),
                "size",
                (fid,),
                radius,
                "feature_size",
                satisfied_by=("radius",),
            ),
            "radius",
            anchor=e1,
            facing=direction,
            radius=radius,
            features=(k,),
            role="width",
            count=2,
            derived=True,
        )
    )


def _turned_radial_axis(ctx: Context) -> str | None:
    """For a turned part's drawing, the frame axis square to the turning axis that the
    base view shows across the sheet (or the first view that sees the axis side on),
    along which its diameters are drawn across the outline (10.6); None for any other
    drawing, or when no view sees the axis side on."""
    t = ctx.features.turned
    if ctx.process != "turned" or t is None:
        return None
    radial = [a for a in AXES if a != t.frame_axis]
    for spec, _geom in sorted(ctx.orthographic(), key=lambda sg: sg[0].kind != "base"):
        if ctx.looks_along(spec, t.axis.direction):
            continue
        shown = [a for a in radial if ctx.sheet_axis(spec, a) is not None]
        if shown:
            return shown[0]
    return None


def _on_turned_axis(ctx: Context, b: Boss) -> bool:
    """Whether a boss turns about the turned part's axis."""
    t = ctx.features.turned
    if t is None or abs(abs(dot(b.axis.direction, t.axis.direction)) - 1.0) > 1e-6:
        return False
    rel = tuple(b.axis.point[j] - t.axis.point[j] for j in range(3))
    along = dot(rel, t.axis.direction)
    off = math.sqrt(max(dot(rel, rel) - along * along, 0.0))
    return off <= ctx.tol


def _turned_diameter(
    ctx: Context, out: Requirements, pos: dict, links: dict, members: list[tuple[int, int]], across: str
) -> None:
    """A turned diameter (10.6): a cylindrical segment's size, drawn across its outline
    in the profile view, from one outline line to the other, as Ø. ``members`` are the
    segments of that diameter (boss index and its centre position along ``across``):
    equal segments share their outline lines, so they are stated once, on the first,
    with their count (2X Ø), as the coincident-surface check asks. The outline lines
    are positions along ``across``, joined to each other and to the axis by the size,
    so the graph needs no location for them. Under the datum scheme each diameter
    carries a circular runout frame to the datum axis, but the datum's own: a datum on
    a 2X diameter is the common axis of its segments."""
    from .. import standards

    fs = ctx.features
    first = fs.features[members[0][0]]
    fids = tuple(ctx.ids[k] for k, _c in members)
    faces = tuple(f for k, _c in members for f in fs.features[k].faces)
    r = first.diameter / 2.0
    c = ctx.along(across, first.axis.point)
    lo = pos[across].add(c - r, "face", features=fids, faces=faces)
    hi = pos[across].add(c + r, "face", features=fids, faces=faces)
    key = requirement_key("size", [fids[0]])
    links[across].append(Link(lo, hi, key))
    for _k, centre_id in members:
        links[across].append(Link(centre_id, lo, key))
    datum = any(d.face in faces for d in fs.frame.datums)
    framed = ctx.scheme == "datum" and not datum
    count = f"{len(members)}X " if len(members) > 1 else ""
    out.needs.append(
        Need(
            Requirement(
                key,
                "size",
                fids,
                first.diameter,
                "feature_size",
                axis=across,
                satisfied_by=("linear",),
                tolerance_class="frame" if framed else "block",
            ),
            "linear",
            axis=across,
            a=lo,
            b=hi,
            features=tuple(k for k, _c in members),
            role="hole_size",
            count=len(members),
            faces=faces,
            prefix=count + standards.SYMBOL_DIAMETER,
            frame="runout" if framed else "",
        )
    )


def _blends(ctx: Context, out: Requirements) -> None:
    """Fillets and rounds (10.1): the most common radius goes in the fillet note and
    the others get a radius each, grouped by size; full-round ends say R alone."""
    fs = ctx.features
    blends = [(k, b) for k, b in fs.of_type(Blend) if not b.of_hole]
    if not blends:
        return
    sized = [b for _k, b in blends if not b.derived]
    step = max(ctx.tol, 1e-7)
    counts = Counter(round(b.radius / step) for b in sized)
    common = None
    if counts:
        common = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        # the radius itself, not its rounding to the merge step: the note prints it
        out.fillet_radius = next(b.radius for b in sized if round(b.radius / step) == common)
    groups: dict[tuple[int, bool], list[int]] = {}
    for k, b in blends:
        r = round(b.radius / step)
        if not b.derived and r == common:
            continue
        groups.setdefault((r, b.derived), []).append(k)
    for (r, derived), ks in sorted(groups.items()):
        first = ks[0]
        b0 = fs.features[first]
        anchor, facing = _blend_anchor(ctx, b0)
        # where a leader may start: on the face of each member a view shows as it shows
        # the first (its axis along the first's)
        on_face = []
        for k in ks:
            q = _on_blend(ctx, fs.features[k])
            c, f = _blend_anchor(ctx, fs.features[k])
            if None not in (q, c, f, facing) and _parallel(f, facing):
                on_face.append((q, c, _half_span(ctx, fs.features[k], q)))
        out.needs.append(
            Need(
                Requirement(
                    requirement_key("radius", [ctx.ids[first]]),
                    "size",
                    tuple(ctx.ids[k] for k in ks),
                    r * step,
                    "feature_size",
                    satisfied_by=("radius",),
                ),
                "radius",
                anchor=anchor,
                facing=facing,
                radius=r * step,
                features=tuple(ks),
                role="width",
                count=len(ks),
                faces=b0.faces,
                derived=derived,
                on_face=tuple(on_face),
            )
        )


def _round_centres(ctx: Context, pos: dict, links: dict) -> None:
    """A full-round end (a derived R, 10.1) is tangent to the two faces of its width, so
    its centre lies the radius from each: its centre position, which a hole on its axis
    shares, is joined to them (conventions 4 and 5), and the width that places the
    faces places it too."""
    fs = ctx.features
    for k, b in fs.of_type(Blend):
        if not b.derived or b.of_hole:
            continue
        cyl = next(
            (ctx.model.faces[f].surface for f in b.faces if isinstance(ctx.model.faces[f].surface, Cylinder)),
            None,
        )
        if cyl is None or ctx.axis_of(cyl.axis) is None:
            continue
        group = _line_group(cyl.point, cyl.axis, ctx.tol)
        for ax in _others(ctx, cyl.axis):
            c = ctx.along(ax, cyl.point)
            low = pos[ax]._find(c - b.radius, "face", "")
            high = pos[ax]._find(c + b.radius, "face", "")
            if low is None or high is None:
                continue  # tangent to faces on both sides only across its width
            centre = pos[ax].add(
                c, "centre", features=(ctx.ids[k],), along=cyl.axis, point=cyl.point, group=group
            )
            links[ax].append(Link(pos[ax].items[low].id, centre, requirement_key("radius", [ctx.ids[k]])))


def _blend_anchor(ctx: Context, b: Blend) -> tuple[Vec3 | None, Vec3 | None]:
    """A blend's arc centre and the axis a view looks along to show the arc: a
    cylinder's axis; for a torus (a fillet along a curved edge) the centre of its cross-section
    by the face's middle, not the torus's own centre, which can lie far off the part."""
    for f in b.faces:
        s = ctx.model.faces[f].surface
        if isinstance(s, Cylinder):
            return s.point, s.axis
        if isinstance(s, Torus):
            return _section_centre(s, _middle(ctx, f)), s.axis
    return None, None


def _middle(ctx: Context, face: int) -> Vec3:
    """The mean of a face's mesh points (the middle of its box when it has none)."""
    v0, v1 = ctx.model.faces[face].vertices
    pts = ctx.model.points[v0:v1]
    if not pts:
        lo, hi = ctx.model.faces[face].box
        return tuple((lo[k] + hi[k]) / 2 for k in range(3))
    return tuple(plain_sum(p[k] for p in pts) / len(pts) for k in range(3))


def _unit_or_none(v) -> Vec3 | None:
    n = math.sqrt(dot(v, v))
    return None if n < 1e-12 else tuple(c / n for c in v)


def _section_centre(s: Torus, near: Vec3) -> Vec3:
    """The centre of a torus's cross-section nearest ``near``: on its major circle."""
    rel = tuple(near[k] - s.centre[k] for k in range(3))
    w = _unit_or_none(tuple(rel[k] - s.axis[k] * dot(rel, s.axis) for k in range(3)))
    if w is None:
        return s.centre
    return tuple(s.centre[k] + w[k] * s.major for k in range(3))


def _half_span(ctx: Context, b: Blend, mid: Vec3) -> float:
    """Half the angle a blend's arc spans about its axis on either side of ``mid`` (a
    point in its middle), degrees: 45, a fillet's, when its face is not a cylinder."""
    for f in b.faces:
        s = ctx.model.faces[f].surface
        if not isinstance(s, Cylinder):
            continue

        def radial(p, s=s) -> Vec3:
            rel = tuple(p[k] - s.point[k] for k in range(3))
            along = dot(rel, s.axis)
            return tuple(rel[k] - s.axis[k] * along for k in range(3))

        u = _unit_or_none(radial(mid))
        if u is None:
            break
        v = (
            s.axis[1] * u[2] - s.axis[2] * u[1],
            s.axis[2] * u[0] - s.axis[0] * u[2],
            s.axis[0] * u[1] - s.axis[1] * u[0],
        )
        v0, v1 = ctx.model.faces[f].vertices
        widest = 0.0
        for p in ctx.model.points[v0:v1]:
            w = radial(p)
            widest = max(widest, abs(math.degrees(math.atan2(dot(w, v), dot(w, u)))))
        return widest
    return 45.0


def _on_blend(ctx: Context, b: Blend) -> Vec3 | None:
    """A point on a blend's arc, by the middle of its face, where its leader starts."""
    for f in b.faces:
        s = ctx.model.faces[f].surface
        if isinstance(s, Cylinder):
            mid = _middle(ctx, f)
            rel = tuple(mid[k] - s.point[k] for k in range(3))
            along = dot(rel, s.axis)
            radial = _unit_or_none(tuple(rel[k] - s.axis[k] * along for k in range(3)))
            if radial is None:
                return None
            return tuple(s.point[k] + s.axis[k] * along + radial[k] * s.radius for k in range(3))
        if isinstance(s, Torus):
            mid = _middle(ctx, f)
            core = _section_centre(s, mid)
            out = _unit_or_none(tuple(mid[k] - core[k] for k in range(3)))
            return None if out is None else tuple(core[k] + out[k] * s.minor for k in range(3))
    return None


def _chamfers(ctx: Context, out: Requirements) -> None:
    """Chamfers grouped by their legs and angle, one statement a group (``nX``)."""
    fs = ctx.features
    step = max(ctx.tol, 1e-7)
    groups: dict[tuple, list[int]] = {}
    for k, c in fs.of_type(Chamfer):
        legs = tuple(sorted(round(v / step) for v in c.legs))
        groups.setdefault((legs, round(c.angle, 6), c.shape), []).append(k)
    for (_legs, _angle, _shape), ks in sorted(groups.items()):
        c0 = fs.features[ks[0]]
        anchor, edge_on = _chamfer_anchor(ctx, c0)
        # the other members a view shows as a line as it shows the first
        others = [_chamfer_anchor(ctx, fs.features[k]) for k in ks[1:]]
        anchors = tuple(p for p, e in others if p is not None and e == edge_on)
        out.needs.append(
            Need(
                Requirement(
                    requirement_key("chamfer", [ctx.ids[ks[0]]]),
                    "size",
                    tuple(ctx.ids[k] for k in ks),
                    min(c0.legs),
                    "feature_size",
                    satisfied_by=("chamfer",),
                ),
                "chamfer",
                anchor=anchor,
                edge_on=edge_on,
                features=tuple(ks),
                role="width",
                count=len(ks),
                faces=c0.faces,
                anchors=anchors,
            )
        )


def _parallel(a: Vec3, b: Vec3) -> bool:
    """Whether two unit directions lie along one line, either way."""
    return abs(abs(dot(a, b)) - 1.0) < 1e-6


def _chamfer_anchor(ctx: Context, c: Chamfer) -> tuple[Vec3 | None, Vec3 | None]:
    """Where a chamfer's leader points (its first face) and the direction a view must
    look along to show it as a line, when planar."""
    face = c.faces[0] if c.faces else None
    if face is None:
        return None, None
    s = ctx.model.faces[face].surface
    edge_on = None
    if isinstance(s, Plane):
        # the view that shows a planar chamfer as a line looks along its edge
        edge_on = ctx.direction(min(AXES, key=lambda a: abs(dot(s.normal, ctx.direction(a)))))
    return _face_point(ctx, face), edge_on


__all__ = ["Link", "Need", "Pos", "Requirements", "requirements"]
