"""The arithmetic behind the Preview tab's pan, zoom and rotate, without Qt.

* :class:`ImageZoom` places a picture in a view: a scale and the view position
  of the picture's top-left corner. Zooming at a cursor keeps the picture point
  under the cursor where it was.
* :class:`OrbitCamera` is the 3D view's orthographic camera. It turns the
  model about a target point at the view's centre, which stays put while it
  turns and which a pan or zoom sets at the depth of the model's centre, in
  one of two rotation modes
  (:data:`ROTATION_MODES`): Free, as SOLIDWORKS does, about the screen's own
  axes with no limit, so every view can be reached, upside down included; or
  Turntable, yaw about the model's Y axis (up in SOLIDWORKS) and pitch about
  the screen's horizontal axis, from straight below to straight above, never
  rolling. It pans the target across the screen and zooms toward the cursor.
  Orthographic, as SOLIDWORKS draws by default, so a point under the cursor
  stays under it while panning and zooming at any depth. It gives SOLIDWORKS's
  standard views (:data:`VIEWS`), exactly, in either mode. Like
  :class:`ImageZoom` it stays ``fitted`` until the user moves it, and a fitted
  camera refits when the view changes shape. It can also turn about a point of
  the model instead of the target, which then keeps its place on the screen,
  and roll about the line of sight. A lens shift draws the target off the
  view's middle, so a fit can centre the model in the part of the view that
  something laid over it (the legend) leaves free, and keep it off the view
  cube's corner where that costs little of its size.
* The view cube's 26 regions (:data:`REGIONS`): directions with components -1,
  0 or 1, each a face, an edge or a corner of a cube with SOLIDWORKS's faces
  (Front on +Z, Top on +Y, Right on +X), looked from upright
  (:func:`region_angles`). :class:`CameraMove` eases the camera to a new view,
  turning the shorter way round (:func:`slerp`), and :func:`unproject` finds
  the model point drawn at a pixel and depth.
* :func:`drag_action` maps a mouse button and modifier keys to rotate, pan or
  zoom for each mouse style, and :func:`wheel_factor` the wheel: away from you
  zooms in for Standard, toward you for SOLIDWORKS, as each does by default.
* Picking: the 3D view finds the instance under the pointer by drawing each
  instance in a colour that is its number (:func:`pick_color`,
  :func:`pick_index`) into a small offscreen square around the pointer, whose
  projection (:func:`pick_projection`) makes those few pixels fill it
  (:func:`pick_window`), and takes the instance nearest the square's centre
  (:func:`nearest_hit`).

Matrices are row-major lists of 16 floats. Screen positions are pixels from
the top-left; normalised device coordinates (NDC) run from -1 to 1 with y up.
Nothing here imports Qt, so it is tested on its own.
"""

import math
from collections.abc import Callable, Sequence
from typing import Any

from .explode import ease

Vec = tuple[float, float, float]

STANDARD, SOLIDWORKS = "standard", "solidworks"
MOUSE_STYLES = {
    STANDARD: "Standard: left-drag rotates, right-drag pans, wheel away from you zooms in",
    SOLIDWORKS: "Middle-drag rotates, Ctrl+middle-drag pans, wheel toward you zooms in, as in SOLIDWORKS",
}
ROTATE, PAN, ZOOM = "rotate", "pan", "zoom"
FREE, TURNTABLE = "free", "turntable"
ROTATION_MODES = {
    FREE: "Free: turns about the screen's axes to any view, upside down too, as SOLIDWORKS does",
    TURNTABLE: "Turntable: turns about the model's vertical axis and tilts up to straight above or below",
}

WHEEL_STEP = 1.25  # zoom factor for one notch of the wheel
ISO_YAW = 45.0
ISO_PITCH = math.degrees(math.asin(1 / math.sqrt(3)))  # 35.26 degrees: looking down the (1, 1, 1) diagonal
DEGREES_PER_PIXEL = 0.4
PITCH_LIMIT = 90.0  # straight down from above, or straight up from below
ARROW_STEP = 15.0  # degrees an arrow key turns the model, as SOLIDWORKS does by default

# SOLIDWORKS's standard views as (yaw, pitch), Y up: Front looks along -Z, Top
# down -Y with the front of the model toward the bottom of the screen.
VIEWS: dict[str, tuple[float, float]] = {
    "front": (0.0, 0.0),
    "back": (180.0, 0.0),
    "left": (270.0, 0.0),
    "right": (90.0, 0.0),
    "top": (0.0, 90.0),
    "bottom": (0.0, -90.0),
    "isometric": (ISO_YAW, ISO_PITCH),
}
VIEW_KEYS = {1: "front", 2: "back", 3: "left", 4: "right", 5: "top", 6: "bottom", 7: "isometric"}  # Ctrl+n


def drag_action(style: str, button: str, *, ctrl: bool = False, shift: bool = False) -> str | None:
    """What dragging with ``button`` (``left``, ``right`` or ``middle``) does in the 3D view.

    Standard: left rotates, right and middle pan. SOLIDWORKS: middle rotates,
    Ctrl+middle pans, Shift+middle zooms, as in SOLIDWORKS; left and right do
    nothing there (SOLIDWORKS selects with them)."""
    if style == SOLIDWORKS:
        if button != "middle":
            return None
        if ctrl:
            return PAN
        if shift:
            return ZOOM
        return ROTATE
    if button == "left":
        return ROTATE
    if button in ("right", "middle"):
        return PAN
    return None


def zooms_in_away(style: str, invert: bool = False) -> bool:
    """Whether rolling the wheel away from you zooms in. It does in the Standard
    style, as in most programs; in the SOLIDWORKS style it zooms out, as SOLIDWORKS
    does out of the box. ``invert`` reverses either, like SOLIDWORKS's "Reverse
    direction of mouse wheel zoom" option."""
    return (style != SOLIDWORKS) != invert


def wheel_factor(steps: float, *, style: str = STANDARD, invert: bool = False) -> float:
    """The magnification for ``steps`` wheel notches; positive steps are the wheel
    rolled away from you (Qt's positive ``angleDelta``)."""
    if not zooms_in_away(style, invert):
        steps = -steps
    return WHEEL_STEP**steps


def wheel_text(style: str, invert: bool = False) -> str:
    """How to zoom in with the wheel, in words."""
    return (
        "roll the wheel "
        + ("away from you" if zooms_in_away(style, invert) else "toward you")
        + " to zoom in"
    )


