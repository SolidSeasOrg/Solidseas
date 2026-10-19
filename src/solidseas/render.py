"""Rendered previews of 3D models, in pure Python (provisional, ``docs/API.md`` 3.21).

:func:`render_preview` draws a model's :class:`~solidseas.formats.Scene` (or a
model document's, read with its display mesh preferred) from the format's Home
view into a PNG: an orthographic isometric view, a z-buffer, flat Lambert
shading with a light over the viewer's shoulder, a dark outline wherever the
depth steps, each object in its own colour or a neutral grey, on a transparent
background. Z points up for print meshes; a format whose models are Y-up
(STEP, Parasolid, Alibre Design) is turned Z-up first, so every Home view
looks down on the model from the front, right and above.

Bounds (:class:`~solidseas.formats.Limits`): ``render_side`` for the width and
height, ``render_triangles`` placed triangles drawn (the largest items first,
then an even sample of what is left; the rest counted), ``render_seconds`` of
drawing (then the image is returned as it stands, marked ``partial``) and,
for a B-rep format, a coarse tessellation of at most ``thumbnail_brep_seconds``
(a chord of 1/150 of the box diagonal, 30 degrees).

:class:`ThumbnailCache` keeps rendered PNGs in ``thumbnails.sqlite`` in the
user's cache folder beside the catalogs, keyed by the folded absolute path,
size and modification time of the file, the SolidSeas version and the render
settings, at most ``thumbnail_cache_bytes`` (least recently used dropped). Only
the parent process (the viewer, the command line) writes it; a damaged file is
made again. Nothing here imports Qt.
"""

import hashlib
import math
import os
import threading
import time
from array import array
from dataclasses import dataclass
from typing import Any

from . import __version__
from .errors import CatalogIncompatibleError, InvalidArgumentError, NoPreviewError, SldLimitError
from .formats._source import Clock, encode_png
from .formats.limits import Limits, check_limits

RENDER_VERSION = 1
DEFAULT_WIDTH = 256
DEFAULT_HEIGHT = 192
VIEWS = ("home",)
NEUTRAL = (0.72, 0.74, 0.77)
BREP_CHORD_FRACTION = 1.0 / 150.0
BREP_ANGLE_DEG = 30.0
_AMBIENT = 0.32
_DIFFUSE = 0.68
_OUTLINE = 0.35  # an outline pixel keeps this much of its colour
_EDGE_STEP = 0.02  # a depth step past this share of the model's depth draws an outline


@dataclass(frozen=True)
class Rendered:
    """A rendered preview: ``data`` (PNG, RGBA), its size, the placed triangles drawn and
    in the scene, and ``partial`` when some were left out (a bound, or a scene that
    was cut short)."""

    data: bytes
    width: int
    height: int
    drawn: int
    total: int
    partial: bool
    mime: str = "image/png"


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


# The Home view, Z up: from the front (-Y), the right (+X) and above.
_EYE = _unit((1.0, -1.0, 0.85))
_RIGHT = _unit(_cross((0.0, 0.0, 1.0), _EYE))
_UP = _cross(_EYE, _RIGHT)
_LIGHT = _unit((-0.1, 0.45, 0.89))  # in view coordinates: from above, a little left, towards the viewer


def _camera(up_axis: str) -> tuple[tuple[float, ...], ...]:
    """Rows taking a model point to (screen x, screen y, depth towards the viewer)."""
    rows = (_RIGHT, _UP, _EYE)
    if up_axis == "y":  # (x, y, z) Y-up is (x, -z, y) Z-up
        return tuple((r[0], r[2], -r[1]) for r in rows)
    return rows


def _check_size(value: Any, what: str, limits: Limits) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limits.render_side:
        raise InvalidArgumentError(
            f"{what} must be a whole number from 1 to {limits.render_side}", detail={"parameter": what}
        )
    return value


def _background(value: Any) -> tuple[int, int, int, int]:
    if value is None:
        return (0, 0, 0, 0)
    try:
        r, g, b = (int(c) for c in value)
    except (TypeError, ValueError):
        raise InvalidArgumentError(
            "background is three numbers from 0 to 255", detail={"parameter": "background"}
        ) from None
    if not all(0 <= c <= 255 for c in (r, g, b)):
        raise InvalidArgumentError(
            "background is three numbers from 0 to 255", detail={"parameter": "background"}
        )
    return (r, g, b, 255)


