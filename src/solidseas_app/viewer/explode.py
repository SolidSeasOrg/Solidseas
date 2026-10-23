"""The 3D view's exploded view of an assembly: how far each instance moves, and when.

SOLIDWORKS keeps an assembly's own exploded views inside its binary
configuration data, which SolidSeas does not decode (``docs/FORMAT.md`` 12.6),
so the viewer explodes an assembly itself, for display only: no placement
changes and nothing is written.

:func:`explode` sorts the instances into groups, each top-level component with
everything inside it (:data:`TOP`) or each part on its own (:data:`PARTS`), and
gives each group an offset. The level is the default of every sub-assembly; the
user can choose for one that it explodes or stays together whatever the level
says (:func:`group_of`): one chosen to stay together is a single group, whatever
is inside it and whatever is chosen there, and one chosen to explode gives each
of its components a group, a nested sub-assembly following its own choice in
turn. A sub-assembly chosen to explode inside one that stays together only by
the level's default is pulled out of it: its components move apart, and the
rest of the one around it moves as one. Instances the user hid are left out:
they are in no group and move by nothing, and the rest spread as if they were
not there. Each group gets an offset: away from the centre of the assembly's box, along
the line from there to the centre of the group's box, :data:`SPREAD` times the
distance between the two, so at 100 percent every group is twice as far from
the centre and groups on one line keep their order. A group at the centre (within
:data:`CENTRAL` of the assembly's diagonal) has no such line: the largest one
stays, and the others are stacked along the assembly's longest axis,
alternately to either side, each clear of the one before by :data:`GAP` of the
diagonal. With fewer than two groups nothing moves. Moving away from the centre
parts two groups only by the distance between their centres, so a part inside
another (a pin in a bore, a part in a housing) would stay inside it: groups
still overlapping when fully exploded are then parted, the smaller one moved
out the shortest way (:func:`_separate`). On the development corpus, of the
4,921 pairs of top-level components whose boxes overlap, 1,045 still did at 100
percent without this, and 1 does with it (7,097 pairs of parts: 1,579 and 1);
it takes 0.08 ms at the median and 34 ms at most.

The view draws an instance at ``t`` (0 collapsed, 1 fully exploded) moved by
``t`` times its group's offset. Every instance moves on a straight line, so
the box of the whole assembly at ``t`` lies inside the blend of its boxes at 0
and 1 (:meth:`Explosion.bbox_at`): along each axis the far side of the union
is the largest of straight lines in ``t``, which never rises above its chord.
The camera fits that box while the amount changes. :class:`Animation` eases
the amount from one value to another; :class:`Follow` follows a slider being
dragged or stepped, closing on each new value at once instead of easing from
rest again each time.

Boxes are as :meth:`solidseas.geometry.DisplayGeometry.bounds` gives them: the
corners of the mesh's own box carried into the assembly (:func:`instance_bounds`).
Nothing here imports Qt, so it is tested on its own.
"""

import math
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

TOP, PARTS = "top", "parts"
LEVELS = {TOP: "Top-level components", PARTS: "Every part"}
SPREAD = 1.0  # at 100 percent a group's centre is (1 + SPREAD) times as far from the assembly's
CENTRAL = 0.02  # of the assembly's diagonal: a group whose centre is this close is at the centre
GAP = 0.02  # of the assembly's diagonal: between groups stacked at the centre
FULL_SECONDS = 0.45  # an animation from collapsed to fully exploded
MIN_SECONDS = 0.12
FOLLOW_SECONDS = 0.06  # the time constant with which the view follows a dragged slider
SEPARATE_PASSES = 8  # passes that part groups still overlapping when fully exploded
SEPARATE_UP_TO = 5_000  # groups: more are not parted (the corpus has at most a few hundred)
MAX_COMPARISONS = 1_000_000  # box comparisons those passes may make together
MAX_PAIRS = 50_000  # overlapping pairs one pass parts

Vec = tuple[float, float, float]
Box = tuple[Vec, Vec]


