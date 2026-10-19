"""Widths: pairs of antiparallel planar faces along a frame axis (``docs/DRAWINGS.md``
9, C10).

For each frame axis, two planar faces square to it whose footprints overlap and
which face each other directly (a ray from sample points of one meets the other
first over at least half the samples) are a width. Normals pointing apart bound
material (a tab, rib, wall or the envelope itself); pointing toward each other
they bound space (a pocket, slot or groove).

Ranking, as the slice found it must be (C10, a decision the design leaves open;
the VM settles it): the envelope first, then spaces, then material, smaller
widths first within each; a material pair touching only one envelope extreme is
two positions, not a width, so the walls beside a pocket never take the
envelope's place. Pairs are accepted while the links they imply stay a forest, so
stepped interlocks cannot make a cycle. When the envelope's faces do not face
each other directly it is still a width.
"""

from __future__ import annotations

from .. import keys
from ..facegraph import BrepModel, Plane
from ..types import Frame, Width
from ._common import AXIS_NAMES, Rays, add, along, dot, extent, mul

MAX_SAMPLES = 48
FACING_SHARE = 0.5


def _footprint(model: BrepModel, face, others) -> list[tuple[float, float]]:
    return [extent(model, face, d) for d in others]


def _overlap(a, b) -> float:
    """The share of the smaller footprint the two have in common."""
    share = 1.0
    for (a0, a1), (b0, b1) in zip(a, b, strict=True):
        common = min(a1, b1) - max(a0, b0)
        smaller = min(a1 - a0, b1 - b0)
        if common <= 0:
            return 0.0
        share *= common / smaller if smaller > 0 else 1.0
    return share


def _samples(model: BrepModel, face) -> list:
    t0, t1 = face.triangles
    n = t1 - t0
    if n <= 0:
        return []
    step = max(1, n // MAX_SAMPLES)
    out = []
    for t in range(t0, t1, step):
        a, b, c = model.triangles[t]
        pa, pb, pc = model.points[a], model.points[b], model.points[c]
        out.append(tuple((pa[i] + pb[i] + pc[i]) / 3.0 for i in range(3)))
    return out


def _faces_directly(model: BrepModel, rays: Rays, f, g, toward) -> bool:
    samples = _samples(model, f)
    if not samples:
        return False
    idx = rays.along(toward)
    eps = model.tolerance * 10
    hits = 0
    for p in samples:
        first = idx.first(add(p, mul(toward, eps)), skip=frozenset((f.index,)))
        if first is not None and first[1] == g.index:
            hits += 1
    return hits >= FACING_SHARE * len(samples)


def recognise_widths(model: BrepModel, frame: Frame, rays: Rays, claimed: dict[int, str]) -> list[Width]:
    out = []
    tol = model.tolerance * 10
    for k, name in enumerate(AXIS_NAMES):
        d = frame.directions[k]
        others = [frame.directions[i] for i in range(3) if i != k]
        square = []
        for f in model.faces:
            if not isinstance(f.surface, Plane) or claimed.get(f.index) in ("hole", "groove", "slot"):
                continue
            hit = along(f.surface.normal, frame.directions)
            if hit is not None and hit[0] == name:
                square.append((f, hit[1], dot(f.surface.origin, d)))
        if not square:
            continue
        lo_all, hi_all = (
            frame.extents[k]
            if frame.extents
            else (min(c for _f, _s, c in square), max(c for _f, _s, c in square))
        )
        foot = {f.index: _footprint(model, f, others) for f, _s, _c in square}
        pairs = []
        for f, sf, cf in square:
            for g, sg, cg in square:
                if sf == sg or not cf < cg - tol:
                    continue
                share = _overlap(foot[f.index], foot[g.index])
                if share <= 0:
                    continue
                material = sf < 0 and sg > 0
                env = material and abs(cf - lo_all) <= tol and abs(cg - hi_all) <= tol
                touches = abs(cf - lo_all) <= tol or abs(cg - hi_all) <= tol
                if material and touches and not env:
                    continue  # a wall beside a space: two positions (C10)
                pairs.append(
                    (
                        (not env, material, round(cg - cf, 12), -round(share, 9), f.index, g.index),
                        f,
                        g,
                        cf,
                        cg,
                        material,
                        env,
                        share,
                    )
                )
        pairs.sort(key=lambda p: p[0])
        parent: dict = {}

        def find(x, parent=parent):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        have_env = False
        for _key, f, g, cf, cg, material, env, share in pairs:
            # a ray from f along +d meets g first: through the material or the space
            if not _faces_directly(model, rays, f, g, d) and not env:
                continue
            ra, rb = find(round(cf / tol)), find(round(cg / tol))
            if ra == rb:
                continue  # it would close a loop
            parent[ra] = rb
            have_env = have_env or env
            out.append(_width(model, frame, name, f, g, cf, cg, material, env, share, lo_all, hi_all))
            for x in (f.index, g.index):
                claimed.setdefault(x, "width")
        if not have_env:
            low = min((s for s in square if s[1] < 0), key=lambda s: s[2], default=None)
            high = max((s for s in square if s[1] > 0), key=lambda s: s[2], default=None)
            if (
                low is not None
                and high is not None
                and abs(low[2] - lo_all) <= tol
                and abs(high[2] - hi_all) <= tol
            ):
                share = _overlap(foot[low[0].index], foot[high[0].index])
                out.append(
                    _width(
                        model,
                        frame,
                        name,
                        low[0],
                        high[0],
                        low[2],
                        high[2],
                        True,
                        True,
                        share,
                        lo_all,
                        hi_all,
                    )
                )
    return out


def _width(model, frame, name, f, g, cf, cg, material, env, share, lo_all, hi_all) -> Width:
    tol = model.tolerance * 10
    if env:
        role = "envelope"
    elif material:
        role = "wall"
    else:
        floor = set(f.neighbours) & set(g.neighbours)
        role = "pocket" if any(isinstance(model.faces[n].surface, Plane) for n in floor) else "gap"
    mid = (cf + cg) / 2
    symmetric = "envelope" if not env and abs(mid - (lo_all + hi_all) / 2) <= tol else None
    d = keys.descriptor(
        "Width",
        {"size": cg - cf, "kind": "material" if material else "gap", "role": role},
        {"axis": name},
        (cf - lo_all, cg - lo_all),
    )
    return Width(
        (f.index, g.index),
        d,
        True,
        (f.index, g.index),
        name,
        "material" if material else "gap",
        role,
        cg - cf,
        share,
        symmetric,
    )


__all__ = ["recognise_widths"]
