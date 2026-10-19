"""Matching features between two versions of a model (docs/DRAWINGS.md 13.4; dwg-file):
the Hungarian method, the two passes, normalised positions, and the regeneration
pairs of 19.1 and the o02 to o07 fixtures built as descriptor sets by hand."""

import itertools
import random

import pytest

from solidseas.drawing import keys
from solidseas.drawing import match as M
from solidseas.drawing import types as T
from solidseas.errors import InvalidArgumentError

MM = 0.001


def face(axis, offset, sign):
    return keys.descriptor("face", {}, {"normal": sign + axis}, (offset,))


def box_faces(ext):
    """The six faces of a box with extents ((x0, x1), (y0, y1), (z0, z1)): -x, +x, -y,
    +y, -z, +z."""
    out = []
    for k, axis in enumerate("xyz"):
        out += [face(axis, ext[k][0], "-"), face(axis, ext[k][1], "+")]
    return out


def widths(ext):
    return [
        keys.descriptor("width", {"size": hi - lo, "kind": "material"}, {"axis": axis}, ((lo + hi) / 2,))
        for axis, (lo, hi) in zip("xyz", ext, strict=True)
    ]


def hole(x, y, z, d=5 * MM, through=True):
    return keys.descriptor(
        "hole", {"diameter": d, "segments": ("cylinder",), "through": through}, {"normal": "+z"}, (x, y, z)
    )


def pattern(first, count, pitch=25 * MM, d=5 * MM):
    return keys.descriptor(
        "pattern", {"diameter": d, "pitch": pitch, "kind": "linear"}, {"count": count}, first
    )


def pairs_of(m):
    return {(p.old, p.new) for p in m.pairs}


# --------------------------------------------------------------------------- the Hungarian method


def brute(cost):
    n, m = len(cost), len(cost[0])
    return min(sum(cost[i][p[i]] for i in range(n)) for p in itertools.permutations(range(m), n))


@pytest.mark.parametrize("n, m", [(1, 1), (2, 2), (3, 3), (3, 5), (4, 4), (5, 6), (6, 6)])
def test_the_hungarian_method_finds_the_least_total_cost(n, m):
    rng = random.Random(n * 100 + m)
    for _ in range(25):
        cost = [[round(rng.uniform(0, 10), 3) for _j in range(m)] for _i in range(n)]
        chosen = M.hungarian(cost)
        assert len(set(chosen)) == n and all(0 <= j < m for j in chosen)
        assert sum(cost[i][j] for i, j in enumerate(chosen)) == pytest.approx(brute(cost))


def test_the_hungarian_method_checks_its_matrix():
    assert M.hungarian([]) == []
    with pytest.raises(InvalidArgumentError):
        M.hungarian([[1.0], [2.0]])  # more rows than columns
    with pytest.raises(InvalidArgumentError):
        M.hungarian([[1.0, 2.0], [1.0]])


def test_forbidden_pairs_are_never_taken_and_more_rows_than_columns_work():
    big = M.BIG
    pairs, greedy = M._assign([[big, 1.0], [big, 2.0], [0.5, big]], 300)
    assert pairs == [(0, 1), (2, 0)] and not greedy
    pairs, greedy = M._assign([[1.0, 2.0], [0.5, 9.0]], 1)
    assert greedy and pairs == [(0, 1), (1, 0)]


# --------------------------------------------------------------------------- the passes


def test_equal_size_comes_first_then_changed_size_nearby():
    old = [hole(10 * MM, 10 * MM, 0.0, d=5 * MM)]
    new = [hole(10 * MM, 10 * MM, 0.0, d=6 * MM), hole(40 * MM, 10 * MM, 0.0, d=5 * MM)]
    ext = ((0.0, 0.05), (0.0, 0.02), (0.0, 0.01))
    m = M.match(old, new, old_extents=ext, new_extents=ext)
    assert pairs_of(m) == {(0, 1)} and m.added == (0,) and not m.pairs[0].changed_size
    # with no hole of the old size left, the resized one nearby is the same hole
    m = M.match(old, new[:1], old_extents=ext, new_extents=ext)
    assert pairs_of(m) == {(0, 0)} and m.pairs[0].changed_size
    # a resized feature far away is not the same one
    far = [hole(45 * MM, 15 * MM, 0.0, d=6 * MM)]
    m = M.match(old, far, old_extents=ext, new_extents=ext)
    assert m.pairs == () and m.gone == (0,) and m.added == (0,)
    # nor is one whose kind of size changed (blind instead of through)
    blind = [hole(10 * MM, 10 * MM, 0.0, through=False)]
    assert M.match(old, blind, old_extents=ext, new_extents=ext).pairs == ()