def group_of(instance_id: str, level: str, choices: Mapping[str, bool] | None = None) -> str:
    """The group an instance moves with: at :data:`TOP` its top-level component (the first
    name of its id, whose names are separated by ``/`` and have any ``/`` of their own
    encoded), at :data:`PARTS` itself.

    ``choices`` overrides the level for single sub-assemblies, by their ids: True explodes
    that sub-assembly (its components move apart), False keeps it together (it moves as
    one, whatever is inside it and whatever is chosen there). The level is the default of
    every sub-assembly without a choice: at :data:`TOP` none explodes, at :data:`PARTS`
    every one does. Going down from the top, the first sub-assembly on the instance's
    path that does not explode is its group, and when all of them explode the instance
    is a group of its own. One that stays together only by the level's default is passed
    through when a sub-assembly further down this path is chosen to explode (with no
    choice to stay together between them): so a nested sub-assembly switched on spreads
    its components even at :data:`TOP`, and the rest of the one around it moves as one."""
    if not choices:
        return instance_id.partition("/")[0] if level == TOP else instance_id
    default = level == PARTS
    subs = subassemblies(instance_id)
    for k, sub in enumerate(subs):
        choice = choices.get(sub)
        if choice is False or (choice is None and not default and not _opened(subs[k + 1 :], choices)):
            return sub
    return instance_id


def _opened(inner: list[str], choices: Mapping[str, bool]) -> bool:
    """Whether a sub-assembly of ``inner`` (further down one path, outermost first) is
    chosen to explode with none chosen to stay together before it."""
    for sub in inner:
        choice = choices.get(sub)
        if choice is not None:
            return choice
    return False


def subassemblies(instance_id: str) -> list[str]:
    """The ids of the sub-assemblies an instance is in, from the top-level one down."""
    names = instance_id.split("/")
    return ["/".join(names[: k + 1]) for k in range(len(names) - 1)]


def held_by(sub_id: str, choices: Mapping[str, bool] | None = None) -> str | None:
    """The sub-assembly around ``sub_id`` chosen to stay together, the outermost when
    several are, which moves everything inside it as one whatever ``sub_id``'s own choice
    says; None when there is none."""
    return next((a for a in subassemblies(sub_id) if (choices or {}).get(a) is False), None)


def explodes(sub_id: str, level: str, choices: Mapping[str, bool] | None = None) -> bool:
    """Whether the sub-assembly ``sub_id`` moves its components apart: its choice, else
    the level's default (:func:`group_of`); never while one around it is chosen to stay
    together (:func:`held_by`)."""
    if held_by(sub_id, choices) is not None:
        return False
    return bool((choices or {}).get(sub_id, level == PARTS))


def instance_bounds(bbox: Box, matrices: bytes) -> bytes:
    """Each instance's box in the assembly: float32 low x, y, z then high x, y, z per
    instance, for a mesh whose own box is ``bbox`` placed by each column-major 4 x 4
    matrix of ``matrices`` (float32, 16 each). The box of the mesh box's corners: its
    centre carried over, its half sizes through the rotation's absolute values."""
    m = array("f")
    m.frombytes(matrices)
    (x0, y0, z0), (x1, y1, z1) = bbox
    c = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    h = ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)
    out = array("f")
    for o in range(0, len(m) - 15, 16):
        lo, hi = [], []
        for i in range(3):  # R[i][j] is m[o + 4 * j + i]
            r0, r1, r2 = m[o + i], m[o + 4 + i], m[o + 8 + i]
            centre = r0 * c[0] + r1 * c[1] + r2 * c[2] + m[o + 12 + i]
            half = abs(r0) * h[0] + abs(r1) * h[1] + abs(r2) * h[2]
            lo.append(centre - half)
            hi.append(centre + half)
        out.extend(lo)
        out.extend(hi)
    return out.tobytes()


def _union(a: Box | None, b: Box) -> Box:
    if a is None:
        return b
    return (
        (min(a[0][0], b[0][0]), min(a[0][1], b[0][1]), min(a[0][2], b[0][2])),
        (max(a[1][0], b[1][0]), max(a[1][1], b[1][1]), max(a[1][2], b[1][2])),
    )