def ndc(x: float, y: float, width: float, height: float) -> tuple[float, float]:
    """A pixel position as normalised device coordinates."""
    return (2.0 * x / max(width, 1.0) - 1.0, 1.0 - 2.0 * y / max(height, 1.0))


# --------------------------------------------------------------------------- 2D
class ImageZoom:
    """A ``width`` x ``height`` picture shown at ``scale`` with its top-left corner at
    ``(x, y)`` in a view of ``view_w`` x ``view_h`` pixels.

    ``fitted`` stays true until the user zooms or pans, so the picture refits when
    the view is resized."""

    MIN_SCALE = 0.02
    MAX_SCALE = 32.0
    FIT_MAX = 2.0  # fit never enlarges a picture more than this
    KEEP = 32  # pixels of the picture that panning always leaves in view

    def __init__(self, width: int = 0, height: int = 0) -> None:
        self.width, self.height = width, height
        self.view_w, self.view_h = 1, 1
        self.scale, self.x, self.y = 1.0, 0.0, 0.0
        self.fitted = True

    def set_image(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.fit()

    def resize(self, view_w: int, view_h: int) -> None:
        old_w, old_h = self.view_w, self.view_h
        self.view_w, self.view_h = max(view_w, 1), max(view_h, 1)
        if self.fitted:
            self.fit()
        else:  # keep the picture point at the centre of the view where it was
            self.x += (self.view_w - old_w) / 2
            self.y += (self.view_h - old_h) / 2
            self._clamp()

    def fit_scale(self, margin: int = 8) -> float:
        if self.width <= 0 or self.height <= 0:
            return 1.0
        s = min((self.view_w - margin) / self.width, (self.view_h - margin) / self.height, self.FIT_MAX)
        return max(s, self.MIN_SCALE)

    def fit(self) -> None:
        self.scale = self.fit_scale()
        self.x = (self.view_w - self.width * self.scale) / 2
        self.y = (self.view_h - self.height * self.scale) / 2
        self.fitted = True

    def actual_size(self, at: tuple[float, float] | None = None) -> None:
        """One picture pixel to one view pixel, about ``at`` (default: the view's centre)."""
        self.zoom_to(1.0, at)

    def zoom(self, factor: float, at: tuple[float, float] | None = None) -> None:
        """Multiply the scale by ``factor``, keeping the picture point under ``at`` fixed."""
        self.zoom_to(self.scale * factor, at)

    def zoom_to(self, scale: float, at: tuple[float, float] | None = None) -> None:
        cx, cy = at if at is not None else (self.view_w / 2, self.view_h / 2)
        new = min(max(scale, self.MIN_SCALE), self.MAX_SCALE)
        f = new / self.scale
        self.x = cx - (cx - self.x) * f
        self.y = cy - (cy - self.y) * f
        self.scale = new
        self.fitted = False
        self._clamp()

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.fitted = False
        self._clamp()

    def to_image(self, vx: float, vy: float) -> tuple[float, float]:
        """The picture point (in picture pixels) under a view position."""
        return ((vx - self.x) / self.scale, (vy - self.y) / self.scale)

    def to_view(self, ix: float, iy: float) -> tuple[float, float]:
        return (self.x + ix * self.scale, self.y + iy * self.scale)

    def rect(self) -> tuple[float, float, float, float]:
        """Where the picture lands in the view: x, y, width, height."""
        return (self.x, self.y, self.width * self.scale, self.height * self.scale)

    def _clamp(self) -> None:
        """Never let a pan or zoom carry the whole picture out of the view."""
        w, h = self.width * self.scale, self.height * self.scale
        keep_w, keep_h = min(self.KEEP, w), min(self.KEEP, h)
        self.x = min(max(self.x, keep_w - w), self.view_w - keep_w)
        self.y = min(max(self.y, keep_h - h), self.view_h - keep_h)


# --------------------------------------------------------------------------- 3D
def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a: Sequence[float], s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Sequence[float]) -> Vec:
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else (0.0, 0.0, 0.0)


def corners(bbox: tuple[Vec, Vec]) -> list[Vec]:
    (x0, y0, z0), (x1, y1, z1) = bbox
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


Axes = tuple[Vec, Vec, Vec]


def turntable_axes(yaw: float, pitch: float) -> Axes:
    """The screen's right, up and toward-the-eye axes, in model space, looking from
    ``yaw`` and ``pitch`` degrees as the turntable does: the right axis level, so it
    is defined looking straight down or up as well."""
    y, p = math.radians(yaw), math.radians(pitch)
    right = (math.cos(y), 0.0, -math.sin(y))
    back = (math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y))
    return right, _cross(right, _mul(back, -1.0)), back


def upright_angles(right: Sequence[float], back: Sequence[float]) -> tuple[float, float]:
    """The turntable's yaw and pitch (degrees) that look from the direction ``back``,
    upright: the same view without its roll. Looking straight down or up, where the
    direction gives no yaw, the yaw keeps the screen's ``right`` axis as it was."""
    pitch = math.degrees(math.asin(min(max(back[1], -1.0), 1.0)))
    if math.hypot(back[0], back[2]) > 1e-9:
        yaw = math.degrees(math.atan2(back[0], back[2]))
    else:
        yaw = math.degrees(math.atan2(-right[2], right[0]))
    return yaw % 360.0, pitch


