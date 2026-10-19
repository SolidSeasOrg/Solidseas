"""The view cube's geometry, without Qt: where its faces, edges and corners are drawn
in its widget, and which of them, or which of its buttons, a point of the widget is on.

The cube follows the model's orientation: it is drawn with the camera's own axes
(:attr:`.viewmath.OrbitCamera.axes`), orthographic like the view, so a point ``p``
of the cube (each coordinate from -1 to 1) lands at ``(S/2 + h p.right, S/2 - h
p.up)`` in a widget of side ``S`` logical pixels, ``h`` being :data:`HALF` of ``S``.
Its faces are SOLIDWORKS's: Front on +Z, Back on -Z, Right on +X, Left on -X, Top
on +Y and Bottom on -Y (:data:`.viewmath.FACES`), each labelled upright as it
appears in its own standard view, so TOP reads with -Z up and BOTTOM with +Z up.

Each face is a 3 x 3 grid: a corner cell in each corner, an edge cell along each
side and the face's own cell in the middle, the border cells :data:`BORDER` of
the face's edge wide. A cell is one of the 26 regions (:data:`.viewmath.REGIONS`):
the face's normal plus the directions of the sides it touches. An edge has a
cell on each of its two faces and a corner one on each of its three, so looking
straight at a face its four edges and four corners are still there to click, as
its border; that is how the hidden half of the cube is reached.

Around the cube are its buttons (:func:`control_rects`): Home at the top-left;
four step arrows, one beside each side of the cube, while the camera looks at a
face square on (straight at it, with its edges along the screen's), and two
roll arrows at the top-right while it looks straight at a face however it is
rolled (:func:`shown_controls`). A step turns a quarter turn to the next face
(:func:`stepped`); a roll turns to the next quarter turn (:func:`rolled`), so
from a view rolled part of the way it squares the face up. Each lands on whole
axis directions. None of the buttons overlaps the cube in any orientation the
cube can have while they show.

The widget's size follows the view's (:func:`cube_side`): 22 percent of its
shorter side, from 96 to 128 logical pixels, and no cube at all in a view under
300 pixels across, where it would take a third of the short side.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .viewmath import (
    FACES,
    FREE,
    ISOMETRIC,
    REGIONS,
    VIEW_KEYS,
    Axes,
    Region,
    region_angles,
    region_text,
    turntable_axes,
)

HALF = 0.21  # the cube's half edge, of the widget's side
BORDER = 0.22  # an edge or corner cell's width, of the face's edge
HIT_FACING = 0.02  # a face turned further from the eye than this is not hit: its solve is ill conditioned
DRAW_FACING = 0.001  # a face turned further away is not drawn
LABEL_FACING = 0.25  # a face turned further away has no label
LABEL_WIDTH = 0.84  # the longest label, BOTTOM, fits this share of the face's edge
LABEL_HEIGHT = 0.24  # and its letters are never taller than this share of it
RING = 0.43  # the step arrows' distance from the middle, of the side
ARROW = 0.10  # a step arrow's size, of the side
BUTTON = 0.16  # Home's and the roll arrows' size, of the side
HOME_AT = (0.02, 0.02)
ROLL_AT = {"roll-ccw": (0.66, 0.02), "roll-cw": (0.82, 0.02)}
MIN_SIDE, MAX_SIDE, SIDE_SHARE, HIDE_BELOW = 96, 128, 0.22, 300
MARGIN = 8  # pixels from the view's edges, as the legend and the pick note keep
FACE_ON = 1e-6  # how near the line of sight (and the screen's axes) must be to a face's normal for the arrows
ROLL_SLACK = 1e-4  # degrees: a view this near a quarter turn is at it, and a roll goes on to the next
STEP_SIDES = {"step-up": (0, -1), "step-down": (0, 1), "step-left": (-1, 0), "step-right": (1, 0)}
STEPS = tuple(STEP_SIDES)
ROLLS = ("roll-ccw", "roll-cw")
HOME = "home"

# Each face's normal, then the directions of its label's right and up, as the face appears
# in its own standard view (:data:`.viewmath.VIEWS`).
FRAMES: dict[Region, tuple[Region, Region]] = {
    (0, 0, 1): ((1, 0, 0), (0, 1, 0)),
    (0, 0, -1): ((-1, 0, 0), (0, 1, 0)),
    (-1, 0, 0): ((0, 0, 1), (0, 1, 0)),
    (1, 0, 0): ((0, 0, -1), (0, 1, 0)),
    (0, 1, 0): ((1, 0, 0), (0, 0, -1)),
    (0, -1, 0): ((1, 0, 0), (0, 0, 1)),
}
LABELS = {face: name.upper() for face, name in FACES.items()}
LONGEST_LABEL = "BOTTOM"
# The light the model's own faces are lit by, in view space (the fragment shader's key light).
_KEY = (0.25 / math.sqrt(1.185), 0.35 / math.sqrt(1.185), 1.0 / math.sqrt(1.185))

Point = tuple[float, float]


@dataclass(frozen=True)
class Cell:
    """One drawn cell: the region it stands for, the face it lies on, its corners in the
    widget (pixels), how squarely its face turns toward the eye (0 edge-on, 1 facing),
    and the share of light its face gets."""

    region: Region
    face: Region
    polygon: tuple[Point, Point, Point, Point]
    facing: float
    shade: float

    @property
    def middle(self) -> Point:
        xs, ys = [p[0] for p in self.polygon], [p[1] for p in self.polygon]
        return (sum(xs) / 4, sum(ys) / 4)

    @property
    def area(self) -> float:
        (x0, y0), (x1, y1), _p2, (x3, y3) = self.polygon
        return abs((x1 - x0) * (y3 - y0) - (y1 - y0) * (x3 - x0))


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cube_side(width: float, height: float) -> int:
    """The widget's side in logical pixels for a view of ``width`` x ``height``; 0 when
    the view is too small for a cube."""
    short = min(width, height)
    if short < HIDE_BELOW:
        return 0
    return int(min(max(round(SIDE_SHARE * short), MIN_SIDE), MAX_SIDE))


def placement(width: float, height: float) -> tuple[int, int, int, int] | None:
    """Where the widget goes in a view of ``width`` x ``height``: its top-right corner,
    :data:`MARGIN` pixels in, as x, y, width, height; None when there is no cube."""
    side = cube_side(width, height)
    if not side:
        return None
    return (int(width) - side - MARGIN, MARGIN, side, side)


def _flat(axes: Axes, v: Sequence[float]) -> Point:
    """A direction of the model as a direction on the widget, y down."""
    right, up, _back = axes
    return (_dot(v, right), -_dot(v, up))


def project(axes: Axes, p: Sequence[float], size: float) -> Point:
    """Where the cube point ``p`` lands in a widget of side ``size``."""
    h, c = HALF * size, size / 2
    fx, fy = _flat(axes, p)
    return (c + h * fx, c + h * fy)


def _grid(i: int) -> tuple[float, float]:
    """The range of face coordinates (-1 to 1) of a cell in column or row ``i`` (-1, 0, 1)."""
    edge = 2 * BORDER
    return {-1: (-1.0, -1.0 + edge), 0: (-1.0 + edge, 1.0 - edge), 1: (1.0 - edge, 1.0)}[i]


def _shade(axes: Axes, face: Region) -> float:
    right, up, back = axes
    n = (_dot(face, right), _dot(face, up), _dot(face, back))
    return 0.55 + 0.45 * max(_dot(n, _KEY), 0.0)


def cells(axes: Axes, size: float, *, facing: float = DRAW_FACING) -> list[Cell]:
    """The cells drawn from this orientation in a widget of side ``size``: nine for each
    face turned toward the eye more than ``facing``. The cube is convex, so they need
    no sort."""
    back = axes[2]
    out = []
    for face, (a, b) in FRAMES.items():
        f = _dot(face, back)
        if f <= facing:
            continue
        shade = _shade(axes, face)
        for iu in (-1, 0, 1):
            u0, u1 = _grid(iu)
            for iv in (-1, 0, 1):
                v0, v1 = _grid(iv)
                corners = tuple(
                    project(axes, [face[k] + u * a[k] + v * b[k] for k in range(3)], size)
                    for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
                )
                region = tuple(face[k] + iu * a[k] + iv * b[k] for k in range(3))
                out.append(Cell(region, face, corners, f, shade))  # type: ignore[arg-type]
    return out


def face_point(axes: Axes, face: Region, x: float, y: float, size: float) -> Point | None:
    """The face coordinates (each -1 to 1 on the face) of the widget point ``(x, y)`` in
    the plane of ``face``; None when the face is too nearly edge-on to tell."""
    a, b = FRAMES[face]
    h, c = HALF * size, size / 2
    nx, ny = _flat(axes, face)
    px, py = (x - c) / h - nx, (y - c) / h - ny
    ax, ay = _flat(axes, a)
    bx, by = _flat(axes, b)
    det = ax * by - ay * bx
    if abs(det) < 1e-12:
        return None
    return ((px * by - py * bx) / det, (ax * py - ay * px) / det)


def _index(t: float) -> int:
    edge = 2 * BORDER
    return -1 if t < -1 + edge else 1 if t > 1 - edge else 0


def region_at(axes: Axes, x: float, y: float, size: float) -> Region | None:
    """The region under the widget point ``(x, y)``, or None off the cube. On the line
    two faces share, the one turned more squarely toward the eye wins."""
    back = axes[2]
    best: tuple[float, Region, float, float] | None = None
    for face in FRAMES:
        f = _dot(face, back)
        if f <= HIT_FACING:
            continue
        uv = face_point(axes, face, x, y, size)
        if uv is None or abs(uv[0]) > 1 or abs(uv[1]) > 1:
            continue
        if best is None or f > best[0]:
            best = (f, face, uv[0], uv[1])
    if best is None:
        return None
    _f, face, u, v = best
    a, b = FRAMES[face]
    iu, iv = _index(u), _index(v)
    return (face[0] + iu * a[0] + iv * b[0], face[1] + iu * a[1] + iv * b[1], face[2] + iu * a[2] + iv * b[2])


def point_of(axes: Axes, region: Region, size: float, *, off_label: bool = False) -> Point | None:
    """The middle of the region's largest cell drawn from here, where a click picks it;
    None when no cell of it can be clicked from here. With ``off_label``, a point of that
    cell below its face's label, where the cell shows its own colour (the self-test reads
    the cube's picture there)."""
    mine = [c for c in cells(axes, size, facing=HIT_FACING) if c.region == tuple(region)]
    if not mine:
        return None
    cell = max(mine, key=lambda c: c.area)
    if not off_label:
        return cell.middle
    a, b = FRAMES[cell.face]
    d = [cell.region[k] - cell.face[k] for k in range(3)]
    iu, iv = round(_dot(d, a)), round(_dot(d, b))
    u, v = sum(_grid(iu)) / 2, sum(_grid(iv)) / 2
    if iv == 0:  # the label runs across this row: below it
        v = -1.0 + 2 * BORDER + 0.14
    face = cell.face
    return project(axes, [face[k] + u * a[k] + v * b[k] for k in range(3)], size)


