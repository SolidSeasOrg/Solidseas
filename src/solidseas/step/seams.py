"""Faces without loops: a whole sphere or a whole torus, given exact seam edges.

Parasolid lets a face that covers a whole closed surface have no loop
(``docs/FORMAT.md`` 10.8). A STEP ADVANCED_FACE needs at least one bound, so the
export cuts the surface along curves that lie on it exactly and bounds the face
with a loop that runs along each cut once each way:

* a sphere: a vertex at each pole, and one edge on the meridian circle through
  u = 0 from the south pole to the north, used twice;
* a torus whose major radius passes its minor one: one vertex at (u, v) = (0, 0)
  and two ring edges through it, the circle v = 0 round the axis and the circle
  u = 0 across the ring, in the loop (major +, minor +, major -, minor -).

Each face carries its own seam, and every point of it lies on the surface as
written. Other surfaces without loops are refused (``unsupported_surface``).
"""

from ..tessellate._vec import add, mul, sub
from . import entities as E
from . import part21 as p21
from .mapper import Refused


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def seam_bounds(mapper, snode, sm):
    """``(bounds, extent)`` for a face with no loop on the surface ``sm`` (a
    :class:`.mapper.SurfaceMap`) of node ``snode``: the face's one bound, and points
    (mm) that bound the face."""
    item = sm.item
    if isinstance(item, E.Sphere):
        c, a, x = item.placement.frame()
        r = item.radius / p21.SCALE
        north = E.Vertex(E.point_mm(add(c, mul(a, r))))
        south = E.Vertex(E.point_mm(sub(c, mul(a, r))))
        # The meridian u = 0: c + r (cos t x + sin t a), t from -pi/2 to pi/2, a circle
        # whose axis is x cross a.
        meridian = E.Circle(E.Placement(item.placement.location, E.direction(_cross(x, a)), x), item.radius)
        edge = E.Edge(south, north, meridian, True)
        mapper.out.vertices.extend((north, south))
        mapper.out.edges.append(edge)
        r_mm = item.radius
        o = item.placement.location
        extent = [tuple(o[k] - r_mm for k in range(3)), tuple(o[k] + r_mm for k in range(3))]
        return [(E.EdgeLoop([(edge, True), (edge, False)]), True)], extent
    if isinstance(item, E.Torus) and item.select_outer is None:
        c, a, x = item.placement.frame()
        R, r = item.major / p21.SCALE, item.minor / p21.SCALE
        vertex = E.Vertex(E.point_mm(add(c, mul(x, R + r))))
        major = E.Circle(E.Placement(item.placement.location, a, x), p21.rounded(item.major + item.minor))
        minor = E.Circle(E.Placement(E.point_mm(add(c, mul(x, R))), E.direction(_cross(x, a)), x), item.minor)
        e1 = E.Edge(vertex, vertex, major, True)
        e2 = E.Edge(vertex, vertex, minor, True)
        mapper.out.vertices.append(vertex)
        mapper.out.edges.extend((e1, e2))
        k = item.major + item.minor
        o = item.placement.location
        extent = [tuple(o[i] - k for i in range(3)), tuple(o[i] + k for i in range(3))]
        loop = E.EdgeLoop([(e1, True), (e2, True), (e1, False), (e2, False)])
        return [(loop, True)], extent
    raise Refused("unsupported_surface", f"a face with no loop on a {snode.tname}, which has no seam here")
