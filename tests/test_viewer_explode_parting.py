"""The exploded view's parting of groups that overlap, made cheaper without changing what
it gives.

A switch of the exploded view (a sub-assembly made to explode or stay together, the
level, what is hidden) works the offsets out again on the window's thread, and in a
compact assembly most of that time went to finding the groups that still overlap. The
sweep now compares each pair by four differences instead of six calls to min and max,
and checks each box's own thickness once; the pairs, their order and the comparisons it
counts must be exactly what comparing the boxes whole gives, since the parting's result
depends on all three. These tests hold the new code to the old, kept here, on random
boxes full of ties, thin boxes, touching faces and overlaps of exactly ``eps``, on the
budget and the pair limit, and on whole explosions of compact assemblies; and they
check that a scene keeps its last explosions, so a switch changed back costs nothing.
"""

import math
import random
from array import array

import pytest

from solidseas_app.viewer import explode as ex


# --------------------------------------------------------------------------- the code before
def _old_overlapping(moved, eps, budget):
    order = sorted(range(len(moved)), key=lambda g: moved[g][0][0])
    active, pairs = [], []
    for g in order:
        (x0, y0, z0), (x1, y1, z1) = moved[g]
        budget[0] -= 2 * len(active)
        if budget[0] < 0 or len(pairs) >= ex.MAX_PAIRS:
            break
        active = [a for a in active if moved[a][1][0] - x0 > eps]
        for a in active:
            (ax0, ay0, az0), (ax1, ay1, az1) = moved[a]
            if (
                min(x1, ax1) - max(x0, ax0) > eps
                and min(y1, ay1) - max(y0, ay0) > eps
                and min(z1, az1) - max(z0, az0) > eps
            ):
                pairs.append((a, g))
        active.append(g)
    return pairs


def _old_overlap(a, b, eps):
    (alo, ahi), (mlo, mhi) = a, b
    return all(min(mhi[k], ahi[k]) - max(mlo[k], alo[k]) > eps for k in range(3))


def _old_separate(boxes, offsets, diagonal):
    n = len(boxes)
    if n > ex.SEPARATE_UP_TO:
        return
    size = [math.dist(b[0], b[1]) for b in boxes]
    eps = 1e-6 * diagonal
    gap = ex.GAP * diagonal
    budget = [ex.MAX_COMPARISONS]
    pushed = [[0, 0, 0] for _ in range(n)]
    for _ in range(ex.SEPARATE_PASSES):
        moved = [ex._moved(boxes[g], offsets[g]) for g in range(n)]
        pairs = _old_overlapping(moved, eps, budget)
        if not pairs:
            return
        pairs.sort(key=lambda p: (-max(size[p[0]], size[p[1]]), -min(size[p[0]], size[p[1]]), p))
        for i, j in pairs:
            stay, move = (i, j) if (size[i], -i) >= (size[j], -j) else (j, i)
            (alo, ahi), (mlo, mhi) = moved[stay], moved[move]
            if not all(min(mhi[k], ahi[k]) - max(mlo[k], alo[k]) > eps for k in range(3)):
                continue
            best = None
            for k in range(3):
                outward = pushed[move][k] or offsets[move][k]
                for travel, side in ((ahi[k] - mlo[k], 0), (mhi[k] - alo[k], 1)):
                    sign = 1 if side == 0 else -1
                    if pushed[move][k] == -sign:
                        continue
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
            moved[move] = ex._moved(boxes[move], offsets[move])
        if budget[0] < 0:
            return


# --------------------------------------------------------------------------- boxes to try
def _boxes(rnd: random.Random, n: int, eps: float) -> list:
    """Boxes on a coarse grid, so that sides meet, starts tie and overlaps of exactly
    ``eps`` happen; some no thicker than ``eps`` along an axis, some inside others, some
    the same as another, some far out or tiny."""
    out = []
    for _ in range(n):
        kind = rnd.random()
        if out and kind < 0.15:
            out.append(rnd.choice(out))  # the same box twice
            continue
        lo, hi = [], []
        for _axis in range(3):
            a = rnd.randrange(0, 12) * 0.25
            if rnd.random() < 0.1:  # about the tolerance: not thicker than eps, or just thicker
                length = rnd.choice([0.0, eps, eps / 2, 2 * eps])
            else:
                length = rnd.choice([0.25, 0.5, 1.0, 1.75, 3.0])
            if kind > 0.9:  # far out, where rounding bites
                a += 1e3
            elif 0.85 < kind <= 0.9:
                a, length = a * 1e-6, length * 1e-6
            lo.append(a)
            hi.append(a + length)
        if out and 0.15 <= kind < 0.3:  # inside another, or overlapping it by exactly eps
            (p0, p1) = rnd.choice(out)
            lo = [p0[i] + (p1[i] - p0[i]) / 4 for i in range(3)]
            hi = [p1[i] - (p1[i] - p0[i]) / 4 if kind < 0.22 else p0[i] + eps for i in range(3)]
        out.append(((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])))
    return out


