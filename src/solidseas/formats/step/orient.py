"""Faces and shells of a solid's mesh turned to agree with their neighbours and with the
file's solids (provisional).

A STEP writer can store a face's holes running the same way as its outer bound, and
the faces lining those holes with a ``same_sense`` that agrees with the stored loops:
the topology is then consistent with itself but inside out at every hole. SolidSeas'
tessellator takes a face's holes by where they lie, not by the way they run, so the
face itself comes out right and the walls of its holes come out turned against it,
and the solid's mesh is not closed (``docs/formats/step.md`` section 10).

:func:`orient_faces` repairs such a mesh the way a B-rep healer orients a shell: two
faces that share a mesh edge must use it in opposite directions. Faces are grouped
by those constraints; in each group, the faces that cover the smaller part of its
area are turned round to agree with the rest. A group whose constraints contradict
each other (a mesh that cannot be oriented, or a face that meets a neighbour both
ways) is left as it is. Only a face's triangles are turned; the B-rep body that
``bodies()`` gives keeps the file's orientation.

A shell is a group of its own, so that check cannot tell a void shell that faces the
wrong way: its faces agree with each other. :func:`orient_shells` turns each closed
shell by its signed volume instead, the solid's outside positive and its voids
negative (``docs/formats/step.md`` section 10).
"""

import math
from array import array
from collections import defaultdict
from collections.abc import Sequence
from typing import Any


def _area(positions: Sequence[float], tris: Sequence[int], t0: int, n: int) -> float:
    total = 0.0
    for k in range(3 * t0, 3 * (t0 + n), 3):
        a, b, c = 3 * tris[k], 3 * tris[k + 1], 3 * tris[k + 2]
        ux, uy, uz = (
            positions[b] - positions[a],
            positions[b + 1] - positions[a + 1],
            positions[b + 2] - positions[a + 2],
        )
        vx, vy, vz = (
            positions[c] - positions[a],
            positions[c + 1] - positions[a + 1],
            positions[c + 2] - positions[a + 2],
        )
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        total += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return total


def orient_faces(
    positions: Sequence[float],
    triangles: array,
    ranges: Sequence[tuple[int, int]],
    clock: Any = None,
    *,
    by_position: bool = False,
) -> tuple[array, int]:
    """``triangles`` (index triples over ``positions``, x y z each) with the faces that
    run against their neighbours turned round, and how many faces were turned.
    ``ranges`` gives each face's first triangle and triangle count. Faces are neighbours
    where they share an edge's points; with ``by_position``, also where their points only
    lie at the same place (faces of a file that share no edge, each with its own)."""
    nv = len(positions) // 3 + 1
    canon = None
    if by_position:
        first: dict[tuple[float, float, float], int] = {}
        canon = [
            first.setdefault((positions[i], positions[i + 1], positions[i + 2]), i // 3)
            for i in range(0, len(positions) - 2, 3)
        ]
    face_of: dict[int, int] = {}  # a directed edge on a face's boundary -> the face
    against: set[tuple[int, int]] = set()  # faces that use an edge the same way
    for f, (t0, n) in enumerate(ranges):
        local: set[int] = set()
        for k in range(3 * t0, 3 * (t0 + n), 3):
            if clock is not None:
                clock.tick()
            a, b, c = triangles[k], triangles[k + 1], triangles[k + 2]
            if canon is not None:
                a, b, c = canon[a], canon[b], canon[c]
            local.update((a * nv + b, b * nv + c, c * nv + a))
        for e in local:
            a, b = divmod(e, nv)
            if b * nv + a in local:
                continue  # inside the face
            g = face_of.get(e)
            if g is None:
                face_of[e] = f
            elif g != f:
                against.add((min(f, g), max(f, g)))
    agree: set[tuple[int, int]] = set()
    for e, f in face_of.items():
        a, b = divmod(e, nv)
        g = face_of.get(b * nv + a)
        if g is not None and g != f:
            agree.add((min(f, g), max(f, g)))
    if not against or agree & against:
        return triangles, 0
    links: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for f, g in agree:
        links[f].append((g, 0))
        links[g].append((f, 0))
    for f, g in against:
        links[f].append((g, 1))
        links[g].append((f, 1))
    turn: dict[int, int] = {}
    for start in sorted(links):
        if start in turn:
            continue
        turn[start] = 0
        group = [start]
        todo = [start]
        while todo:
            f = todo.pop()
            for g, odd in links[f]:
                want = turn[f] ^ odd
                got = turn.get(g)
                if got is None:
                    turn[g] = want
                    group.append(g)
                    todo.append(g)
                elif got != want:
                    return triangles, 0  # the group cannot be oriented
        areas = {f: _area(positions, triangles, *ranges[f]) for f in group}
        turned = sum(areas[f] for f in group if turn[f])
        if turned > 0.5 * sum(areas.values()):
            for f in group:
                turn[f] ^= 1
    flipped = [f for f, t in turn.items() if t]
    if not flipped:
        return triangles, 0
    out = array("I", triangles)
    for f in flipped:
        t0, n = ranges[f]
        for k in range(3 * t0, 3 * (t0 + n), 3):
            out[k + 1], out[k + 2] = out[k + 2], out[k + 1]
    return out, len(flipped)


def orient_shells(
    positions: Sequence[float],
    triangles: array,
    ranges: Sequence[tuple[int, int]],
    face_shells: Sequence[int],
    shells: Sequence[int],
) -> tuple[array, int, int]:
    """``triangles`` with each closed shell of a solid turned to face the way the file says
    it does, and how many void shells and outer shells were turned.

    A solid's first shell is its outside, and must have a positive signed volume; every
    other is a void of a ``BREP_WITH_VOIDS``, and must have a negative one. The file marks
    each void ``ORIENTED_CLOSED_SHELL`` with orientation ``.F.``, which ISO 10303-42 reads
    as the shell's faces turned round: right for a writer whose closed shell faces out of
    the void as a solid's would, wrong for one whose shell already faces into it. The
    signed volume says which. ``ranges`` gives each face's first triangle and triangle
    count, ``face_shells`` each face's SHELL node and ``shells`` the solid's SHELL nodes,
    outer first. A shell that is not closed is left as it is: its volume means little."""
    from ...tessellate import checks

    groups: dict[int, list[tuple[int, int]]] = {}
    for (t0, n), sh in zip(ranges, face_shells, strict=True):
        if n:
            groups.setdefault(sh, []).append((t0, n))
    roles = [(k, groups[sh]) for k, sh in enumerate(shells) if sh in groups]
    if not roles:
        return triangles, 0, 0
    points = list(zip(positions[0::3], positions[1::3], positions[2::3], strict=True))
    found = checks.shells(points, triangles, [g for _k, g in roles])
    out = triangles
    voids = outer = 0
    for (k, g), s in zip(roles, found, strict=True):
        if not s.closed or s.volume == 0.0 or (s.volume > 0.0) == (k == 0):
            continue
        if out is triangles:
            out = array("I", triangles)
        for t0, n in g:
            for j in range(3 * t0, 3 * (t0 + n), 3):
                out[j + 1], out[j + 2] = out[j + 2], out[j + 1]
        if k == 0:
            outer += 1
        else:
            voids += 1
    return out, voids, outer


__all__ = ["orient_faces", "orient_shells"]