def turned(v: Sequence[float], axis: Sequence[float], degrees: float) -> Vec:
    """``v`` turned ``degrees`` about the unit vector ``axis``, right-handed (Rodrigues)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    kxv, kdv = _cross(axis, v), _dot(axis, v)
    return (
        v[0] * c + kxv[0] * s + axis[0] * kdv * (1.0 - c),
        v[1] * c + kxv[1] * s + axis[1] * kdv * (1.0 - c),
        v[2] * c + kxv[2] * s + axis[2] * kdv * (1.0 - c),
    )


def orthonormal(right: Sequence[float], back: Sequence[float]) -> Axes | None:
    """Right, up and back made exactly perpendicular unit vectors again from a right and a
    back axis that rounding has bent a little; None when they are not two directions."""
    b = _unit(back)
    r = _unit(_sub(right, _mul(b, _dot(right, b))))
    if b == (0.0, 0.0, 0.0) or r == (0.0, 0.0, 0.0):
        return None
    return r, _cross(b, r), b


def snapped(axes: Axes) -> Axes:
    """Axes a turn by right angles left a rounding error away from whole numbers (a
    component within 1e-9 of -1, 0 or 1) made whole again, so a view stepped from face to
    face looks straight at each, however many steps it takes."""

    def snap(v: Sequence[float]) -> Vec:
        x, y, z = (float(round(c)) if abs(c - round(c)) < 1e-9 else float(c) for c in v)
        return (x, y, z)

    right, _up, back = axes
    return orthonormal(snap(right), snap(back)) or axes


# --------------------------------------------------------------------------- the view cube's regions
# The 26 directions the view cube offers, each a vector from the model toward the eye with
# components -1, 0 or 1: one nonzero for a face, two for an edge, three for a corner. The
# cube's faces are SOLIDWORKS's: Front on +Z, Top on +Y, Right on +X.
Region = tuple[int, int, int]
REGIONS: tuple[Region, ...] = tuple(
    (x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if (x, y, z) != (0, 0, 0)
)
FACES: dict[Region, str] = {
    (0, 0, 1): "front",
    (0, 0, -1): "back",
    (-1, 0, 0): "left",
    (1, 0, 0): "right",
    (0, 1, 0): "top",
    (0, -1, 0): "bottom",
}
ISOMETRIC: Region = (1, 1, 1)
_NAMED = {name: region for region, name in FACES.items()}


def region_angles(region: Sequence[float]) -> tuple[float, float]:
    """The turntable's yaw and pitch (degrees) that look from ``region`` toward the model,
    upright: yaw 0 straight above or below. For the six faces and the (1, 1, 1) corner these
    are exactly SOLIDWORKS's standard views (:data:`VIEWS`)."""
    x, y, z = (float(v) for v in region)
    length = math.sqrt(x * x + y * y + z * z)
    yaw = math.degrees(math.atan2(x, z)) % 360.0 if math.hypot(x, z) > 0 else 0.0
    return yaw, math.degrees(math.asin(min(max(y / length, -1.0), 1.0)))


def region_faces(region: Region) -> list[str]:
    """The faces a region touches: front or back first, then top or bottom, then left or
    right, as SOLIDWORKS names a view."""
    x, y, z = region
    out = []
    if z:
        out.append("front" if z > 0 else "back")
    if y:
        out.append("top" if y > 0 else "bottom")
    if x:
        out.append("right" if x > 0 else "left")
    return out


def region_name(region: Region) -> str:
    """``front``, ``front-top`` or ``front-top-right``: the faces joined by hyphens."""
    return "-".join(region_faces(region))


def parse_region(text: str) -> Region | None:
    """The region named by one, two or three faces joined by hyphens in any order
    (``top-front`` is ``front-top``); None when they name no region (a face and its
    opposite, a face twice, or a word that is not a face)."""
    words = [w.strip().lower() for w in text.split("-")]
    if not 1 <= len(words) <= 3 or len(set(words)) != len(words):
        return None
    out = [0, 0, 0]
    for word in words:
        face = _NAMED.get(word)
        if face is None:
            return None
        for i, v in enumerate(face):
            if v:
                if out[i]:
                    return None  # front and back, say
                out[i] = v
    return (out[0], out[1], out[2])


def region_text(region: Region) -> str:
    """The region in words, for its tooltip: ``Front``, ``Front and top edge``, ``Back, top
    and left corner``."""
    faces = [f.capitalize() if k == 0 else f for k, f in enumerate(region_faces(region))]
    if len(faces) == 1:
        return faces[0]
    if len(faces) == 2:
        return f"{faces[0]} and {faces[1]} edge"
    return f"{faces[0]}, {faces[1]} and {faces[2]} corner"


# --------------------------------------------------------------------------- quaternions
Quat = tuple[float, float, float, float]  # w, x, y, z