def _centre(b: Box) -> Vec:
    return ((b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2, (b[0][2] + b[1][2]) / 2)


def _moved(b: Box, d: Sequence[float]) -> Box:
    return (
        (b[0][0] + d[0], b[0][1] + d[1], b[0][2] + d[2]),
        (b[1][0] + d[0], b[1][1] + d[1], b[1][2] + d[2]),
    )


@dataclass(frozen=True)
class Explosion:
    """The offsets of one level: ``offsets[m]`` holds, for each instance of mesh ``m``,
    its group's offset at 100 percent (float32 x, y, z, metres). ``groups`` counts
    the groups, ``moving`` those that move, ``central`` those found at the centre;
    ``bbox0`` and ``bbox1`` are the assembly's boxes collapsed and fully exploded."""

    level: str
    offsets: list[array]
    groups: int
    moving: int
    central: int
    axis: int
    bbox0: Box
    bbox1: Box

    def bbox_at(self, t: float) -> Box:
        """A box that holds every instance at ``t``: exact at 0 and 1, between them the
        blend of the two (see the module docstring)."""
        t = min(max(t, 0.0), 1.0)
        (a0, b0), (a1, b1) = self.bbox0, self.bbox1
        return (
            tuple(a0[i] + (a1[i] - a0[i]) * t for i in range(3)),  # type: ignore[return-value]
            tuple(b0[i] + (b1[i] - b0[i]) * t for i in range(3)),
        )

    def offset(self, mesh: int, instance: int) -> Vec:
        o = self.offsets[mesh]
        return (o[3 * instance], o[3 * instance + 1], o[3 * instance + 2])


def explode(
    ids: Sequence[Sequence[str]],
    bounds: Sequence[bytes],
    level: str = TOP,
    *,
    spread: float = SPREAD,
    choices: Mapping[str, bool] | None = None,
    hidden: Sequence[Sequence[bool]] | None = None,
) -> Explosion:
    """The :class:`Explosion` of an assembly whose mesh ``m`` has the instances
    ``ids[m]`` (component tree ids) with the boxes ``bounds[m]``
    (:func:`instance_bounds`), at ``level`` (:data:`TOP` or :data:`PARTS`), with the
    sub-assemblies of ``choices`` exploding or kept together as :func:`group_of` says.
    An instance ``hidden[m][k]`` says is hidden is left out: it is in no group, moves by
    nothing, and neither the assembly's box nor the parting of overlaps counts it, so
    what is shown spreads as if it were not there."""
    index: dict[str, int] = {}
    boxes: list[Box] = []
    member: list[list[int]] = []
    for m, (mesh_ids, raw) in enumerate(zip(ids, bounds, strict=True)):
        b = array("f")
        b.frombytes(raw)
        skip = hidden[m] if hidden is not None and m < len(hidden) else ()
        of = []
        for k, iid in enumerate(mesh_ids):
            if k < len(skip) and skip[k]:
                of.append(-1)
                continue
            o = 6 * k
            box = ((b[o], b[o + 1], b[o + 2]), (b[o + 3], b[o + 4], b[o + 5]))
            key = group_of(iid, level, choices)
            g = index.get(key)
            if g is None:
                g = index[key] = len(boxes)
                boxes.append(box)
            else:
                boxes[g] = _union(boxes[g], box)
            of.append(g)
        member.append(of)
    whole: Box | None = None
    for box in boxes:
        whole = _union(whole, box)
    if whole is None:
        whole = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    size = [whole[1][i] - whole[0][i] for i in range(3)]
    diagonal = math.sqrt(sum(s * s for s in size))
    axis = max(range(3), key=lambda i: size[i])
    offsets: list[Vec] = [(0.0, 0.0, 0.0)] * len(boxes)
    central: list[int] = []
    if len(boxes) >= 2 and diagonal > 0:
        c = _centre(whole)
        for g, box in enumerate(boxes):
            p = _centre(box)
            v = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
            if math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) <= CENTRAL * diagonal:
                central.append(g)
            else:
                offsets[g] = (v[0] * spread, v[1] * spread, v[2] * spread)
        if len(central) >= 2:
            # The largest stays; the others go to either side in turn, each clear of the last.
            def extent(g: int) -> float:
                return math.dist(boxes[g][0], boxes[g][1])

            anchor = max(central, key=extent)
            half = (boxes[anchor][1][axis] - boxes[anchor][0][axis]) / 2
            edges = [half, half]  # how far each side reaches from the centre so far
            gap = GAP * diagonal
            turn = 0
            for g in central:
                if g == anchor:
                    continue
                side = turn % 2
                turn += 1
                h = (boxes[g][1][axis] - boxes[g][0][axis]) / 2
                reach = edges[side] + gap + h
                edges[side] = reach + h
                d = [0.0, 0.0, 0.0]
                d[axis] = reach if side == 0 else -reach
                offsets[g] = (d[0], d[1], d[2])
    if len(boxes) >= 2 and diagonal > 0:
        _separate(boxes, offsets, diagonal)
    # As the view draws them: float32, which the exploded box is made from too.
    offsets = [tuple(array("f", o)) for o in offsets]  # type: ignore[misc]
    out: list[array] = []
    for of in member:
        a = array("f")
        for g in of:
            a.extend(offsets[g] if g >= 0 else (0.0, 0.0, 0.0))
        out.append(a)
    exploded: Box | None = None
    for g, box in enumerate(boxes):
        exploded = _union(exploded, _moved(box, offsets[g]))
    return Explosion(
        level=level,
        offsets=out,
        groups=len(boxes),
        moving=sum(1 for o in offsets if o != (0.0, 0.0, 0.0)),
        central=len(central),
        axis=axis,
        bbox0=whole,
        bbox1=exploded or whole,
    )