def test_types_never_match_each_other():
    m = M.match([hole(0.0, 0.0, 0.0)], [keys.descriptor("boss", {"diameter": 5 * MM}, {}, (0.0, 0.0, 0.0))])
    assert m.pairs == () and m.gone == (0,) and m.added == (0,)


def test_adjacency_breaks_ties():
    ext = ((0.0, 0.1), (0.0, 0.1), (0.0, 0.1))
    a = keys.descriptor("chamfer", {"legs": (MM, MM)}, {"normal": "+z"}, (0.05, 0.05, 0.1))
    b = keys.descriptor("chamfer", {"legs": (MM, MM)}, {"normal": "-z"}, (0.05, 0.05, 0.1))
    m = M.match([a, b], [b, a], old_extents=ext, new_extents=ext)
    assert pairs_of(m) == {(0, 1), (1, 0)}


def test_faces_on_another_axis_are_never_paired():
    ext = ((0.0, 0.1), (0.0, 0.1), (0.0, 0.1))
    m = M.match([face("z", 0.1, "+")], [face("y", 0.1, "+")], old_extents=ext, new_extents=ext)
    assert m.pairs == ()


def test_matching_is_deterministic_and_takes_records():
    rng = random.Random(7)
    old = [hole(rng.uniform(0, 0.1), rng.uniform(0, 0.1), 0.0) for _ in range(30)]
    new = [hole(x + rng.uniform(-1e-3, 1e-3), y, z) for x, y, z in (d.position for d in old)]
    rng.shuffle(new)
    a = M.match(old, new)
    b = M.match([T.FeatureRecord(f"f-{k}", d) for k, d in enumerate(old, 1)], list(new))
    assert a == b and len(a.pairs) == 30
    with pytest.raises(InvalidArgumentError):
        M.match(["not a feature"], [])
    with pytest.raises(InvalidArgumentError):
        M.match([], [], size_tolerance=-1)
    with pytest.raises(InvalidArgumentError):
        M.match([], [], old_extents=((0, 1),))


def test_a_group_over_the_bound_is_paired_nearest_first_and_named():
    old = [hole(k * MM, 0.0, 0.0) for k in range(12)]
    new = [hole(k * MM + 0.2 * MM, 0.0, 0.0) for k in range(12)]
    m = M.match(old, new, limit=5)
    assert m.greedy == ("hole",) and pairs_of(m) == {(k, k) for k in range(12)}


# --------------------------------------------------------------------------- the regeneration pairs (19.1)


def test_a_mid_plane_extrusion_lengthened_moves_its_ends_proportionally():
    before = ((-0.030, 0.030), (0.0, 0.04), (0.0, 0.02))
    after = ((-0.035, 0.035), (0.0, 0.04), (0.0, 0.02))
    old = box_faces(before) + widths(before) + [hole(0.010, 0.020, 0.020)]
    new = box_faces(after) + widths(after) + [hole(0.010, 0.020, 0.020)]
    m = M.match(old, new, old_extents=before, new_extents=after)
    assert pairs_of(m) == {(k, k) for k in range(len(old))}
    assert {p.old for p in m.pairs if p.changed_size} == {6}  # the length along x
    assert all(p.cost < 0.05 for p in m.pairs)
    # the end faces moved 5 mm; carried by the extent they did not move at all
    assert [p.cost for p in m.pairs if p.old in (0, 1)] == [0.0, 0.0]


