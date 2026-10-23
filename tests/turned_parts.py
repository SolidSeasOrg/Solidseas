"""Synthetic turned (lathe) parts for the drawing tests, built on ``xt_bodies.XtBuilder``:
a profile in the (r, z) half plane revolved about the z axis, as exact Parasolid bodies.

A profile is a closed list of (r, z) points, counter-clockwise (outside faces run up
the profile, bores down), with :class:`Arc` items between points for a fillet (turning
clockwise) or a round (counter-clockwise). Each straight piece becomes a face of
revolution (a plane where it is level, a cylinder where it is upright, a cone where it
slopes) and each arc a torus, or a sphere when its centre is on the axis; a piece on
the axis (r = 0 at both ends) is no face. Every point off the axis is a ring edge, a
circle with no vertex, shared by the faces on either side of it.

:func:`revolve` returns ``(transmit, truth)``; ``truth`` holds the face count and the
diameters and axial lengths of the upright pieces. The named parts below are the
turned goldens of ``docs/DRAWINGS.md`` 21 (stage 2) that a builder without
intersection curves can make: a solid shaft, a stepped shaft with a chamfer and a
fillet, a bored shaft, an undercut groove and a bushing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from xt_bodies import XtBuilder

MM = 1e-3
Z, X = (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Arc:
    """An arc from the previous point of a profile to ``end`` about ``centre``, both
    (r, z); counter-clockwise in the (r, z) plane when ``ccw``."""

    centre: tuple[float, float]
    end: tuple[float, float]
    ccw: bool = True


def _pieces(profile):
    first = profile[0]
    out, prev = [], first
    for item in profile[1:]:
        if isinstance(item, Arc):
            out.append((prev, item.end, item))
            prev = item.end
        else:
            out.append((prev, tuple(item), None))
            prev = tuple(item)
    if math.dist(prev, first) > 1e-15:
        out.append((prev, tuple(first), None))
    return out


def revolve(profile, name: str = "turned"):
    """``(transmit, truth)`` of ``profile`` revolved about z (see the module notes)."""
    b = XtBuilder()
    rings: dict[tuple[float, float], object] = {}
    edges = []

    def ring(p):
        r, z = p
        if r <= 0.0:
            return None
        key = (round(r, 12), round(z, 12))
        if key not in rings:
            e = b.edge(b.circle((0, 0, z), Z, X, r))
            rings[key] = e
            edges.append(e)
        return rings[key]

    faces = 0
    uprights = []
    for (ra, za), (rb, zb), arc in _pieces(profile):
        if ra <= 0.0 and rb <= 0.0:
            continue  # on the axis: no face
        loops = []
        start, end = ring((ra, za)), ring((rb, zb))
        if start is not None:
            loops.append([(start, "+")])
        if end is not None:
            loops.append([(end, "-")])
        if arc is not None:
            rc, zc = arc.centre
            rho = math.dist((ra, za), arc.centre)
            sense = "+" if arc.ccw else "-"  # a round bulges out, a fillet in
            if rc <= 0.0:
                surface = b.sphere((0, 0, zc), rho, Z, X)
            else:
                surface = b.torus((0, 0, zc), Z, rc, rho, X)
        elif za == zb:
            # level: outward is down where the profile runs outward, up where it runs in
            surface, sense = b.plane((0, 0, za), Z, X), ("-" if rb > ra else "+")
        elif ra == rb:
            surface, sense = b.cylinder((0, 0, 0), Z, ra, X), ("+" if zb > za else "-")
            uprights.append({"diameter": 2.0 * ra, "length": abs(zb - za), "bore": zb < za, "z": min(za, zb)})
        else:
            half = math.atan((rb - ra) / (zb - za))
            surface = b.cone((0, 0, za), Z, ra, half, X)
            sense = "+" if zb > za else "-"
        b.face(surface, sense, loops)
        faces += 1
    xt = b.body(edges)
    xt.max_types = 231
    return xt, {"name": name, "faces": faces, "uprights": uprights}


def _shaft(steps, *, chamfer: float = 0.0, fillet: float = 0.0, bore: float = 0.0):
    """A profile of cylinders ``steps`` [(diameter, length)] from z = 0 up, the largest
    usually first; ``chamfer`` a 45 degree chamfer on the top end's edge, ``fillet``
    a fillet in the corner of the first shoulder, ``bore`` a through bore's diameter."""
    rb = bore / 2.0
    pts: list = [(rb, 0.0), (steps[0][0] / 2.0, 0.0)]
    z = 0.0
    for k, (dia, length) in enumerate(steps):
        r = dia / 2.0
        top = z + length
        if k == len(steps) - 1:
            pts += [(r, top - chamfer), (r - chamfer, top)] if chamfer else [(r, top)]
        else:
            r_next = steps[k + 1][0] / 2.0
            if fillet and k == 0 and r_next < r:
                corner = Arc((r_next + fillet, top + fillet), (r_next, top + fillet), ccw=False)
                pts += [(r, top), (r_next + fillet, top), corner]
            else:
                pts += [(r, top), (r_next, top)]
        z = top
    pts.append((rb, z))
    return pts


def solid_shaft():
    """A plain shaft, Ø20 by 60."""
    return revolve(_shaft([(20 * MM, 60 * MM)]), "solid_shaft")


def stepped_shaft():
    """Ø20 by 20, Ø12 by 30 and Ø8 by 15 from the large end, a 1 mm chamfer on the small
    end."""
    return revolve(
        _shaft([(20 * MM, 20 * MM), (12 * MM, 30 * MM), (8 * MM, 15 * MM)], chamfer=1 * MM), "stepped_shaft"
    )


def filleted_shaft():
    """Ø24 by 15 and Ø16 by 35, an R2 fillet in the shoulder's corner."""
    return revolve(_shaft([(24 * MM, 15 * MM), (16 * MM, 35 * MM)], fillet=2 * MM), "filleted_shaft")


def bored_shaft():
    """Ø30 by 10 and Ø18 by 40 with a Ø8 bore through."""
    return revolve(_shaft([(30 * MM, 10 * MM), (18 * MM, 40 * MM)], bore=8 * MM), "bored_shaft")


def bushing():
    """A tube: Ø20 outside, Ø12 bore, 15 long; one cylinder outside, one inside."""
    return revolve(_shaft([(20 * MM, 15 * MM)], bore=12 * MM), "bushing")


def grooved_shaft():
    """Ø16 by 50 with an undercut groove 3 wide down to Ø12, 20 from the large end."""
    r, rg = 8 * MM, 6 * MM
    profile = [
        (0.0, 0.0),
        (r, 0.0),
        (r, 20 * MM),
        (rg, 20 * MM),
        (rg, 23 * MM),
        (r, 23 * MM),
        (r, 50 * MM),
        (0.0, 50 * MM),
    ]
    return revolve(profile, "grooved_shaft")


def small_end_first_shaft():
    """The stepped shaft built from its small end up (z = 0 is the Ø8 end), so the larger
    end is the high one."""
    return revolve(
        _shaft([(8 * MM, 15 * MM), (12 * MM, 30 * MM), (20 * MM, 20 * MM)]), "small_end_first_shaft"
    )


PARTS = {
    "solid_shaft": solid_shaft,
    "stepped_shaft": stepped_shaft,
    "filleted_shaft": filleted_shaft,
    "bored_shaft": bored_shaft,
    "bushing": bushing,
    "grooved_shaft": grooved_shaft,
    "small_end_first_shaft": small_end_first_shaft,
}