def _overlapping(moved: list[Box], eps: float, budget: list[int]) -> list[tuple[int, int]]:
    """The pairs of boxes that overlap by more than ``eps`` along every axis, by a sweep
    along x, at most :data:`MAX_PAIRS`; ``budget[0]`` is how many box comparisons are
    left, and the sweep stops when it runs out.

    Along one axis two boxes overlap by more than ``eps`` when ``min(h1, h2) - max(l1,
    l2)`` is, which is the least of ``h1 - l1``, ``h1 - l2``, ``h2 - l1`` and ``h2 - l2``,
    rounded alike: each box is thicker than ``eps`` there, and each one's high side lies
    more than ``eps`` past the other's low side. So each box's thickness is checked
    once, and along x the sweep gives the rest (a box still active ends past the low
    side of the one met now, which begins no earlier than it): a pair costs four
    comparisons, along y and z, and the pairs, their order and the comparisons counted
    are what comparing the boxes whole gives. This runs each time a switch of the
    exploded view changes, on the window's thread."""
    n = len(moved)
    order = sorted(range(n), key=lambda g: moved[g][0][0])
    x0s = [b[0][0] for b in moved]
    x1s = [b[1][0] for b in moved]
    y0s = [b[0][1] for b in moved]
    y1s = [b[1][1] for b in moved]
    z0s = [b[0][2] for b in moved]
    z1s = [b[1][2] for b in moved]
    thick = [x1s[g] - x0s[g] > eps and y1s[g] - y0s[g] > eps and z1s[g] - z0s[g] > eps for g in range(n)]
    active: list[int] = []
    pairs: list[tuple[int, int]] = []
    for g in order:
        budget[0] -= 2 * len(active)
        if budget[0] < 0 or len(pairs) >= MAX_PAIRS:
            break
        x0 = x0s[g]
        active = [a for a in active if x1s[a] - x0 > eps]
        if thick[g]:  # one no thicker than eps along some axis overlaps nothing by more
            y0, y1, z0, z1 = y0s[g], y1s[g], z0s[g], z1s[g]
            for a in active:
                if (
                    y1s[a] - y0 > eps
                    and y1 - y0s[a] > eps
                    and z1s[a] - z0 > eps
                    and z1 - z0s[a] > eps
                    and thick[a]
                ):
                    pairs.append((a, g))
        active.append(g)
    return pairs


def _overlap(a: Box, b: Box, eps: float) -> bool:
    """Whether two boxes overlap by more than ``eps`` along every axis: ``min(h1, h2) -
    max(l1, l2) > eps`` along each, as its four differences (see :func:`_overlapping`)."""
    (ax0, ay0, az0), (ax1, ay1, az1) = a
    (bx0, by0, bz0), (bx1, by1, bz1) = b
    return (
        ax1 - bx0 > eps
        and bx1 - ax0 > eps
        and ay1 - by0 > eps
        and by1 - ay0 > eps
        and az1 - bz0 > eps
        and bz1 - az0 > eps
        and ax1 - ax0 > eps
        and bx1 - bx0 > eps
        and ay1 - ay0 > eps
        and by1 - by0 > eps
        and az1 - az0 > eps
        and bz1 - bz0 > eps
    )