def path_to(axes: Axes, region: Region, size: float) -> list[Region]:
    """The regions to click in turn to reach ``region`` from the view ``axes``, each drawn
    from the view the click before gives (a click looks from its region, upright), the last
    being ``region`` itself: the shortest such path. Just ``[region]`` when it is drawn
    from here."""
    region = tuple(region)  # type: ignore[assignment]
    if point_of(axes, region, size) is not None:
        return [region]
    seen = {r for r in REGIONS if point_of(axes, r, size) is not None}
    queue = [[r] for r in sorted(seen)]
    while queue:
        path = queue.pop(0)
        there = turntable_axes(*region_angles(path[-1]))
        if point_of(there, region, size) is not None:
            return [*path, region]
        for r in REGIONS:
            if r not in seen and point_of(there, r, size) is not None:
                seen.add(r)
                queue.append([*path, r])
    return [region]  # every region is drawn from some view: never reached


def label_frame(axes: Axes, face: Region, size: float) -> tuple[float, float, float, float, float, float]:
    """The affine map from a face's own square to the widget, for its label: ``(ox, oy,
    ax, ay, bx, by)`` takes the face point ``(u, v)`` (u to the label's right, v up,
    each -1 to 1) to ``(ox + ax u + bx v, oy + ay u + by v)``. The view is orthographic,
    so a face lands as a parallelogram and this map is exact."""
    a, b = FRAMES[face]
    h = HALF * size
    ox, oy = project(axes, face, size)
    ax, ay = _flat(axes, a)
    bx, by = _flat(axes, b)
    return (ox, oy, h * ax, h * ay, h * bx, h * by)


