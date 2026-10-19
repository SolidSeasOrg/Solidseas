"""Matching the features of two versions of a model (``docs/DRAWINGS.md`` 13.4).

Regeneration pairs the features the drawing knows (old) with the features a new run
found (new) by their descriptors (6.4.1), never by node ids:

1. **Equal type and size signature.** Within each type, the old and new features
   whose size signatures are equal (``keys.same_size`` within ``exact_tolerance``)
   are paired by an assignment problem on their positions.
2. **Changed size.** What is left of each type is paired the same way among features
   whose sizes are within ``size_tolerance`` of each other (relative, every numeric
   size value; everything else equal), and those pairs are marked ``changed_size``.

The assignment is the Hungarian method (Kuhn and Munkres, in the shortest augmenting
path form, O(n²m)), implemented here and bounded: a group with more than
``limit`` features on a side is paired greedily, cheapest first, and named in the
result. Costs are distances between positions in the datum frame, each axis
normalised by the part's extent along it: an old position is first carried into the
new part by the change of the extent along each axis, so a mid-plane extrusion that
grew moves its end faces proportionally rather than "far", and a part whose origin
moved keeps its features where they were relative to its extent. Adjacency patterns
(the entry face's normal, neighbouring kinds, member counts) only break ties. A pair
further apart than the gate of its pass is not a pair. Unmatched old features are
gone; unmatched new ones are new. The result is deterministic.

**Positions.** A descriptor's ``position`` of three numbers is a point (x, y, z) in
the datum frame. One number is an offset along the axis that the adjacency's
``axis`` (``x``, ``y`` or ``z``) or ``normal`` (``+z``, ``-x``... or a unit vector)
names; a component the other side does not have costs a full extent. Anything else
is compared component by component, normalised by the part's diagonal.

**Extents** are the part's ((xmin, xmax), (ymin, ymax), (zmin, zmax)) in the datum
frame, as ``FeatureSet.frame.extents`` gives them and the drawing's ``model.extents``
keeps them; without them the box of the descriptors' positions stands in.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidArgumentError
from . import keys
from .numbers import plain_sum
from .types import Descriptor

EXACT_TOLERANCE = 1e-6  # metres: descriptors are rounded to this
SIZE_TOLERANCE = 0.5  # relative: a size may grow or shrink by half and still be "changed size"
EXACT_GATE = 1.0  # normalised: an exact-size pair further apart than one extent is no pair
CHANGED_GATE = 0.25  # normalised: a changed-size pair must stay within a quarter of the extent
MAX_ASSIGN = 300  # features on a side of one assignment problem, at most
QUANTUM = 1e-6  # position costs are rounded to this, so float noise never decides
TIE = 1e-8  # a differing adjacency entry adds this: less than QUANTUM even fifty times over
BIG = 1e6  # the cost of a pair that is not allowed
MIN_SPAN = 1e-9


@dataclass(frozen=True)
class Pair:
    """One match: the old feature's index, the new feature's index, whether its size
    changed, and the cost the assignment paid (normalised distance)."""

    old: int
    new: int
    changed_size: bool
    cost: float


@dataclass(frozen=True)
class Matching:
    """The result: pairs in old order, the old features gone, the new features added
    (indices), and the types paired greedily because they were over the bound."""

    pairs: tuple[Pair, ...] = ()
    gone: tuple[int, ...] = ()
    added: tuple[int, ...] = ()
    greedy: tuple[str, ...] = ()

    def new_for_old(self) -> dict[int, int]:
        return {p.old: p.new for p in self.pairs}

    def old_for_new(self) -> dict[int, int]:
        return {p.new: p.old for p in self.pairs}


def descriptor_of(item: Any) -> Descriptor:
    """The descriptor of a ``Descriptor``, a ``FeatureRecord`` or a ``Feature``."""
    if isinstance(item, Descriptor):
        return item
    d = getattr(item, "descriptor", None)
    if isinstance(d, Descriptor):
        return d
    raise InvalidArgumentError("a feature to match must have a descriptor", detail={"parameter": "features"})


# --------------------------------------------------------------------------- the Hungarian method


def hungarian(cost: Sequence[Sequence[float]]) -> list[int]:
    """The assignment of minimum total cost: for each row the column it takes. Rows must
    not outnumber columns. Finite costs only; O(n²m) and bounded by the matrix."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    if n > m or any(len(r) != m for r in cost):
        raise InvalidArgumentError("the cost matrix must be n by m with n <= m", detail={"parameter": "cost"})
    inf = math.inf
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)  # p[j]: the row holding column j (1-based), 0 when free
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        for _step in range(m + 1):  # each step marks one more column; at most m + 1
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            row = cost[i0 - 1]
            ui0 = u[i0]
            for j in range(1, m + 1):
                if not used[j]:
                    cur = row[j - 1] - ui0 - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        for _step in range(m + 1):
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def _assign(cost: list[list[float]], limit: int) -> tuple[list[tuple[int, int]], bool]:
    """Pairs (row, column) of an assignment that takes as many allowed pairs as it can at
    the least cost; greedy (cheapest first) when a side is over ``limit``."""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return [], False
    if n > limit or m > limit:
        order = sorted((cost[i][j], i, j) for i in range(n) for j in range(m) if cost[i][j] < BIG)
        rows, cols, out = set(), set(), []
        for _c, i, j in order:
            if i not in rows and j not in cols:
                rows.add(i)
                cols.add(j)
                out.append((i, j))
        return sorted(out), True
    if n <= m:
        pairs = [(i, j) for i, j in enumerate(hungarian(cost))]
    else:
        transposed = [[cost[i][j] for i in range(n)] for j in range(m)]
        pairs = [(i, j) for j, i in enumerate(hungarian(transposed))]
    return sorted((i, j) for i, j in pairs if j >= 0 and cost[i][j] < BIG), False