@pytest.mark.parametrize("seed", range(60))
def test_the_sweep_finds_the_same_pairs_in_the_same_order_and_counts_alike(seed):
    rnd = random.Random(seed)
    eps = rnd.choice([0.0, 1e-9, 1e-6, 0.25])
    boxes = _boxes(rnd, rnd.randrange(0, 160), eps)
    for budget in (ex.MAX_COMPARISONS, rnd.randrange(0, 3000), 0):
        new, old = [budget], [budget]
        assert ex._overlapping(boxes, eps, new) == _old_overlapping(boxes, eps, old)
        assert new == old  # the same comparisons counted, so the passes stop alike
    for _ in range(300):
        a, b = rnd.choice(boxes or [((0, 0, 0), (1, 1, 1))]), rnd.choice(boxes or [((0, 0, 0), (1, 1, 1))])
        assert ex._overlap(a, b, eps) == _old_overlap(a, b, eps) == _old_overlap(b, a, eps)


def test_the_sweep_stops_at_the_pair_limit_as_before(monkeypatch):
    monkeypatch.setattr(ex, "MAX_PAIRS", 7)
    rnd = random.Random(3)
    boxes = _boxes(rnd, 120, 1e-6)
    new, old = [ex.MAX_COMPARISONS], [ex.MAX_COMPARISONS]
    pairs = ex._overlapping(boxes, 1e-6, new)
    assert pairs == _old_overlapping(boxes, 1e-6, old) and new == old and 7 <= len(pairs)


def _compact(tops: int, subs: int, parts: int, seed: int) -> tuple[list, list]:
    """``(ids per mesh, boxes per mesh)`` of an assembly whose sub-assemblies all lie in one
    place, as in a gearbox, each with a frame round its parts and parts inside parts."""
    rnd = random.Random(seed)
    unit = ((0.0, 0.0, 0.0), (0.02, 0.01, 0.005))
    ids: list[list[str]] = [[] for _ in range(6)]
    mats = [array("f") for _ in range(6)]
    for t in range(tops):
        for s in range(subs):
            ids[5].append(f"top{t}-1/sub{s}-1/frame-1")
            mats[5].extend((4, 0, 0, 0, 0, 8, 0, 0, 0, 0, 12, 0, -0.005, -0.005, -0.004, 1))
            last = None
            for p in range(parts):
                m = rnd.randrange(5)
                if last is not None and rnd.random() < 0.3:
                    x, y, z = last[0] + 0.004, last[1] + 0.002, last[2] + 0.001
                else:
                    x, y, z = rnd.random() * 0.06, rnd.random() * 0.06, rnd.random() * 0.05
                last = (x, y, z)
                ids[m].append(f"top{t}-1/sub{s}-1/part{p}-1")
                mats[m].extend((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1))
    return ids, [ex.instance_bounds(unit, m.tobytes()) for m in mats]


@pytest.mark.parametrize(
    ("tops", "subs", "parts", "level", "choices", "hide"),
    [
        (3, 3, 12, ex.PARTS, None, False),
        (3, 3, 12, ex.TOP, {"top0-1": True}, False),
        (4, 2, 20, ex.PARTS, {"top1-1": False, "top2-1/sub0-1": False}, True),
        (2, 4, 25, ex.TOP, {"top0-1/sub1-1": True, "top1-1": True}, True),
    ],
)
def test_explosions_are_what_they_were(monkeypatch, tops, subs, parts, level, choices, hide):
    ids, bounds = _compact(tops, subs, parts, seed=tops * 100 + parts)
    hidden = [[(k % 7 == 3) for k in range(len(i))] for i in ids] if hide else None
    now = ex.explode(ids, bounds, level, choices=choices, hidden=hidden)
    monkeypatch.setattr(ex, "_separate", _old_separate)
    before = ex.explode(ids, bounds, level, choices=choices, hidden=hidden)
    assert now == before and now.groups > 1 and now.moving > 1


# --------------------------------------------------------------------------- kept explosions
def test_a_scene_keeps_its_last_explosions():
    pytest.importorskip("PySide6")
    from solidseas_app.viewer import view3d
    from solidseas_app.viewer.mesh3d import MeshBuffers

    ids, bounds = _compact(2, 2, 10, seed=5)
    mesh = MeshBuffers(b"", b"", b"", 0, 0, ((0.0, 0.0, 0.0), (0.02, 0.01, 0.005)))
    blank = [b""] * len(ids)
    whole = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    scene = view3d.Scene([mesh] * len(ids), blank, blank, whole, ids=ids, bounds=bounds)
    n = sum(len(i) for i in ids)
    first = scene.explosion(ex.TOP, {"top0-1": True}, None)
    assert first == ex.explode(ids, bounds, ex.TOP, choices={"top0-1": True})
    assert scene.explosion(ex.TOP, {"top0-1": True}, [False] * n) is first  # nothing hidden: the same
    assert scene.explosion(ex.TOP, {"top0-1": False}, None) is not first
    assert scene.explosion(ex.TOP, {"top0-1": True}, None) is first  # changed back: kept
    hidden = [k % 5 == 0 for k in range(n)]
    per_mesh, k = [], 0
    for i in ids:
        per_mesh.append(hidden[k : k + len(i)])
        k += len(i)
    assert scene.explosion(ex.PARTS, None, hidden) == ex.explode(ids, bounds, ex.PARTS, hidden=per_mesh)
    for t in range(view3d.KEPT_EXPLOSIONS):
        scene.explosion(ex.PARTS, {f"top{t}-1": True}, None)
    assert len(scene._explosions) == view3d.KEPT_EXPLOSIONS
    assert scene.explosion(ex.TOP, {"top0-1": True}, None) is not first  # let go for newer ones
    assert view3d.Scene([], [], [], ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))).explosion(ex.TOP) is None