def test_the_origin_moved():
    before = ((0.0, 0.08), (0.0, 0.05), (0.0, 0.01))
    after = ((0.01, 0.09), (-0.005, 0.045), (0.0, 0.01))
    old = box_faces(before) + [hole(0.02, 0.025, 0.01), hole(0.06, 0.025, 0.01)]
    new = box_faces(after) + [hole(0.07, 0.020, 0.01), hole(0.03, 0.020, 0.01)]
    for extents in ((before, after), (None, None)):
        m = M.match(old, new, old_extents=extents[0], new_extents=extents[1])
        assert pairs_of(m) == {(k, k) for k in range(6)} | {(6, 7), (7, 6)}
        assert m.gone == () and m.added == ()


def test_a_hole_added_to_a_pattern():
    ext = ((0.0, 0.12), (0.0, 0.04), (0.0, 0.01))
    old = [pattern((0.02, 0.02, 0.01), 4)] + [hole((20 + 25 * k) * MM, 0.02, 0.01) for k in range(4)]
    # one more hole at the end
    new = [pattern((0.02, 0.02, 0.01), 5)] + [hole((20 + 25 * k) * MM, 0.02, 0.01) for k in range(5)]
    m = M.match(old, new, old_extents=ext, new_extents=ext)
    assert pairs_of(m) == {(k, k) for k in range(5)} and m.added == (5,)
    assert not any(p.changed_size for p in m.pairs)
    # 19.1's pair: the grown pattern also moved 10 mm to the left; the hole past the old
    # last one is the new one and the others keep their ids
    new = [pattern((0.01, 0.02, 0.01), 5)] + [hole((10 + 25 * k) * MM, 0.02, 0.01) for k in range(5)]
    m = M.match(old, new, old_extents=ext, new_extents=ext)
    assert pairs_of(m) == {(k, k) for k in range(5)} and m.added == (5,) and m.gone == ()


def test_a_datum_face_that_is_no_longer_the_largest_keeps_its_match():
    before = ((0.0, 0.1), (0.0, 0.06), (0.0, 0.01))  # the top, 100 x 60, is the largest face
    after = ((0.0, 0.1), (0.0, 0.02), (0.0, 0.08))  # now a side, 100 x 80, is
    m = M.match(box_faces(before), box_faces(after), old_extents=before, new_extents=after)
    assert pairs_of(m) == {(k, k) for k in range(6)}
    # without the extents the box of the faces' own positions stands in for them
    m = M.match(box_faces(before), box_faces(after))
    assert pairs_of(m) == {(k, k) for k in range(6)}


def test_the_o02_to_o07_change():
    """o02 is a 10 x 20 box extruded 30 mm from the Front Plane; o07 the same extruded 31."""
    o02 = ((0.0, 0.010), (0.0, 0.020), (0.0, 0.030))
    o07 = ((0.0, 0.010), (0.0, 0.020), (0.0, 0.031))
    old = box_faces(o02) + widths(o02)
    new = box_faces(o07) + widths(o07)
    m = M.match(old, new, old_extents=o02, new_extents=o07)
    assert pairs_of(m) == {(k, k) for k in range(9)}
    assert [p.old for p in m.pairs if p.changed_size] == [8]  # the 30 mm became 31
    # and o02 against itself (o03, saved again) matches everything exactly
    same = M.match(old, old, old_extents=o02, new_extents=o02)
    assert all(p.cost == 0.0 and not p.changed_size for p in same.pairs) and len(same.pairs) == 9


def _width(axis, lo, hi):
    """A width as the recogniser describes one: its faces' offsets from the part's low
    face along ``axis``."""
    return keys.descriptor(
        "Width", {"size": hi - lo, "kind": "material", "role": "envelope"}, {"axis": axis}, (lo, hi)
    )


def test_widths_never_pair_across_axes():
    # a 60 mm width along Y and a 10 mm thickness along Z; the new part has a 20 mm
    # width along Y and an 80 mm height along Z: no Y width may pair with a Z one
    old = [_width("y", 0.0, 60 * MM), _width("z", 0.0, 10 * MM)]
    new = [_width("z", 0.0, 80 * MM), _width("y", 0.0, 20 * MM)]
    m = M.match(old, new)
    for p in m.pairs:
        assert dict(old[p.old].adjacency)["axis"] == dict(new[p.new].adjacency)["axis"]
    grown = M.match([_width("y", 0.0, 60 * MM)], [_width("y", 0.0, 70 * MM)])
    assert [(p.old, p.new, p.changed_size) for p in grown.pairs] == [(0, 0, True)]