# --------------------------------------------------------------------------- positions


def _axis_hint(d: Descriptor) -> int | None:
    adj = dict(d.adjacency)
    for key in ("axis", "normal"):
        v = adj.get(key)
        if isinstance(v, str):
            name = v.lstrip("+-").lower()
            if name in ("x", "y", "z"):
                return "xyz".index(name)
        if isinstance(v, tuple) and len(v) == 3 and all(isinstance(c, (int, float)) for c in v):
            for k, c in enumerate(v):
                if abs(abs(c) - 1.0) < 1e-6:
                    return k
    return None


def _point(d: Descriptor) -> tuple[str, tuple]:
    """("xyz", (x, y, z) with None where unknown), ("span<k>", its two faces' offsets
    from the part's low face) for a width along frame axis k, or ("raw", the
    numbers)."""
    pos = tuple(float(c) for c in d.position)
    if len(pos) == 3:
        return "xyz", pos
    if len(pos) == 1:
        k = _axis_hint(d)
        if k is not None:
            out: list[float | None] = [None, None, None]
            out[k] = pos[0]
            return "xyz", tuple(out)
    if len(pos) == 2 and d.type == "Width":
        k = _axis_hint(d)
        if k is not None:
            return f"span{k}", pos  # two faces along one axis: never paired across axes
    return "raw", pos


def _extents(points: list[tuple[str, tuple]], given: Any) -> list[tuple[float, float]]:
    if given is not None:
        try:
            ext = [(float(lo), float(hi)) for lo, hi in given]
        except (TypeError, ValueError):
            raise InvalidArgumentError(
                "extents are three (low, high) ranges", detail={"parameter": "extents"}
            ) from None
        if len(ext) != 3 or not all(math.isfinite(lo) and math.isfinite(hi) and lo <= hi for lo, hi in ext):
            raise InvalidArgumentError(
                "extents are three (low, high) ranges", detail={"parameter": "extents"}
            )
        return ext
    out = []
    for k in range(3):
        vals = [p[k] for kind, p in points if kind == "xyz" and p[k] is not None]
        if not vals:  # only widths along this axis: their offsets from the low face give its span
            vals = [v for kind, p in points if kind == f"span{k}" for v in p]
        out.append((min(vals), max(vals)) if vals else (0.0, 0.0))
    return out


class _Frame:
    """Carries old positions into the new part's extent and normalises distances."""

    def __init__(self, old: list[tuple[float, float]], new: list[tuple[float, float]]) -> None:
        self.old, self.new = old, new
        spans = [hi - lo for lo, hi in new]
        diag = math.sqrt(plain_sum(s * s for s in spans))
        self.floor = max(diag * 1e-6, MIN_SPAN)
        self.spans = [max(s, self.floor) for s in spans]
        self.diag = max(diag, self.floor)

    def carry(self, k: int, a: float) -> float:
        lo, hi = self.old[k]
        nlo, nhi = self.new[k]
        span = hi - lo
        if span > self.floor:
            return nlo + (a - lo) * (nhi - nlo) / span
        return nlo + (a - lo)

    def cost(self, a: tuple[str, tuple], b: tuple[str, tuple]) -> float:
        if a[0] == "xyz" and b[0] == "xyz":
            total = 0.0
            for k in range(3):
                x, y = a[1][k], b[1][k]
                if x is None and y is None:
                    continue
                if x is None or y is None:
                    total += 1.0
                    continue
                total += ((self.carry(k, x) - y) / self.spans[k]) ** 2
            return math.sqrt(total)
        if a[0] != b[0] or len(a[1]) != len(b[1]):
            return math.sqrt(3.0)
        if a[0].startswith("span"):
            # offsets from the low face, carried by the change of the part's span
            k = int(a[0][4:])
            was = self.old[k][1] - self.old[k][0]
            grow = (self.new[k][1] - self.new[k][0]) / was if was > self.floor else 1.0
            ends = [((x * grow - y) / self.spans[k]) ** 2 for x, y in zip(a[1], b[1], strict=True)]
            return math.sqrt(plain_sum(ends) / len(ends))
        return math.sqrt(plain_sum(((x - y) / self.diag) ** 2 for x, y in zip(a[1], b[1], strict=True)))