def _whole(v: Sequence[float]) -> Region | None:
    """The direction ``v`` as a whole axis direction (a face's normal), when it is within
    :data:`FACE_ON` of one; None otherwise."""
    for face in FRAMES:
        if all(abs(v[k] - face[k]) <= FACE_ON for k in range(3)):
            return face
    return None


def face_on(axes: Axes) -> Region | None:
    """The face the camera looks straight at, or None."""
    return _whole(axes[2])


def square_on(axes: Axes) -> tuple[Region, Region, Region] | None:
    """The camera's right, up and back as whole axis directions, when it looks straight at
    a face square on: its edges along the screen's, as the cube's clicks and arrows leave
    it. None otherwise (not face on, or rolled part of the way)."""
    right, up, back = (_whole(v) for v in axes)
    if right is None or up is None or back is None:
        return None
    return right, up, back


def shown_controls(axes: Axes, mode: str = FREE) -> frozenset[str]:
    """The buttons shown: Home always; looking at a face square on, the step arrows;
    looking straight at a face however rolled, the roll arrows, unless a turntable looks
    at a side face, where it cannot roll."""
    face = face_on(axes)
    shown = {HOME}
    if face is not None:
        if square_on(axes) is not None:
            shown.update(STEPS)
        if mode == FREE or face[1]:
            shown.update(ROLLS)
    return frozenset(shown)