def _separate(boxes: list[Box], offsets: list[Vec], diagonal: float) -> None:
    """Part the groups that the offsets leave overlapping, in place.

    Moving away from the centre separates two groups only by the distance between
    their centres, so a part inside another (a pin in a bore, a part in a housing)
    stays in it. So, the largest groups first, the smaller group of each pair that
    still overlaps moves along the axis and the way that part it with the least
    travel, :data:`GAP` of the diagonal clear; a move can make a new overlap, which
    the next of :data:`SEPARATE_PASSES` passes parts. Each group still moves on a
    straight line, so the blended box holds the assembly at any amount. The work is
    bounded, since this runs on the UI thread: an assembly of more than
    :data:`SEPARATE_UP_TO` groups is not parted, and the passes stop after
    :data:`MAX_COMPARISONS` box comparisons in all, which no corpus assembly comes
    near."""
    n = len(boxes)
    if n > SEPARATE_UP_TO:
        return
    size = [math.dist(b[0], b[1]) for b in boxes]
    eps = 1e-6 * diagonal
    gap = GAP * diagonal
    budget = [MAX_COMPARISONS]
    # The way each group has been pushed along each axis: a group is never pushed back the
    # way it came, so it cannot swing between two larger groups, and moving on one way it
    # comes out of every group in that direction.
    pushed = [[0, 0, 0] for _ in range(n)]
    for _ in range(SEPARATE_PASSES):
        moved = [_moved(boxes[g], offsets[g]) for g in range(n)]
        pairs = _overlapping(moved, eps, budget)
        if not pairs:
            return
        pairs.sort(key=lambda p: (-max(size[p[0]], size[p[1]]), -min(size[p[0]], size[p[1]]), p))
        for i, j in pairs:
            # The smaller one moves; of two the same size, the later one.
            stay, move = (i, j) if (size[i], -i) >= (size[j], -j) else (j, i)
            (alo, ahi), (mlo, mhi) = moved[stay], moved[move]
            if not _overlap(moved[stay], moved[move], eps):
                continue  # parted already by a move earlier in this pass
            best: tuple[float, int, int, int] | None = None
            for k in range(3):
                outward = pushed[move][k] or offsets[move][k]
                # Up by ahi - mlo puts its low side on the other's high side; down by mhi - alo.
                for travel, side in ((ahi[k] - mlo[k], 0), (mhi[k] - alo[k], 1)):
                    sign = 1 if side == 0 else -1
                    if pushed[move][k] == -sign:
                        continue  # not back the way it was pushed
                    # The shortest travel wins; on a tie, the way the group already moves.
                    rank = (travel, 0 if sign * outward > 0 else 1, k, side)
                    if best is None or rank < best:
                        best = rank
            if best is None:
                continue
            travel, _, k, side = best
            sign = 1 if side == 0 else -1
            pushed[move][k] = sign
            d = list(offsets[move])
            d[k] += sign * (travel + gap)
            offsets[move] = (d[0], d[1], d[2])
            moved[move] = _moved(boxes[move], offsets[move])
        if budget[0] < 0:
            return


def ease(x: float) -> float:
    """Smoothstep: starts and ends gently, 0 at 0 and 1 at 1."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


class Animation:
    """The explode amount easing from ``start`` to ``target``, from time ``now`` (seconds,
    any clock), over a time that grows with the distance: :data:`FULL_SECONDS` for the
    whole way, never less than :data:`MIN_SECONDS`."""

    def __init__(self, start: float, target: float, now: float) -> None:
        self.start, self.target, self.t0 = start, target, now
        self.duration = max(MIN_SECONDS, FULL_SECONDS * abs(target - start))

    def value(self, now: float) -> float:
        return self.start + (self.target - self.start) * ease((now - self.t0) / self.duration)

    def done(self, now: float) -> bool:
        return now - self.t0 >= self.duration


FOLLOW_DONE = 0.001  # a Follow this close to its target is there


class Follow:
    """The explode amount following a target that keeps moving, as the Explode slider's
    does while it is dragged or a key held down: from ``start`` at time ``now`` it closes
    on the target exponentially, with the time constant :data:`FOLLOW_SECONDS`. So it
    moves at once, at full speed, and keeps about that time behind a target moving at
    a steady speed; :meth:`retarget` takes a new target from where the amount is now,
    without starting again from rest as a new :class:`Animation` would (which made the
    view fall further behind the faster the slider moved)."""

    def __init__(self, start: float, target: float, now: float) -> None:
        self.start, self.target, self.t0 = start, target, now

    def value(self, now: float) -> float:
        k = math.exp(-max(now - self.t0, 0.0) / FOLLOW_SECONDS)
        return self.target + (self.start - self.target) * k

    def retarget(self, target: float, now: float) -> None:
        self.start, self.t0, self.target = self.value(now), now, target

    def done(self, now: float) -> bool:
        return abs(self.value(now) - self.target) < FOLLOW_DONE