def quat_of_axes(axes: Axes) -> Quat:
    """The unit quaternion of the rotation whose matrix has the columns right, up and back
    (camera to model space)."""
    (m00, m10, m20), (m01, m11, m21), (m02, m12, m22) = axes
    trace = m00 + m11 + m22
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = (0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s)
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        q = ((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s)
    elif m11 > m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        q = ((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s)
    else:
        s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
        q = ((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s)
    n = math.sqrt(sum(v * v for v in q))
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def axes_of_quat(q: Quat) -> Axes:
    """Right, up and back: the columns of the unit quaternion ``q``'s rotation matrix."""
    w, x, y, z = q
    right = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    up = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))
    back = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return right, up, back


def quat_angle(a: Quat, b: Quat) -> float:
    """The angle (degrees) of the rotation from one orientation to the other."""
    d = abs(sum(p * q for p, q in zip(a, b, strict=True)))
    return math.degrees(2.0 * math.acos(min(d, 1.0)))


def slerp(a: Quat, b: Quat, t: float) -> Quat:
    """The orientation ``t`` (0 to 1) of the way from ``a`` to ``b``, the shorter way round,
    at a constant angular speed."""
    d = sum(p * q for p, q in zip(a, b, strict=True))
    if d < 0:  # q and -q are the same orientation: take the nearer
        b, d = tuple(-v for v in b), -d  # type: ignore[assignment]
    if d > 0.9995:  # nearly the same: a straight line is as good, and never divides by zero
        q = tuple(p + t * (q - p) for p, q in zip(a, b, strict=True))
    else:
        theta = math.acos(min(d, 1.0))
        s = math.sin(theta)
        wa, wb = math.sin((1 - t) * theta) / s, math.sin(t * theta) / s
        q = tuple(wa * p + wb * q for p, q in zip(a, b, strict=True))
    n = math.sqrt(sum(v * v for v in q))
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


NDCRect = tuple[float, float, float, float]  # x0, y0, x1, y1 in NDC
WHOLE_VIEW: NDCRect = (-1.0, -1.0, 1.0, 1.0)


class OrbitCamera:
    """An orthographic camera looking at ``target`` along the orientation it holds,
    showing ``half_height`` model units above and below the target, in a view
    ``aspect`` times as wide as it is high. The target is drawn at ``shift`` (NDC, the
    view's middle by default): a lens shift, so a fit can centre the model in the part
    of the view the legend leaves free (:attr:`free`) and the model still turns about
    its own centre there.

    ``mode`` is :data:`FREE` or :data:`TURNTABLE`. A turntable's orientation is
    ``yaw`` and ``pitch`` (degrees). A free camera's is its three axes (:attr:`axes`),
    turned about the screen's axes and made orthonormal again after every turn, so
    rounding never bends them; its ``yaw`` and ``pitch`` follow along as the upright
    view from the same direction (:func:`upright_angles`), which is what it shows on
    turning to a turntable.

    ``fitted`` stays true from :meth:`fit` (or :meth:`reset`, or a standard view)
    until the user rotates, pans or zooms, and :meth:`set_aspect` refits a fitted
    camera: the view can change shape after the model was first fitted, for
    example when its panel is laid out or resized."""

    MIN_HALF = 1e-7  # 0.1 micrometre: the display mesh is in metres
    ZOOM_OUT_LIMIT = 50.0  # times the model's size
    # A fit keeps the model's box out of :attr:`avoid` (the view cube's corner) unless that
    # draws it smaller than this share of the size it has in the free area: beside the cube a
    # model shaped like the view comes out 14 to 20 percent smaller.
    AVOID_SHARE = 0.8

    def __init__(self, bbox: tuple[Vec, Vec] | None = None, mode: str = FREE) -> None:
        self.bbox: tuple[Vec, Vec] = bbox or ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
        self.target: Vec = self.center
        self.mode = mode if mode in ROTATION_MODES else FREE
        self.yaw, self.pitch = ISO_YAW, ISO_PITCH
        self._axes: Axes = turntable_axes(self.yaw, self.pitch)  # a free camera's orientation
        self.half_height = self.radius
        self.aspect = 1.0
        self.fitted = False
        self.shift: tuple[float, float] = (0.0, 0.0)  # where the target is drawn, in NDC
        # The areas of the view a fit may centre the model in (NDC rectangles); the whole
        # view unless something covers part of it (:meth:`set_free`). And the area a fit
        # keeps the model's box out of when it can (the view cube's corner), or None.
        self.free: tuple[NDCRect, ...] = (WHOLE_VIEW,)
        self.avoid: NDCRect | None = None

    def copy(self) -> "OrbitCamera":
        """Another camera in the same state, to work out a view without moving this one."""
        c = OrbitCamera(self.bbox, mode=self.mode)
        c.target, c.yaw, c.pitch, c._axes = self.target, self.yaw, self.pitch, self._axes
        c.half_height, c.aspect, c.fitted = self.half_height, self.aspect, self.fitted
        c.shift, c.free, c.avoid = self.shift, self.free, self.avoid
        return c

    # -- the model -------------------------------------------------------------------
    @property
    def center(self) -> Vec:
        (x0, y0, z0), (x1, y1, z1) = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)

    @property
    def radius(self) -> float:
        """Half the bounding box's diagonal, never zero."""
        lo, hi = self.bbox
        return max(math.sqrt(_dot(_sub(hi, lo), _sub(hi, lo))) / 2, 1e-6)

    # -- the view's axes ---------------------------------------------------------------
    @property
    def axes(self) -> Axes:
        """The screen's right and up axes and the direction from the target toward the
        eye, in model space."""
        if self.mode == FREE:
            return self._axes
        return turntable_axes(self.yaw, self.pitch)

    @property
    def back(self) -> Vec:
        """From the target toward the eye."""
        return self.axes[2]

    @property
    def right(self) -> Vec:
        """The screen's x axis. A turntable keeps it level, whatever the pitch, so it is
        defined looking straight down or up as well."""
        return self.axes[0]

    @property
    def up(self) -> Vec:
        return self.axes[1]

    @property
    def eye(self) -> Vec:
        """Far enough back that the whole model is in front of it wherever the target is."""
        dist = math.sqrt(_dot(_sub(self.target, self.center), _sub(self.target, self.center)))
        return _add(self.target, _mul(self.back, dist + 2 * self.radius))

    def set_mode(self, mode: str) -> None:
        """Turn freely or as a turntable from now on. A free camera becomes the upright
        turntable view from the same direction; a turntable becomes a free camera with
        the same view. A fitted camera fits again."""
        if mode not in ROTATION_MODES or mode == self.mode:
            return
        if mode == FREE:
            self._axes = turntable_axes(self.yaw, self.pitch)
        self.mode = mode
        if self.fitted:
            self.fit()

    # -- moves ---------------------------------------------------------------------------
    def rotate(self, dx: float, dy: float, about: Sequence[float] | None = None) -> None:
        """Drag by ``dx``, ``dy`` pixels: right turns the model's front to the right,
        down tilts its top toward you; about the point ``about`` when given
        (:meth:`turn_model`)."""
        self.turn_model(dx * DEGREES_PER_PIXEL, dy * DEGREES_PER_PIXEL, about)

    def turn_model(self, across: float, down: float, about: Sequence[float] | None = None) -> None:
        """Turn the model as a drag would: ``across`` degrees as a drag to the right turns
        its front to the right, ``down`` degrees as a drag down tilts its top toward you.
        Free, it turns about the screen's vertical and horizontal axes (together, about
        the screen axis square to the drag) without limit; a turntable turns ``across``
        about the model's Y axis and tilts ``down`` up to straight above or below.

        Without ``about`` the model turns about the target. With a model point ``about``
        (the surface under the pointer) it turns about that point instead: the point
        keeps its place on the screen and its depth (:meth:`_kept`)."""
        if self.mode != FREE:
            self.turn(-across, down, about)
            return
        angle = math.hypot(across, down)
        if not angle:
            return
        kept = self._kept(about)
        right, up, back = self._axes
        axis = _unit(_add(_mul(right, down), _mul(up, across)))  # the model turns +angle about it
        axes = orthonormal(turned(right, axis, -angle), turned(back, axis, -angle))
        if axes is not None:
            self._axes = axes
            self.yaw, self.pitch = upright_angles(axes[0], axes[2])
        self._put(about, kept)
        self.fitted = False

    def turn(self, yaw: float, pitch: float, about: Sequence[float] | None = None) -> None:
        """A turntable adds ``yaw`` and ``pitch`` degrees; the pitch stops at straight
        above or below. A free camera turns the same way about the screen's axes. With
        ``about``, about that point (:meth:`turn_model`)."""
        if self.mode == FREE:
            self.turn_model(-yaw, pitch, about)
            return
        kept = self._kept(about)
        self.yaw = (self.yaw + yaw) % 360.0
        self.pitch = min(max(self.pitch + pitch, -PITCH_LIMIT), PITCH_LIMIT)
        self._put(about, kept)
        self.fitted = False

    def _kept(self, about: Sequence[float] | None) -> Vec | None:
        """Where the target lies from ``about``, along the screen's right, up and back."""
        if about is None:
            return None
        d = _sub(self.target, about)
        r, u, b = self.axes
        return (_dot(d, r), _dot(d, u), _dot(d, b))

    def _put(self, about: Sequence[float] | None, kept: Vec | None) -> None:
        """Put the target where it lay from ``about`` (:meth:`_kept`) along the new axes:
        ``about`` then keeps its place on the screen and its depth, so the model turns
        about it."""
        if about is None or kept is None:
            return
        r, u, b = self.axes
        self.target = _add(about, _add(_mul(r, kept[0]), _add(_mul(u, kept[1]), _mul(b, kept[2]))))

    def roll(self, degrees: float) -> bool:
        """Turn the model ``degrees`` counter-clockwise on the screen (clockwise when
        negative), about the line of sight through the target. A turntable never rolls:
        looking straight down or up, the same turn on the screen is a yaw, which it does;
        elsewhere it does nothing. Whether the view turned."""
        a = math.radians(degrees)
        c, s = math.cos(a), math.sin(a)
        right, up, back = self.axes
        new_right = _add(_mul(right, c), _mul(up, -s))
        if self.mode == FREE:
            axes = orthonormal(new_right, back)
            if axes is None:
                return False
            self._axes = axes
            self.yaw, self.pitch = upright_angles(axes[0], axes[2])
        else:
            if abs(abs(self.pitch) - PITCH_LIMIT) > 1e-9:
                return False
            self.yaw = math.degrees(math.atan2(-new_right[2], new_right[0])) % 360.0
        self.fitted = False
        return True

    def to_model_depth(self) -> None:
        """Set the point the view turns about at the depth of the model's centre: the
        target slides along the line of sight to the point at the target's place on the
        screen nearest the box's centre, which changes nothing on screen. A pan and a zoom
        do this and a turn does not, so the point stays fixed while the model turns: a
        drag turns it the same however many moves it arrives in, and turning back undoes
        a turn. Without it, once the view had turned after a pan the target lay in front
        of or behind the model, a later pan or zoom kept it there, and the next turn
        swung the model round that far point, out of view when zoomed in. A turn about a
        point under the pointer ends with it too."""
        b = self.back
        self.target = _add(self.target, _mul(b, _dot(_sub(self.center, self.target), b)))

    def units_per_pixel(self, view_h: float) -> float:
        return 2.0 * self.half_height / max(view_h, 1.0)

    def pan(self, dx: float, dy: float, view_h: float) -> None:
        """Drag by ``dx``, ``dy`` pixels: the model follows the cursor exactly, and the
        point it turns about is set again (:meth:`to_model_depth`)."""
        upp = self.units_per_pixel(view_h)
        self.target = _add(self.target, _add(_mul(self.right, -dx * upp), _mul(self.up, dy * upp)))
        self.to_model_depth()
        self.fitted = False

    def set_aspect(self, aspect: float) -> None:
        """The view's width over its height. A fitted camera refits to the new shape;
        otherwise the height shown stays and the width follows."""
        aspect = max(aspect, 1e-6)
        if aspect == self.aspect:
            return
        self.aspect = aspect
        if self.fitted:
            self.fit()

    def set_free(self, areas: Sequence[NDCRect] | None, avoid: NDCRect | None = None) -> None:
        """The areas of the view (NDC rectangles) a fit may centre the model in, the
        whole view with none, and the area it keeps the model's box out of where that
        costs little of its size (the view cube's corner, :func:`avoid_area`), or None.
        A fitted camera fits again at once; one the user moved stays where it is until
        the next fit."""
        free = tuple(tuple(float(v) for v in a) for a in areas or ()) or (WHOLE_VIEW,)
        away = tuple(float(v) for v in avoid) if avoid else None
        if free == self.free and away == self.avoid:
            return
        self.free = free  # type: ignore[assignment]
        self.avoid = away  # type: ignore[assignment]
        if self.fitted:
            self.fit()

    def point_at(self, nx: float, ny: float) -> Vec:
        """The point on the plane through the target, facing the eye, that lies under
        the NDC position ``(nx, ny)``."""
        hh = self.half_height
        sx, sy = self.shift
        return _add(
            self.target, _add(_mul(self.right, (nx - sx) * hh * self.aspect), _mul(self.up, (ny - sy) * hh))
        )

    def zoom(self, factor: float, at: tuple[float, float] = (0.0, 0.0)) -> None:
        """Magnify by ``factor`` (above 1 zooms in) toward the NDC position ``at``,
        which keeps the model point under it where it was; the point the model turns
        about is set again (:meth:`to_model_depth`)."""
        p = self.point_at(*at)
        new = min(max(self.half_height / factor, self.MIN_HALF), self.radius * self.ZOOM_OUT_LIMIT)
        f = new / self.half_height
        self.target = _add(p, _mul(_sub(self.target, p), f))
        self.to_model_depth()
        self.half_height = new
        self.fitted = False

    def fit(self, margin: float = 1.15) -> None:
        """Show the whole of the model's bounding box from the current direction, as large
        as it can be in one of the :attr:`free` areas (the first, of equals), centred
        there: the target is the box's centre and the shift puts it in that area's
        middle. Where the box would then reach into :attr:`avoid` (the view cube's corner:
        the box's outline as drawn, not the rectangle round it, which an isometric view
        leaves empty at its corners), it goes beside that instead, left of it or below it,
        whichever shows it larger, when it is drawn at least :data:`AVOID_SHARE` as large
        there."""
        c = self.center
        r, u = self.right, self.up
        offsets = [(_dot(_sub(k, c), r), _dot(_sub(k, c), u)) for k in corners(self.bbox)]
        ex = max(abs(x) for x, _y in offsets)
        ey = max(abs(y) for _x, y in offsets)
        aspect = max(self.aspect, 1e-6)
        floor = self.radius * 1e-3
        best = self._largest(self.free, ex, ey, floor) or (max(ey, ex / aspect, floor), (0.0, 0.0))
        avoid = self.avoid
        if avoid is not None:
            (sx, sy), hh = best[1], best[0] * margin
            outline = _hull([(sx + x / (hh * aspect), sy + y / hh) for x, y in offsets])
            if _meets(outline, avoid):
                clear = self._largest([b for a in self.free for b in _beside(a, avoid)], ex, ey, floor)
                if clear is not None and best[0] >= self.AVOID_SHARE * clear[0]:
                    best = clear
        self.target = c
        self.half_height = best[0] * margin
        self.shift = best[1]
        self.fitted = True

    def _largest(
        self, areas: Sequence[NDCRect], ex: float, ey: float, floor: float
    ) -> tuple[float, tuple[float, float]] | None:
        """Of ``areas``, the one that shows a box reaching ``ex`` and ``ey`` from its centre
        along the screen's right and up largest (the first, of equals): the half height
        that just holds it there, never below ``floor``, and the area's middle; None when
        no area has room."""
        aspect = max(self.aspect, 1e-6)
        best: tuple[float, tuple[float, float]] | None = None
        for x0, y0, x1, y1 in areas:
            half_w, half_h = (x1 - x0) / 2, (y1 - y0) / 2
            if half_w <= 0 or half_h <= 0:
                continue
            hh = max(ey / half_h, ex / (aspect * half_w), floor)
            if best is None or hh < best[0]:
                best = (hh, ((x0 + x1) / 2, (y0 + y1) / 2))
        return best

    def lost(self) -> bool:
        """Whether this camera has lost the model: none of its box in the free area, or the
        view zoomed out past :data:`ZOOM_OUT_LIMIT` times the model's size. The box test is
        generous: a box that reaches into the view keeps the camera even where no geometry
        is drawn there."""
        xs, ys = [], []
        for k in corners(self.bbox):
            x, y, _z = self.project(k)
            xs.append(x)
            ys.append(y)
        inside = any(
            min(xs) < x1 and max(xs) > x0 and min(ys) < y1 and max(ys) > y0 for x0, y0, x1, y1 in self.free
        )
        return not inside or self.half_height > self.radius * self.ZOOM_OUT_LIMIT

    def keep_in_view(self) -> bool:
        """After the model changed under a camera the user moved (another configuration):
        fit again from the same direction when the camera has lost the model (:meth:`lost`);
        otherwise keep the view as it is. Whether it fitted again."""
        if not self.lost():
            return False
        self.fit()
        return True

    def set_view(self, name: str) -> None:
        """One of :data:`VIEWS`, fitted: the same orientation in either mode."""
        self.yaw, self.pitch = VIEWS[name]
        self._axes = turntable_axes(self.yaw, self.pitch)
        self.fit()

    def look_from(self, region: Sequence[float]) -> None:
        """Look from the direction ``region`` (a view cube region), upright and fitted: for
        a face or the (1, 1, 1) corner exactly the standard view (:func:`region_angles`)."""
        self.yaw, self.pitch = region_angles(region)
        self._axes = turntable_axes(self.yaw, self.pitch)
        self.fit()

    def reset(self) -> None:
        """The isometric view, fitted: looking down the (1, 1, 1) diagonal with Y up."""
        self.set_view("isometric")

    # -- what Back keeps -----------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        """The direction the camera looks from (its axes, and the turntable's yaw and
        pitch, which a free camera keeps as the upright view from there), what it looks
        at, where on the view, how far it is zoomed, and whether it is fitted."""
        right, up, _back = self.axes
        return {
            "yaw": self.yaw,
            "pitch": self.pitch,
            "axes": [list(right), list(up)],
            "target": list(self.target),
            "half_height": self.half_height,
            "shift": list(self.shift),
            "fitted": self.fitted,
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Turn and zoom as :meth:`state` gave it. A free camera takes the axes when the
        state has them, else the yaw and pitch, as a turntable does; a fitted one fits
        what is shown now, from that direction, in the free area as it is now. A state
        without a shift (from before it was kept) has none."""
        self.yaw, self.pitch = float(state["yaw"]), float(state["pitch"])
        axes = _axes_of(state.get("axes")) if self.mode == FREE else None
        self._axes = axes or turntable_axes(self.yaw, self.pitch)
        if state.get("fitted"):
            self.fit()
        else:
            x, y, z = (float(v) for v in state["target"])
            self.target = (x, y, z)
            self.half_height = max(float(state["half_height"]), self.MIN_HALF)
            self.shift = _shift_of(state.get("shift"))
            self.fitted = False

    # -- matrices ------------------------------------------------------------------------
    def view_matrix(self) -> list[float]:
        r, u, b = self.axes
        e = self.eye
        return [
            r[0], r[1], r[2], -_dot(r, e),
            u[0], u[1], u[2], -_dot(u, e),
            b[0], b[1], b[2], -_dot(b, e),
            0.0, 0.0, 0.0, 1.0,
        ]  # fmt: skip

    def depth_range(self) -> tuple[float, float]:
        """Near and far distances from the eye that hold the whole model."""
        e, f = self.eye, _mul(self.back, -1.0)
        depths = [_dot(_sub(k, e), f) for k in corners(self.bbox)]
        pad = self.radius * 0.05
        return (max(min(depths) - pad, self.radius * 1e-3), max(depths) + pad)

    def projection_matrix(self) -> list[float]:
        """Orthographic, with the target drawn at :attr:`shift`."""
        hh, hw = self.half_height, self.half_height * self.aspect
        sx, sy = self.shift
        near, far = self.depth_range()
        return [
            1.0 / hw, 0.0, 0.0, sx,
            0.0, 1.0 / hh, 0.0, sy,
            0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near),
            0.0, 0.0, 0.0, 1.0,
        ]  # fmt: skip

    def project(self, point: Sequence[float]) -> Vec:
        """A model point in NDC: x and y on the screen, z from -1 (near) to 1 (far)."""
        v = mat_vec(self.view_matrix(), (*point, 1.0))
        p = mat_vec(self.projection_matrix(), v)
        return (p[0], p[1], p[2])