# --------------------------------------------------------------------------- sizes and adjacency


def _numeric(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _size_change(a: Any, b: Any, rel: float) -> float | None:
    """The largest relative change between two size values, or None when they differ in
    kind or by more than ``rel``."""
    if _numeric(a) and _numeric(b):
        scale = max(abs(a), abs(b))
        change = 0.0 if scale == 0.0 else abs(a - b) / scale
        return change if abs(a - b) <= rel * scale + 1e-12 else None
    if isinstance(a, tuple) and isinstance(b, tuple):
        if len(a) != len(b):
            return None
        worst = 0.0
        for x, y in zip(a, b, strict=True):
            c = _size_change(x, y, rel)
            if c is None:
                return None
            worst = max(worst, c)
        return worst
    return 0.0 if a == b else None


def _sizes_close(a: Descriptor, b: Descriptor, rel: float) -> float | None:
    if a.type != b.type or [k for k, _ in a.size] != [k for k, _ in b.size]:
        return None
    worst = 0.0
    for (_k, x), (_k2, y) in zip(a.size, b.size, strict=True):
        c = _size_change(x, y, rel)
        if c is None:
            return None
        worst = max(worst, c)
    return worst


def _adjacency_differences(a: Descriptor, b: Descriptor) -> int:
    da, db = dict(a.adjacency), dict(b.adjacency)
    n = 0
    for k in sorted(set(da) | set(db)):
        if k not in da or k not in db or not keys._close(da[k], db[k], 1e-9):
            n += 1
    return min(n, 50)


# --------------------------------------------------------------------------- matching


def match(
    old: Sequence[Any],
    new: Sequence[Any],
    *,
    old_extents: Any = None,
    new_extents: Any = None,
    exact_tolerance: float = EXACT_TOLERANCE,
    size_tolerance: float = SIZE_TOLERANCE,
    exact_gate: float = EXACT_GATE,
    changed_gate: float = CHANGED_GATE,
    limit: int = MAX_ASSIGN,
) -> Matching:
    """Pair ``old`` features with ``new`` ones (descriptors, ``FeatureRecord`` or features)
    as the module notes say; indices refer to the two sequences."""
    for name, value in (
        ("exact_tolerance", exact_tolerance),
        ("size_tolerance", size_tolerance),
        ("exact_gate", exact_gate),
        ("changed_gate", changed_gate),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < math.inf:
            raise InvalidArgumentError(f"{name} must be a number of 0 or more", detail={"parameter": name})
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise InvalidArgumentError("limit must be 1 to 2,000", detail={"parameter": "limit"})
    od = [descriptor_of(x) for x in old]
    nd = [descriptor_of(x) for x in new]
    op = [_point(d) for d in od]
    np_ = [_point(d) for d in nd]
    frame = _Frame(_extents(op, old_extents), _extents(np_, new_extents))

    free_old = set(range(len(od)))
    free_new = set(range(len(nd)))
    pairs: list[Pair] = []
    greedy: set[str] = set()
    for changed in (False, True):
        types_ = sorted({od[i].type for i in free_old} & {nd[j].type for j in free_new})
        for kind in types_:
            rows = sorted(i for i in free_old if od[i].type == kind)
            cols = sorted(j for j in free_new if nd[j].type == kind)
            gate = changed_gate if changed else exact_gate
            cost: list[list[float]] = []
            dist: dict[tuple[int, int], float] = {}
            for i in rows:
                line = []
                for j in cols:
                    if changed:
                        change = _sizes_close(od[i], nd[j], size_tolerance)
                        ok = change is not None
                    else:
                        change = 0.0
                        ok = keys.same_size(od[i], nd[j], exact_tolerance)
                    if not ok:
                        line.append(BIG)
                        continue
                    d = round(frame.cost(op[i], np_[j]) / QUANTUM) * QUANTUM
                    if d > gate:
                        line.append(BIG)
                        continue
                    dist[(i, j)] = d
                    line.append(d + TIE * (_adjacency_differences(od[i], nd[j]) + min(change or 0.0, 1.0)))
                cost.append(line)
            chosen, was_greedy = _assign(cost, limit)
            if was_greedy:
                greedy.add(kind)
            for a, b in chosen:
                i, j = rows[a], cols[b]
                resized = changed and not keys.same_size(od[i], nd[j], exact_tolerance)
                pairs.append(Pair(i, j, resized, dist[(i, j)]))
                free_old.discard(i)
                free_new.discard(j)
    pairs.sort(key=lambda p: p.old)
    return Matching(tuple(pairs), tuple(sorted(free_old)), tuple(sorted(free_new)), tuple(sorted(greedy)))


__all__ = ["Matching", "Pair", "descriptor_of", "hungarian", "match"]