def scene_for_preview(doc: Any, limits: Limits, cancelled=None):
    """A model document's scene as a preview wants it: its display mesh first, and a
    coarse tessellation of a B-rep within ``thumbnail_brep_seconds``."""
    return doc.scene(
        prefer="display",
        chord_fraction=BREP_CHORD_FRACTION,
        angle_deg=BREP_ANGLE_DEG,
        max_seconds=limits.thumbnail_brep_seconds,
        cancelled=cancelled,
    )


def render_preview(
    scene_or_document: Any,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    view: str = "home",
    background: Any = None,
    up_axis: str | None = None,
    limits: Limits | None = None,
    cancelled=None,
) -> Rendered:
    """A PNG preview of a :class:`~solidseas.formats.Scene` or a model document (see the
    module notes). ``up_axis`` (``z`` or ``y``) defaults to the document's format's,
    and to ``z`` for a scene. ``background`` is None (transparent) or an RGB triple
    from 0 to 255. Raises :class:`~solidseas.errors.NoPreviewError` when the model holds
    no triangle to draw."""
    lim = check_limits(limits)
    width = _check_size(width, "width", lim)
    height = _check_size(height, "height", lim)
    if view not in VIEWS:
        raise InvalidArgumentError(f"view is one of {', '.join(VIEWS)}", detail={"parameter": "view"})
    bg = _background(background)
    scene = scene_or_document
    if hasattr(scene_or_document, "scene") and callable(scene_or_document.scene):
        if up_axis is None:
            spec = getattr(scene_or_document, "spec", None)
            up_axis = getattr(spec, "up_axis", "z")
        scene = scene_for_preview(scene_or_document, lim, cancelled)
    up_axis = up_axis or "z"
    if up_axis not in ("z", "y"):
        raise InvalidArgumentError("up_axis is z or y", detail={"parameter": "up_axis"})
    clock = Clock(lim.render_seconds, cancelled, limit="render_seconds")
    return _render(scene, width, height, up_axis, bg, lim, clock)