def _axes_of(raw: Any) -> Axes | None:
    """The axes a :meth:`OrbitCamera.state` holds (right and up), made orthonormal; None
    when they are missing or are not two directions."""
    try:
        right, up = ([float(v) for v in a] for a in raw)
    except (TypeError, ValueError):
        return None
    if len(right) != 3 or len(up) != 3 or not all(math.isfinite(v) for v in (*right, *up)):
        return None
    return orthonormal(right, _cross(right, up))


def _shift_of(raw: Any) -> tuple[float, float]:
    """The lens shift a state holds; none (0, 0) when it is missing or not two numbers."""
    try:
        sx, sy = (float(v) for v in raw)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    if not (math.isfinite(sx) and math.isfinite(sy)):
        return (0.0, 0.0)
    return (sx, sy)


FREE_GAP = 8  # pixels between the model's area and what covers the rest of the view
FREE_LEAST = 0.35  # an area narrower (or lower) than this share of the view is no place for the model


def free_areas(
    width: float,
    height: float,
    reserved: Sequence[tuple[float, float, float, float]],
    beside: Sequence[tuple[float, float, float, float]] = (),
) -> list[NDCRect]:
    """The areas of a ``width`` x ``height`` view a fit may centre the model in, as NDC
    rectangles, when ``reserved`` (rectangles x, y, width, height in pixels: the legend)
    covers the right of it: the column from the left of the leftmost of those, or of
    ``beside`` (the view cube, which is over the same corner), to the right edge, and
    from the top down to their bottom. The areas are the view left of that column, its
    full height, and the view below it, its full width, each :data:`FREE_GAP` pixels
    clear of it and dropped when it is narrower (or lower) than :data:`FREE_LEAST` of
    the view. Nothing reserved, or no area left: none, which means the whole view."""
    if not reserved or width <= 0 or height <= 0:
        return []
    left = min(x for x, _y, _w, _h in [*reserved, *beside])
    bottom = max(y + h for _x, y, _w, h in reserved)
    out: list[NDCRect] = []
    right = left - FREE_GAP
    if right >= FREE_LEAST * width:
        out.append((-1.0, -1.0, 2.0 * right / width - 1.0, 1.0))
    top = bottom + FREE_GAP
    if height - top >= FREE_LEAST * height:
        out.append((-1.0, -1.0, 1.0, 1.0 - 2.0 * top / height))
    return out


