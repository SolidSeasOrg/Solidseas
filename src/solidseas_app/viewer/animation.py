"""Save Animation's plan: what each frame of a clip shows (``docs/EXTENSIONS.md`` section 9,
video export). Nothing here imports Qt, so it is tested everywhere.

:class:`AnimationOptions` holds what the person chose: length and frame rate, the size,
how far the camera circles the model and which way, a zoom and a pan over the clip,
when the assembly explodes and collapses and how far, the background and the format.
:func:`frames` turns them and the camera the 3D view shows into one :class:`Frame` a
frame: the camera's yaw (circling about the up axis from where it starts), its pitch
(kept), its zoom and pan, and the explode amount, which eases out and back as Play does.
The 3D view draws each frame offscreen at the size chosen; the video extension's helper
encodes them.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

SIZES = {"640x360": (640, 360), "1280x720": (1280, 720), "1920x1080": (1920, 1080), "800x800": (800, 800)}
FORMATS = ("mp4", "gif")
MAX_SECONDS = 60
MAX_FRAMES = 3600
_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


class OptionsError(ValueError):
    """An option Save Animation refuses, in words."""


@dataclass(frozen=True)
class AnimationOptions:
    seconds: float = 6.0
    fps: int = 30
    size: str = "1280x720"
    orbit_degrees: float = 360.0
    clockwise: bool = True
    zoom: float = 1.0  # the zoom at the end against the start: 1.2 is 20 percent closer
    pan: tuple[float, float] = (0.0, 0.0)  # how far the view moves over the clip, in view heights
    explode: float = 1.0  # how far the assembly explodes (0 to 1); 0 does not explode
    explode_from: float = 0.2  # when it starts to explode, as a share of the clip
    collapse_from: float = 0.65  # when it starts to collapse again
    move: float = 0.15  # how long each move takes, as a share of the clip
    background: str = "#ffffff"
    format: str = "mp4"

    def __post_init__(self) -> None:
        def number(value: Any, lo: float, hi: float, what: str) -> None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
                raise OptionsError(f"{what} is a number from {lo:g} to {hi:g}")

        number(self.seconds, 0.5, MAX_SECONDS, "the length in seconds")
        if not isinstance(self.fps, int) or isinstance(self.fps, bool) or not 5 <= self.fps <= 60:
            raise OptionsError("the frame rate is a whole number from 5 to 60")
        if self.size not in SIZES:
            raise OptionsError(f"the size is one of {', '.join(SIZES)}")
        number(self.orbit_degrees, 0, 1440, "the degrees the camera circles")
        number(self.zoom, 0.25, 4.0, "the zoom at the end")
        if not (isinstance(self.pan, tuple) and len(self.pan) == 2):
            raise OptionsError("the pan is two numbers")
        for p in self.pan:
            number(p, -2.0, 2.0, "the pan")
        number(self.explode, 0.0, 1.0, "how far it explodes")
        number(self.explode_from, 0.0, 1.0, "when it explodes")
        number(self.collapse_from, 0.0, 1.0, "when it collapses")
        number(self.move, 0.01, 1.0, "how long each move takes")
        if self.explode and self.collapse_from < self.explode_from:
            raise OptionsError("the assembly collapses after it explodes")
        if not isinstance(self.background, str) or not _COLOUR.fullmatch(self.background):
            raise OptionsError("the background is a colour such as #ffffff")
        if self.format not in FORMATS:
            raise OptionsError(f"the format is one of {', '.join(FORMATS)}")
        if self.frame_count > MAX_FRAMES:
            raise OptionsError(f"a clip has at most {MAX_FRAMES} frames")

    @property
    def frame_count(self) -> int:
        return max(1, round(self.seconds * self.fps))

    @property
    def pixels(self) -> tuple[int, int]:
        return SIZES[self.size]


@dataclass(frozen=True)
class Frame:
    """One frame: the camera (yaw and pitch in degrees, ``half_height`` and ``target`` as
    :meth:`.viewmath.OrbitCamera.state` holds them) and the explode amount."""

    index: int
    yaw: float
    pitch: float
    half_height: float
    target: tuple[float, float, float]
    explode: float


def ease(t: float) -> float:
    """Smooth start and stop, as the explode bar eases."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _right_and_up(yaw: float, pitch: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The screen's right and up in model axes for a turntable camera (Z up)."""
    y, p = math.radians(yaw), math.radians(pitch)
    right = (math.cos(y), -math.sin(y), 0.0)
    up = (-math.sin(p) * math.sin(y), -math.sin(p) * math.cos(y), math.cos(p))
    return right, up


def frames(options: AnimationOptions, camera: dict[str, Any]) -> list[Frame]:
    """Every frame of the clip, from the camera the view shows (its ``state()``)."""
    n = options.frame_count
    yaw0 = float(camera.get("yaw", 45.0))
    pitch = float(camera.get("pitch", 35.26))
    half0 = float(camera.get("half_height", 1.0))
    target0 = tuple(float(v) for v in camera.get("target", (0.0, 0.0, 0.0)))
    sign = -1.0 if options.clockwise else 1.0
    out = []
    for i in range(n):
        t = i / max(n - 1, 1)
        yaw = (yaw0 + sign * options.orbit_degrees * t) % 360.0
        zoom = options.zoom**t
        half = half0 / zoom
        right, up = _right_and_up(yaw, pitch)
        dx, dy = (options.pan[0] * t * 2 * half0, options.pan[1] * t * 2 * half0)
        target = tuple(target0[k] - dx * right[k] - dy * up[k] for k in range(3))
        explode = 0.0
        if options.explode:
            out_part = ease((t - options.explode_from) / options.move)
            back = ease((t - options.collapse_from) / options.move)
            explode = options.explode * max(0.0, out_part - back)
        out.append(Frame(i, yaw, pitch, half, target, round(explode, 6)))
    return out


def steady_framing(
    planned: list[Frame],
    fitted_half: Callable[[float, float, float], float],
    centre_at: Callable[[float], tuple[float, float, float]],
) -> list[Frame]:
    """``planned`` framed so the exploded assembly stays in the picture: every frame zoomed
    out by one factor, the most any frame's explode needs (``fitted_half(yaw, pitch,
    amount)`` is the half height that fits the assembly exploded by ``amount`` from that
    direction), so the clip does not pump in and out; and each frame's target moved with
    the exploded box's centre (``centre_at(amount)``)."""
    if not any(f.explode for f in planned):
        return planned
    ratio = 1.0
    for f in planned:
        if f.explode:
            base = fitted_half(f.yaw, f.pitch, 0.0)
            if base > 0:
                ratio = max(ratio, fitted_half(f.yaw, f.pitch, f.explode) / base)
    c0 = centre_at(0.0)
    out = []
    for f in planned:
        c = centre_at(f.explode) if f.explode else c0
        target = tuple(f.target[k] + c[k] - c0[k] for k in range(3))
        out.append(replace(f, half_height=f.half_height * ratio, target=target))
    return out


def with_format(options: AnimationOptions, path: str) -> AnimationOptions:
    """``options`` with the format the file name asks for (``.gif`` or ``.mp4``)."""
    lower = path.lower()
    for f in FORMATS:
        if lower.endswith("." + f):
            return replace(options, format=f)
    return options


__all__ = [
    "FORMATS",
    "SIZES",
    "AnimationOptions",
    "Frame",
    "OptionsError",
    "ease",
    "frames",
    "steady_framing",
    "with_format",
]