def _pick(scene, budget: int) -> tuple[list[tuple[Any, int]], int]:
    """The items to draw with a sampling step each, largest first, and the placed total."""
    sizes = [(scene.objects[it.object].n_triangles, i) for i, it in enumerate(scene.items)]
    total = sum(n for n, _i in sizes)
    picks: list[tuple[Any, int]] = []
    left = budget
    for n, i in sorted(sizes, key=lambda t: -t[0]):
        if n == 0 or left <= 0:
            continue
        step = 1 if n <= left else -(-n // left)
        picks.append((scene.items[i], step))
        left -= -(-n // step)
    return picks, total


def _render(scene, width: int, height: int, up_axis: str, bg, lim: Limits, clock: Clock) -> Rendered:
    picks, total = _pick(scene, lim.render_triangles)
    if not picks:
        raise NoPreviewError("the model holds no triangles to draw")
    cam = _camera(up_axis)
    # Each drawn item: its view transform, and its vertices in view coordinates when every
    # one is drawn (a sampled item's are worked out per triangle, so a sampled million-
    # triangle soup costs only what is drawn). The frame comes from the objects' boxes.
    views: list[tuple[Any, ...]] = []
    lo_x = lo_y = lo_z = math.inf
    hi_x = hi_y = hi_z = -math.inf
    for item, step in picks:
        obj = scene.objects[item.object]
        r, t = item.placement.rotation, item.placement.translation_m
        m = [[sum(cam[i][k] * r[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        o = [sum(cam[i][k] * t[k] for k in range(3)) for i in range(3)]
        p = obj.positions
        if not p:
            continue
        (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = m
        box = [(min(p[i::3]), max(p[i::3])) for i in range(3)]
        for x in box[0]:
            for y in box[1]:
                for z in box[2]:
                    vx = a0 * x + a1 * y + a2 * z + o[0]
                    vy = b0 * x + b1 * y + b2 * z + o[1]
                    vz = c0 * x + c1 * y + c2 * z + o[2]
                    lo_x, hi_x = min(lo_x, vx), max(hi_x, vx)
                    lo_y, hi_y = min(lo_y, vy), max(hi_y, vy)
                    lo_z, hi_z = min(lo_z, vz), max(hi_z, vz)
        views.append((m, o, obj, step, obj.color))
    if not all(math.isfinite(v) for v in (lo_x, hi_x, lo_y, hi_y, lo_z, hi_z)):
        raise NoPreviewError("the model's coordinates are not finite")
    span = max(hi_x - lo_x, hi_y - lo_y) or 1.0
    scale = 0.9 * min(width / max(hi_x - lo_x, span * 1e-9), height / max(hi_y - lo_y, span * 1e-9))
    ox = (width - scale * (hi_x - lo_x)) / 2.0 - scale * lo_x
    oy = (height - scale * (hi_y - lo_y)) / 2.0 - scale * lo_y
    depth = (hi_z - lo_z) or span
    n_pix = width * height
    zbuf = array("d", [-math.inf]) * n_pix
    cbuf = array("I", bytes(4 * n_pix))  # each pixel's colour, an index into palette; 0 the background
    palette = [bytes(bg)]
    colours: dict[bytes, int] = {}
    lx, ly, lz = _LIGHT
    drawn = 0
    partial = bool(getattr(scene, "truncated", ())) or False
    ceil, floor = math.ceil, math.floor
    try:
        for m, o, obj, step, rgba in views:
            base = rgba[:3] if rgba is not None else NEUTRAL
            alpha = int(round(255 * (rgba[3] if rgba is not None else 1.0)))
            # pixels: x right, y down, z towards the viewer, all in pixel units
            (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = m
            a0, a1, a2, ta = a0 * scale, a1 * scale, a2 * scale, o[0] * scale + ox
            b0, b1, b2, tb = -b0 * scale, -b1 * scale, -b2 * scale, height - (o[1] * scale + oy)
            c0, c1, c2, tc = c0 * scale, c1 * scale, c2 * scale, o[2] * scale
            p = obj.positions
            if step == 1:
                sx, sy, sz = [], [], []
                for k in range(0, len(p), 3):
                    x, y, z = p[k], p[k + 1], p[k + 2]
                    sx.append(a0 * x + a1 * y + a2 * z + ta)
                    sy.append(b0 * x + b1 * y + b2 * z + tb)
                    sz.append(c0 * x + c1 * y + c2 * z + tc)
                    if not k % 12288:
                        clock.check()
            t = obj.triangles
            for k in range(0, len(t), 3 * step):
                a, b, c = t[k], t[k + 1], t[k + 2]
                if step == 1:
                    ax, ay, az = sx[a], sy[a], sz[a]
                    bx, by, bz = sx[b], sy[b], sz[b]
                    cx, cy, cz = sx[c], sy[c], sz[c]
                else:
                    x, y, z = p[3 * a], p[3 * a + 1], p[3 * a + 2]
                    ax, ay, az = (
                        a0 * x + a1 * y + a2 * z + ta,
                        b0 * x + b1 * y + b2 * z + tb,
                        c0 * x + c1 * y + c2 * z + tc,
                    )
                    x, y, z = p[3 * b], p[3 * b + 1], p[3 * b + 2]
                    bx, by, bz = (
                        a0 * x + a1 * y + a2 * z + ta,
                        b0 * x + b1 * y + b2 * z + tb,
                        c0 * x + c1 * y + c2 * z + tc,
                    )
                    x, y, z = p[3 * c], p[3 * c + 1], p[3 * c + 2]
                    cx, cy, cz = (
                        a0 * x + a1 * y + a2 * z + ta,
                        b0 * x + b1 * y + b2 * z + tb,
                        c0 * x + c1 * y + c2 * z + tc,
                    )
                area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                drawn += 1
                if area == 0.0:
                    continue
                ux, uy, uz = bx - ax, ay - by, bz - az
                vx, vy, vz = cx - ax, ay - cy, cz - az
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                shade = _AMBIENT + _DIFFUSE * abs(nx * lx + ny * ly + nz * lz) / ln
                pix = bytes(
                    (
                        min(255, int(base[0] * shade * 255)),
                        min(255, int(base[1] * shade * 255)),
                        min(255, int(base[2] * shade * 255)),
                        alpha,
                    )
                )
                pid = colours.get(pix)
                if pid is None:
                    pid = colours[pix] = len(palette)
                    palette.append(pix)
                # depth on the triangle's plane: z = A x + B y + C, in pixels
                dz_x = ((bz - az) * (cy - ay) - (by - ay) * (cz - az)) / area
                dz_y = ((bx - ax) * (cz - az) - (bz - az) * (cx - ax)) / area
                z0 = az - dz_x * ax - dz_y * ay
                (x0, y0), (x1, y1), (x2, y2) = sorted(((ax, ay), (bx, by), (cx, cy)), key=lambda q: q[1])
                top = max(0, ceil(y0 - 0.5))
                bottom = min(height - 1, floor(y2 - 0.5))
                covered = 0
                clock.tick(64 + max(0, bottom - top + 1) * 16)
                for y in range(top, bottom + 1):  # rows whose centre the triangle spans
                    py = y + 0.5
                    xa = x0 + (x2 - x0) * (py - y0) / (y2 - y0)
                    if py < y1:
                        xb = x0 + (x1 - x0) * (py - y0) / (y1 - y0)
                    else:
                        xb = x1 + (x2 - x1) * (py - y1) / (y2 - y1) if y2 > y1 else x1
                    if xa > xb:
                        xa, xb = xb, xa
                    left = max(0, ceil(xa - 0.5))
                    right = min(width - 1, floor(xb - 0.5))
                    if left > right:
                        continue
                    covered += right - left + 1
                    z = dz_x * (left + 0.5) + dz_y * py + z0
                    first = y * width + left
                    for j in range(first, first + right - left + 1):
                        if z > zbuf[j]:
                            zbuf[j] = z
                            cbuf[j] = pid
                        z += dz_x
                if not covered:  # it falls between pixel centres: a dot where its centre is
                    px, py = int((ax + bx + cx) / 3.0), int((ay + by + cy) / 3.0)
                    if 0 <= px < width and 0 <= py < height:
                        j = py * width + px
                        zz = (az + bz + cz) / 3.0
                        if zz > zbuf[j]:
                            zbuf[j] = zz
                            cbuf[j] = pid
    except SldLimitError:
        partial = True  # render_seconds: the image as it stands
    if drawn < total:
        partial = True
    color = bytearray(b"".join([palette[i] for i in cbuf]))
    _outline(color, zbuf, width, height, _EDGE_STEP * depth * scale)
    return Rendered(encode_png(width, height, bytes(color), 4), width, height, drawn, total, partial)


def _outline(color: bytearray, zbuf: array, width: int, height: int, step: float) -> None:
    """Darken every drawn pixel beside an empty one or a depth step."""
    inf = -math.inf
    edges = []
    for y in range(height):
        row = y * width
        for x in range(width):
            j = row + x
            z = zbuf[j]
            if z == inf:
                continue
            for k in (j - 1 if x else -1, j + 1 if x + 1 < width else -1, j - width, j + width):
                if k < 0 or k >= len(zbuf):
                    continue
                zn = zbuf[k]
                if zn == inf or zn - z > step:  # empty, or something nearer steps over this one
                    edges.append(j)
                    break
    for j in edges:
        i = 4 * j
        color[i] = int(color[i] * _OUTLINE)
        color[i + 1] = int(color[i + 1] * _OUTLINE)
        color[i + 2] = int(color[i + 2] * _OUTLINE)


# --------------------------------------------------------------------------- the cache
THUMBNAIL_FILE = "thumbnails.sqlite"
APPLICATION_ID = 0x53535448  # "SSTH"


def _fold(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).casefold()


class ThumbnailCache:
    """Rendered previews kept between runs (see the module notes). Every method answers
    None or does nothing when the cache cannot be used (no ``sqlite3``, a file that
    belongs to another program); a damaged file is removed and made again."""

    def __init__(self, path: str | None = None, *, max_bytes: int | None = None) -> None:
        if path is None:
            from .catalog.store import cache_dir

            path = os.path.join(cache_dir(), THUMBNAIL_FILE)
        self.path = os.path.abspath(path)
        self.max_bytes = max_bytes if max_bytes is not None else Limits().thumbnail_cache_bytes
        self._lock = threading.Lock()
        self._con = None
        self._disabled = False

    @staticmethod
    def key(path: str, size: int, mtime_ns: int, settings: str = "") -> str:
        """The cache key of one file's preview with these render ``settings``."""
        text = "\n".join((_fold(path), str(size), str(mtime_ns), __version__, str(RENDER_VERSION), settings))
        return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()

    def _open_db(self):
        """A connection to the cache file, its table made; the connection is closed again
        when the file turns out damaged (``sqlite3.DatabaseError``)."""
        import sqlite3

        con = sqlite3.connect(self.path, timeout=2.0, check_same_thread=False)
        try:
            con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            con.execute(
                "CREATE TABLE IF NOT EXISTS thumbs (key TEXT PRIMARY KEY, png BLOB NOT NULL, "
                "bytes INTEGER NOT NULL, used REAL NOT NULL)"
            )
            con.execute("SELECT COUNT(*) FROM thumbs").fetchone()
            con.commit()
        except BaseException:
            con.close()
            raise
        return con

    def _connect(self):
        if self._con is not None or self._disabled:
            return self._con
        try:
            import sqlite3
        except ImportError:
            self._disabled = True
            return None
        from .catalog.store import file_application_id, make_private_dir

        try:
            make_private_dir(os.path.dirname(self.path))
            if os.path.lexists(self.path) and (os.path.islink(self.path) or not os.path.isfile(self.path)):
                self._disabled = True
                return None
            try:
                app = file_application_id(self.path) if os.path.exists(self.path) else None
            except CatalogIncompatibleError:  # not SQLite at all: a damaged cache file
                app = APPLICATION_ID
                self._remove_files()
            if app not in (None, 0, APPLICATION_ID):
                self._disabled = True  # another program's database: never touched
                return None
            try:
                self._con = self._open_db()
            except sqlite3.DatabaseError:
                self._rebuild()
        except (OSError, CatalogIncompatibleError):
            self._disabled = True
        return self._con

    def _remove_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    def _rebuild(self) -> None:
        """Remove a damaged cache file and make it again; the cache is off when that fails."""
        import sqlite3

        self.close()
        try:
            self._remove_files()
            self._con = self._open_db()
        except (OSError, sqlite3.DatabaseError):
            self._disabled = True

    def get(self, path: str, size: int, mtime_ns: int, settings: str = "") -> bytes | None:
        import sqlite3

        with self._lock:
            con = self._connect()
            if con is None:
                return None
            k = self.key(path, size, mtime_ns, settings)
            try:
                row = con.execute("SELECT png FROM thumbs WHERE key = ?", (k,)).fetchone()
                if row is None:
                    return None
                con.execute("UPDATE thumbs SET used = ? WHERE key = ?", (time.time(), k))
                con.commit()
                return bytes(row[0])
            except sqlite3.DatabaseError:
                self._rebuild()
                return None

    def put(self, path: str, size: int, mtime_ns: int, png: bytes, settings: str = "") -> None:
        import sqlite3

        if len(png) > self.max_bytes:
            return
        with self._lock:
            con = self._connect()
            if con is None:
                return
            k = self.key(path, size, mtime_ns, settings)
            try:
                con.execute(
                    "INSERT OR REPLACE INTO thumbs (key, png, bytes, used) VALUES (?, ?, ?, ?)",
                    (k, png, len(png), time.time()),
                )
                (total,) = con.execute("SELECT COALESCE(SUM(bytes), 0) FROM thumbs").fetchone()
                if total > self.max_bytes:
                    goal = int(self.max_bytes * 0.9)
                    rows = con.execute("SELECT key, bytes FROM thumbs ORDER BY used").fetchall()
                    drop = []
                    for key, n in rows:
                        if total <= goal:
                            break
                        drop.append((key,))
                        total -= n
                    con.executemany("DELETE FROM thumbs WHERE key = ?", drop)
                con.commit()
            except sqlite3.DatabaseError:
                self._rebuild()

    def size(self) -> int:
        """The bytes of PNG the cache holds."""
        with self._lock:
            con = self._connect()
            if con is None:
                return 0
            (total,) = con.execute("SELECT COALESCE(SUM(bytes), 0) FROM thumbs").fetchone()
            return int(total)

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            finally:
                self._con = None


__all__ = [
    "APPLICATION_ID",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "RENDER_VERSION",
    "THUMBNAIL_FILE",
    "Rendered",
    "ThumbnailCache",
    "render_preview",
    "scene_for_preview",
]