def avoid_area(width: float, height: float, rect: tuple[float, float, float, float]) -> NDCRect | None:
    """The area of a ``width`` x ``height`` view a fit keeps the model's box out of when it
    can (:meth:`OrbitCamera.fit`), as an NDC rectangle: the view cube's square ``rect`` (x,
    y, width, height in pixels, over the view's top-right corner), :data:`FREE_GAP` pixels
    wider to the left and lower, out to the view's top and right edges. None for an empty
    view."""
    if width <= 0 or height <= 0:
        return None
    x, y, _w, h = rect
    return (2.0 * (x - FREE_GAP) / width - 1.0, 1.0 - 2.0 * (y + h + FREE_GAP) / height, 1.0, 1.0)


def _hull(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """The convex hull of ``points``, counter-clockwise (Andrew's monotone chain); fewer
    than three points where they lie on a line or are one."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def turn(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _meets(polygon: Sequence[tuple[float, float]], rect: NDCRect) -> bool:
    """Whether the convex ``polygon`` and the rectangle ``rect`` overlap (more than touch):
    no axis of either separates them."""
    x0, y0, x1, y1 = rect
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    if max(xs) <= x0 or min(xs) >= x1 or max(ys) <= y0 or min(ys) >= y1:
        return False
    box = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for k, (ax, ay) in enumerate(polygon):
        bx, by = polygon[(k + 1) % len(polygon)]
        nx, ny = by - ay, ax - bx  # square to the edge
        if not (nx or ny):
            continue
        mine = [nx * px + ny * py for px, py in polygon]
        theirs = [nx * px + ny * py for px, py in box]
        if max(mine) <= min(theirs) or max(theirs) <= min(mine):
            return False
    return True


def _beside(area: NDCRect, avoid: NDCRect) -> list[NDCRect]:
    """The parts of ``area`` clear of ``avoid``: left of it and right of it, at the area's
    full height, and below it and above it, at its full width; those with no room left
    out."""
    x0, y0, x1, y1 = area
    a0, b0, a1, b1 = avoid
    parts = [
        (x0, y0, min(x1, a0), y1),
        (max(x0, a1), y0, x1, y1),
        (x0, y0, x1, min(y1, b0)),
        (x0, max(y0, b1), x1, y1),
    ]
    return [p for p in parts if p[2] > p[0] and p[3] > p[1]]


def unproject(camera: OrbitCamera, nx: float, ny: float, depth: float) -> Vec:
    """The model point drawn at the NDC position ``(nx, ny)`` at the window depth
    ``depth`` (0 near to 1 far, as the depth buffer holds it): :meth:`OrbitCamera.project`
    undone."""
    near, far = camera.depth_range()
    z_ndc = 2.0 * depth - 1.0
    z_eye = -(z_ndc * (far - near) + (far + near)) / 2.0  # the projection's third row, undone
    hh = camera.half_height
    sx, sy = camera.shift
    r, u, b = camera.axes
    across = _add(_mul(r, (nx - sx) * hh * camera.aspect), _mul(u, (ny - sy) * hh))
    return _add(camera.eye, _add(across, _mul(b, z_eye)))


DEPTH_STEPS = 255 * 65536  # the depth pass's 24 bits: the range from near to far in this many steps


def depth_bytes(z: float, rounded: Callable[[float], float] = float) -> tuple[int, int, int]:
    """The red, green and blue bytes the depth pass writes for the window depth ``z`` (0
    near to 1 far), worked out as its fragment shader works them out, ``rounded`` taking
    each result to the shader's float precision (by default Python's own): blue is
    floor(255 z), and green and red the next 16 bits of 255 z's fraction. No value on
    the way exceeds 256, so OpenGL ES, which may work in half precision (its largest
    number is 65504), cannot overflow; there the depth holds about 11 bits."""
    t = rounded(min(max(z, 0.0), 1.0) * 255.0)
    hi = math.floor(t)
    m = rounded(rounded(t - hi) * 256.0)
    mid = math.floor(m)
    return math.floor(rounded(rounded(m - mid) * 256.0)), mid, hi


def depth_of(r: int, g: int, b: int) -> float:
    """The window depth (0 to 1) a pixel of the depth pass holds (:func:`depth_bytes`)."""
    return min((r | (g << 8) | (b << 16)) / DEPTH_STEPS, 1.0)


# --------------------------------------------------------------------------- camera moves
MOVE_MIN_S, MOVE_MAX_S = 0.15, 0.5  # how long a camera move takes, at least and at most


class CameraMove:
    """The camera eased from where it is to ``end`` (a :meth:`OrbitCamera.state`), from
    time ``now`` (seconds, any clock): the view cube's clicks, Home and the standard
    views. A free camera turns the shorter way round at a steady angular speed
    (:func:`slerp`); a turntable turns its yaw the shorter way and tilts, so it stays
    upright throughout. The target and the shift slide, the zoom changes by a steady
    factor, all eased (:func:`.explode.ease`). It takes half a second for a half turn,
    a quarter for each doubling of the zoom, from :data:`MOVE_MIN_S` to
    :data:`MOVE_MAX_S`: on a slow frame it still ends on time, with fewer frames.

    A fitted end is worked out again on every step from the camera's box, shape and
    free area as they are then, so the move still lands fitted when the assembly
    explodes, the view is resized or the legend shows while it runs. Meanwhile the
    camera is not ``fitted``, so nothing refits it under the move."""

    def __init__(self, camera: OrbitCamera, end: dict[str, Any], now: float) -> None:
        self.end = dict(end)
        self.t0 = now
        self.start_q = quat_of_axes(camera.axes)
        self.start_yaw, self.start_pitch = camera.yaw, camera.pitch
        self.start_target, self.start_half, self.start_shift = camera.target, camera.half_height, camera.shift
        goal = self.goal(camera)
        self.end_q = quat_of_axes(goal.axes)
        self.angle = quat_angle(self.start_q, self.end_q)
        zoom = abs(math.log2(self._zoom(goal)))
        self.duration = min(max(0.5 * self.angle / 180.0, 0.25 * zoom, MOVE_MIN_S), MOVE_MAX_S)

    def _zoom(self, goal: OrbitCamera) -> float:
        """How many times the half height grows from the start to ``goal``: their ratio, both
        above zero (a fit keeps a model under a micrometre below :data:`OrbitCamera.MIN_HALF`,
        so that is no floor for either)."""
        return goal.half_height / self.start_half if self.start_half > 0 else 1.0

    def goal(self, camera: OrbitCamera) -> OrbitCamera:
        """The camera at the end of the move, as things are now."""
        c = camera.copy()
        c.set_state(self.end)
        return c

    def state(self, camera: OrbitCamera) -> dict[str, Any]:
        """Where the move ends, as :meth:`OrbitCamera.state` gives it."""
        return self.goal(camera).state()

    def done(self, now: float) -> bool:
        return now - self.t0 >= self.duration

    def apply(self, camera: OrbitCamera, now: float) -> bool:
        """Put the camera where the move is at ``now``; at the end, exactly at its end.
        Whether it has ended."""
        if self.done(now):
            self.finish(camera)
            return True
        k = ease((now - self.t0) / self.duration)
        goal = self.goal(camera)
        if camera.mode == FREE:
            right, _up, back = axes_of_quat(slerp(self.start_q, self.end_q, k))
            axes = orthonormal(right, back)
            if axes is not None:
                camera._axes = axes
                camera.yaw, camera.pitch = upright_angles(axes[0], axes[2])
        else:
            turn = (goal.yaw - self.start_yaw + 180.0) % 360.0 - 180.0
            camera.yaw = (self.start_yaw + k * turn) % 360.0
            camera.pitch = self.start_pitch + k * (goal.pitch - self.start_pitch)
        camera.target = _add(self.start_target, _mul(_sub(goal.target, self.start_target), k))
        camera.half_height = self.start_half * self._zoom(goal) ** k
        sx, sy = self.start_shift
        camera.shift = (sx + k * (goal.shift[0] - sx), sy + k * (goal.shift[1] - sy))
        camera.fitted = False
        return False

    def finish(self, camera: OrbitCamera) -> None:
        """Jump to the end."""
        camera.set_state(self.end)


# --------------------------------------------------------------------------- picking
PICK_RADIUS = 3  # a click this many pixels from an instance still picks it
CLICK_SLOP = 3  # pixels the pointer may move between pressing and releasing for a click
MAX_PICK = (1 << 24) - 1  # instances the 24 bits of a colour can number


def pick_color(index: int) -> tuple[int, int, int]:
    """The red, green and blue (0 to 255) the id pass draws instance ``index`` (from 0)
    in: ``index + 1``, its low byte in red, so black is no instance. The vertex shader
    makes the same three bytes from the number."""
    n = index + 1
    if not 0 < n <= MAX_PICK:
        raise ValueError(f"instance {index} cannot be numbered in 24 bits")
    return n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF


def pick_index(r: int, g: int, b: int) -> int | None:
    """The instance a pixel of the id pass shows, or None for none."""
    n = r | (g << 8) | (b << 16)
    return n - 1 if n else None


def pick_window(
    x: float, y: float, width: float, height: float, radius: int = PICK_RADIUS
) -> tuple[float, float, float, float, int]:
    """The square of ``2 * radius + 1`` pixels centred on the view position ``(x, y)``
    of a ``width`` x ``height`` view: its centre in NDC, its half width and half
    height in NDC, and its side in pixels. Drawn into a buffer of that side, each of
    its pixels is one pixel of the view, the middle one centred on ``(x, y)``."""
    side = 2 * radius + 1
    nx, ny = ndc(x, y, width, height)
    return nx, ny, side / max(width, 1.0), side / max(height, 1.0), side


def pick_projection(
    projection: Sequence[float], cx: float, cy: float, half_w: float, half_h: float
) -> list[float]:
    """``projection`` (row-major) narrowed to the NDC window centred on ``(cx, cy)``
    with half sizes ``half_w`` and ``half_h``, so that window fills the whole of NDC;
    depth is unchanged."""
    narrow = [
        1.0 / half_w, 0.0, 0.0, -cx / half_w,
        0.0, 1.0 / half_h, 0.0, -cy / half_h,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]  # fmt: skip
    return mat_mul(narrow, projection)


def nearest_index(values: Sequence[Any], side: int) -> int | None:
    """Of a ``side`` x ``side`` square of values, row by row, where the one nearest the
    middle pixel that is not None lies (the first in row order among equals); None when
    every one is None."""
    c = (side - 1) / 2
    best: tuple[float, int] | None = None
    for k, value in enumerate(values):
        if value is None:
            continue
        d = (k % side - c) ** 2 + (k // side - c) ** 2
        if best is None or d < best[0]:
            best = (d, k)
    return None if best is None else best[1]


def nearest_hit(ids: Sequence[int | None], side: int) -> int | None:
    """Of a ``side`` x ``side`` square of picked instances, row by row, the one nearest
    the middle pixel (the first in row order among equals); None when none is there."""
    k = nearest_index(ids, side)
    return None if k is None else ids[k]


def mat_vec(m: Sequence[float], v: Sequence[float]) -> tuple[float, float, float, float]:
    return tuple(sum(m[4 * i + j] * v[j] for j in range(4)) for i in range(4))  # type: ignore[return-value]


def mat_mul(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [sum(a[4 * i + k] * b[4 * k + j] for k in range(4)) for i in range(4) for j in range(4)]