def _neg(v: Region) -> Region:
    return (-v[0], -v[1], -v[2])


def stepped(axes: Axes, side: str) -> tuple[Region, Region, Region] | None:
    """Where a step arrow (``side``, of :data:`STEPS`) turns a view square on to a face:
    a quarter turn about the screen's horizontal axis (up, down) or vertical axis (left,
    right) that brings the face on that side of the screen to the front, as right, up and
    back in whole axis directions. None when the view is not square on, where the face on
    a side is not one face."""
    square = square_on(axes)
    if square is None:
        return None
    right, up, back = square
    return {
        "step-up": (right, _neg(back), up),
        "step-down": (right, back, _neg(up)),
        "step-left": (back, up, _neg(right)),
        "step-right": (_neg(back), up, right),
    }[side]


def rolled(axes: Axes, sign: int) -> tuple[Region, Region, Region] | None:
    """Where a roll arrow turns a view that looks straight at a face: counter-clockwise on
    the screen (``sign`` 1) or clockwise (-1) to the next quarter turn, a quarter turn from
    a view square on and less from one rolled part of the way, as right, up and back in
    whole axis directions. None when the camera does not look straight at a face."""
    face = face_on(axes)
    if face is None:
        return None
    now_right, now_up, _back = axes
    best: tuple[float, Region] | None = None
    for w in FRAMES:
        if _dot(w, face):
            continue  # of the faces' normals, the four square to this face can be up
        # Rolled by ``a`` (counter-clockwise), the view's up is cos(a) up + sin(a) right.
        a = (sign * math.degrees(math.atan2(_dot(w, now_right), _dot(w, now_up)))) % 360.0
        if a < ROLL_SLACK or a > 360.0 - ROLL_SLACK:
            a = 360.0  # up already: the next quarter turn instead
        if best is None or a < best[0]:
            best = (a, w)
    assert best is not None
    up = best[1]
    right = (
        up[1] * face[2] - up[2] * face[1],
        up[2] * face[0] - up[0] * face[2],
        up[0] * face[1] - up[1] * face[0],
    )  # up x back
    return right, up, face


def control_rects(size: float) -> dict[str, tuple[float, float, float, float]]:
    """Each button's square in the widget: x, y, width, height in pixels."""
    b, a, c = BUTTON * size, ARROW * size, size / 2
    ring = RING * size
    out = {HOME: (HOME_AT[0] * size, HOME_AT[1] * size, b, b)}
    for name, (fx, fy) in ROLL_AT.items():
        out[name] = (fx * size, fy * size, b, b)
    for name, (dx, dy) in STEP_SIDES.items():
        out[name] = (c + dx * ring - a / 2, c + dy * ring - a / 2, a, a)
    return out


def control_at(x: float, y: float, size: float, shown: frozenset[str] | set[str]) -> str | None:
    """The button shown under the widget point ``(x, y)``, or None."""
    for name, (x0, y0, w, h) in control_rects(size).items():
        if name in shown and x0 <= x <= x0 + w and y0 <= y <= y0 + h:
            return name
    return None


def tooltip(region: Region) -> str:
    """What a region's tooltip says."""
    if tuple(region) == ISOMETRIC:
        return "Isometric: front, top and right (R)"
    name = FACES.get(tuple(region))  # type: ignore[arg-type]
    if name is not None:
        key = next(k for k, v in VIEW_KEYS.items() if v == name)
        return f"{region_text(region)} (Ctrl+{key})"
    return region_text(region)
