"""The Gridfinity tools a chat uses, served beside the SOLIDWORKS ones by
:mod:`solidseas_app.assistant.mcp_server` (``docs/GRIDFINITY.md``).

* ``gridfinity_photos`` lists the photos in the person's Gridfinity photos folder.
* ``gridfinity_trace`` has Tracefinity trace the tools in one of them, the paper giving the
  scale, and returns each outline's size and a drawing of them, numbered.
* ``gridfinity_save_tools`` saves the outlines that are tools into Tracefinity's library,
  named, each with a finger scoop unless asked not to; ``gridfinity_tools`` lists the
  library and ``gridfinity_edit_tool`` renames a tool or adds or takes off its scoop.
* ``gridfinity_make_bin`` lays tools out in the smallest bin they fit (:mod:`.layout`), has
  Tracefinity make it, and saves its STL in the person's bins folder (with the zip of its
  parts when it is larger than the printer's bed, and a 3MF when it has a label). A label
  (:mod:`.labels`) goes along the bin's back edge, with room kept for it in the layout, or
  on the floor of each pocket, as big as fits.

What the chat chooses is checked before it is used: a photo is named by a file that is in
the photos folder itself (a plain file, not a link), ids are checked before they become part
of a Tracefinity path, and a bin's name becomes part of a file name in the bins folder only
after everything but letters, digits, spaces and ``_-.,()+`` is taken out. Files are never
written over. Replies name folders under the person's profile as ``%USERPROFILE%``.
"""

from __future__ import annotations

import math
import os
import stat
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from solidseas.ai.http import Cancel

from . import labels
from .drawings import bin_drawing, trace_drawing
from .labels import Label, LabelError
from .layout import (
    BIN_GAP,
    GRID,
    HEIGHT_UNIT,
    MAX_HEIGHT_UNITS,
    MAX_UNITS,
    WALL,
    Hole,
    Layout,
    LayoutError,
    Shape,
    area,
    finger_scoop,
    height_units_for,
    inset,
    interior,
    lay_out,
    long_side_angle,
    max_depth,
    mean,
    placed_about,
    placed_points,
    size,
    units_for,
)
from .tracefinity import CONTENT_TYPES, MAX_PHOTO_BYTES, PAPER_SIZES, Tracefinity, TracefinityError, segment

PHOTOS_ENV = "SOLIDSEAS_GRIDFINITY_PHOTOS"
BINS_ENV = "SOLIDSEAS_GRIDFINITY_BINS"
MAX_PHOTOS_LISTED = 40
MAX_TOOLS_LISTED = 200
MAX_BIN_TOOLS = 40
MAX_NAME = 60
SCOOP_ID = "solidseas-scoop"  # the start of the id of a finger scoop SolidSeas placed
_UNSAFE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

_PHOTO = {"type": "string", "description": "a photo's file name from gridfinity_photos"}
_TRACE = {"type": "string", "description": "the trace id gridfinity_trace returned"}
_TOOL = {"type": "string", "description": "a tool id from gridfinity_save_tools or gridfinity_tools"}
_WRITES = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
TOOLS: list[dict[str, Any]] = [
    {
        "name": "gridfinity_photos",
        "title": "Gridfinity: photos",
        "description": (
            "List the photos in the person's Gridfinity photos folder, newest first. Each should show "
            "tools lying flat on a sheet of paper of a known size, all four of its corners in view."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "gridfinity_trace",
        "title": "Gridfinity: trace the tools in a photo",
        "description": (
            "Trace the tools in a photo with the person's Tracefinity: the paper's corners give the scale "
            "and take out the perspective. Returns each outline's length, width and area in mm and a "
            "drawing of the outlines, numbered. Takes seconds. Nothing is saved yet: save the "
            "outlines that are tools with gridfinity_save_tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "photo": _PHOTO,
                "paper": {
                    "type": "string",
                    "enum": list(PAPER_SIZES),
                    "description": "the sheet under the tools; ask the person if you do not know",
                },
            },
            "required": ["photo", "paper"],
            "additionalProperties": False,
        },
        "annotations": _WRITES,
    },
    {
        "name": "gridfinity_save_tools",
        "title": "Gridfinity: save traced tools",
        "description": (
            "Save outlines from a trace into the tool library, each with a name and, unless "
            "finger_scoop is false, a round finger scoop so the tool can be lifted out of its pocket."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": _TRACE,
                "tools": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_BIN_TOOLS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "outline": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "its number in the trace",
                            },
                            "name": {"type": "string", "maxLength": 200},
                            "finger_scoop": {"type": "boolean", "default": True},
                        },
                        "required": ["outline", "name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["trace", "tools"],
            "additionalProperties": False,
        },
        "annotations": _WRITES,
    },
    {
        "name": "gridfinity_tools",
        "title": "Gridfinity: the tool library",
        "description": "List the tools in the library, newest first: id, name, length and width in mm.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "gridfinity_edit_tool",
        "title": "Gridfinity: rename a tool or change its scoop",
        "description": (
            "Rename a library tool, or add (true) or take off (false) the finger scoop SolidSeas places. "
            "Bins made later use the change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": _TOOL,
                "name": {"type": "string", "maxLength": 200},
                "finger_scoop": {"type": "boolean"},
            },
            "required": ["tool"],
            "additionalProperties": False,
        },
        "annotations": _WRITES,
    },
    {
        "name": "gridfinity_make_bin",
        "title": "Gridfinity: make a bin",
        "description": (
            "Lay tools out in the smallest Gridfinity bin they fit (or the grid asked for), each in a "
            "pocket of its outline, have Tracefinity make the bin, and save its STL in the "
            "person's bins folder. Returns the grid, the files and a drawing of the layout. depth_mm is "
            "how deep the pockets are: ask how thick the tools are. A tool listed twice gets two pockets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tools": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_BIN_TOOLS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": _TOOL,
                            "depth_mm": {
                                "type": "number",
                                "description": "this tool's pocket depth, if not depth_mm",
                            },
                        },
                        "required": ["tool"],
                        "additionalProperties": False,
                    },
                },
                "depth_mm": {"type": "number", "minimum": 2, "maximum": 133, "description": "pocket depth"},
                "name": {"type": "string", "maxLength": 200, "description": "the bin's name and file name"},
                "grid": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[units across, units deep], 42 mm a unit; omit for the smallest",
                },
                "height_units": {"type": "integer", "minimum": 2, "maximum": MAX_HEIGHT_UNITS},
                "magnets": {"type": "boolean", "default": True},
                "stacking_lip": {"type": "boolean", "default": True},
                "half_grid": {"type": "boolean", "default": False, "description": "allow half units"},
                "clearance_mm": {"type": "number", "minimum": 0, "maximum": 5, "default": 1.0},
                "gap_mm": {"type": "number", "minimum": 1, "maximum": 30, "default": 3.0},
                "bed_mm": {
                    "type": "number",
                    "default": 256,
                    "description": "the printer bed; a larger bin is also given in parts. 0: never split",
                },
                "label": {
                    "type": "object",
                    "description": (
                        "a text label on the bin, sized to fit; omit for none, {} for the default. "
                        "lip: one label along the back edge of the bin's top, saying text, else the "
                        "tool's name (the bin's name for several tools). floor: each tool's name in "
                        "the floor of its pocket, seen when the tool is out"
                    ),
                    "properties": {
                        "text": {"type": "string", "maxLength": labels.MAX_CHARS},
                        "placement": {"type": "string", "enum": list(labels.PLACEMENTS), "default": "lip"},
                        "style": {
                            "type": "string",
                            "enum": list(labels.STYLES),
                            "default": "deboss",
                            "description": "deboss: sunk into the surface; emboss: raised from it",
                        },
                        "height_mm": {
                            "type": "number",
                            "minimum": labels.MIN_CAP,
                            "maximum": labels.MAX_CAP,
                            "default": labels.DEFAULT_CAP,
                            "description": "capital letters' height; made smaller to fit, to the minimum",
                        },
                        "depth_mm": {
                            "type": "number",
                            "minimum": labels.MIN_DEPTH,
                            "maximum": labels.MAX_DEPTH,
                            "default": labels.DEFAULT_DEPTH,
                            "description": "how far the letters are sunk or raised",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["tools", "depth_mm"],
            "additionalProperties": False,
        },
        "annotations": _WRITES,
    },
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)
_HANDLERS = {
    "gridfinity_photos": "_list_photos",
    "gridfinity_trace": "_trace",
    "gridfinity_save_tools": "_save_tools",
    "gridfinity_tools": "_list_tools",
    "gridfinity_edit_tool": "_edit_tool",
    "gridfinity_make_bin": "_make_bin",
}

INSTRUCTIONS = """Gridfinity bins from photos, with the person's Tracefinity:
1. gridfinity_photos lists the photos in the person's Gridfinity folder, newest first. A good
   photo shows the tools lying flat, apart, on a plain sheet of paper (a4, letter, a3 or
   tabloid) on a darker surface, all four corners in view, taken from straight above: the
   paper gives the scale.
2. gridfinity_trace traces one photo and returns each outline's size in mm and a drawing with
   the outlines numbered. Check the sizes with the person; ask what each tool is.
3. gridfinity_save_tools saves the outlines that are tools, with names. gridfinity_tools lists
   the library; gridfinity_edit_tool renames a tool or adds or takes off its finger scoop.
4. gridfinity_make_bin lays tools out in the smallest bin they fit and saves its STL.
   Ask how thick the tools are for depth_mm, and offer a label (the tool's name along the
   bin's back edge, or each tool's name in its pocket's floor). Returns a drawing of the layout and an address
   where the person can adjust the bin by hand in Tracefinity."""


class BadArguments(ValueError):
    """Arguments that are not what the tool takes."""


class Refused(RuntimeError):
    """A tool that cannot do what it was asked: said to the chat as it is."""


def _shell_folder(csidl: int) -> str | None:
    """A Windows shell folder (Pictures, Documents), wherever the person keeps it."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) != 0:  # type: ignore[attr-defined]
        return None
    return buffer.value or None


def _saved(key: str) -> str | None:
    """A Gridfinity setting: its environment variable, else what the Extensions page saved."""
    from ..extensions import setting

    return setting("gridfinity", key)


def _folder(env: str, csidl: int, fallback: str, leaf: str) -> str:
    key = {PHOTOS_ENV: "photos", BINS_ENV: "bins"}[env]
    chosen = _saved(key)
    if chosen:
        if not os.path.isabs(chosen):
            raise Refused(f"{env} must be a full path.")
        return os.path.normpath(chosen)
    base = _shell_folder(csidl) or os.path.join(os.path.expanduser("~"), fallback)
    return os.path.join(base, leaf)


def default_photos() -> str:
    """``%USERPROFILE%\\Pictures\\Gridfinity``, or :data:`PHOTOS_ENV`."""
    return _folder(PHOTOS_ENV, 0x27, "Pictures", "Gridfinity")


def default_bins() -> str:
    """``%USERPROFILE%\\Documents\\Gridfinity bins``, or :data:`BINS_ENV`."""
    return _folder(BINS_ENV, 0x05, "Documents", "Gridfinity bins")


def safe_file_name(name: str) -> str:
    """``name`` as a file name on any drive: letters, digits, spaces and ``_-.,()+`` only."""
    kept = "".join(c if (c.isalnum() or c in " _-.,()+") and c.isprintable() else " " for c in name)
    kept = " ".join(kept.split()).strip(" .")[:MAX_NAME] or "bin"
    return f"bin {kept}" if kept.split(".")[0].lower() in _UNSAFE_NAMES else kept


def _only(args: dict, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> None:
    unknown = sorted(set(args) - set(required) - set(optional))
    if unknown:
        raise BadArguments(f"unknown argument {unknown[0][:64]!r}")
    for key in required:
        if key not in args:
            raise BadArguments(f"{key} is required")


def _number(value: Any, what: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadArguments(f"{what} is a number")
    if not low <= value <= high:
        raise BadArguments(f"{what} is from {low:g} to {high:g}")
    return float(value)


def _flag(args: dict, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise BadArguments(f"{key} is true or false")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise BadArguments(f"{what} is text")
    text = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    if not text:
        raise BadArguments(f"{what} is empty")
    return text[:MAX_NAME]


def _points(raw: Any) -> list[tuple[float, float]]:
    """Tracefinity's ``[{"x": .., "y": ..}]``, checked."""
    if not isinstance(raw, list):
        return []
    points = []
    for p in raw:
        x, y = (p.get("x"), p.get("y")) if isinstance(p, dict) else (None, None)
        if (
            isinstance(x, (int, float))
            and isinstance(y, (int, float))
            and math.isfinite(x)
            and math.isfinite(y)
        ):
            points.append((float(x), float(y)))
    return points


def _xy(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"x": x, "y": y} for x, y in points]


def _mm(value: float) -> float:
    return round(value, 1)


def _half_turn(angle: float) -> float:
    """The same line's direction in (-90, 90], so a label never reads upside down."""
    angle = math.fmod(angle, 180.0)
    if angle <= -90.0:
        angle += 180.0
    elif angle > 90.0:
        angle -= 180.0
    return angle


def _label_args(raw: Any) -> dict:
    """The ``label`` argument of ``gridfinity_make_bin``, checked, with its defaults."""
    if not isinstance(raw, dict):
        raise BadArguments("label is an object: text, placement, style, height_mm, depth_mm")
    _only(raw, (), ("text", "placement", "style", "height_mm", "depth_mm"))
    text = None
    if "text" in raw:
        if not isinstance(raw["text"], str):
            raise BadArguments("label text is text")
        if len(" ".join(raw["text"].split())) > labels.MAX_CHARS:
            raise BadArguments(f"label text is {labels.MAX_CHARS} characters at most")
        text = labels.clean(raw["text"])
        if not text:
            raise BadArguments("label text has no letters, digits or punctuation Tracefinity's font draws")
    placement = raw.get("placement", "lip")
    if placement not in labels.PLACEMENTS:
        raise BadArguments("label placement is lip or floor")
    style = raw.get("style", "deboss")
    if style not in labels.STYLES:
        raise BadArguments("label style is deboss or emboss")
    return {
        "text": text,
        "placement": placement,
        "emboss": style == "emboss",
        "height_mm": _number(
            raw.get("height_mm", labels.DEFAULT_CAP), "label height_mm", labels.MIN_CAP, labels.MAX_CAP
        ),
        "depth_mm": _number(
            raw.get("depth_mm", labels.DEFAULT_DEPTH), "label depth_mm", labels.MIN_DEPTH, labels.MAX_DEPTH
        ),
    }


def _lip_label(text: str, label: dict, shapes: list[Shape], options: dict) -> tuple[Layout, Label]:
    """The layout with a strip kept along the back edge for ``text``, and the label in it, at
    the largest size from the one asked for down to :data:`labels.MIN_CAP` that fits across.
    A bin of no grid given that is too narrow even then is made wider: the fewest cells that
    take the label at one of those sizes, the larger size when two take as many."""
    if not text:
        raise Refused(
            "The label has no letters, digits or punctuation Tracefinity's font draws: give its text."
        )
    pad = inset(options["stacking_lip"])

    def place(cap: float, min_across: float = 1.0) -> tuple[Layout | None, Label | None, float]:
        try:
            layout = lay_out(shapes, reserve=labels.band(cap), min_across=min_across, **options)
        except LayoutError:
            return None, None, 0.0  # a smaller label needs a narrower strip
        across, _ = layout.grid
        room = interior(across, pad)
        found = labels.on_lip(
            text,
            cap,
            across_mm=across * GRID,
            room=room,
            between=(BIN_GAP / 2 + pad, min(p.box[1] for p in layout.placements)),
            emboss=label["emboss"],
            depth=label["depth_mm"],
        )
        return layout, found, room

    last_room = None
    for cap in labels.sizes(label["height_mm"]):
        layout, found, room = place(cap)
        if found is not None:
            return layout, found
        if layout is not None:
            last_room = (layout.grid[0], room)
    if options["grid"] is None:
        best: tuple[Layout, Label] | None = None
        for cap in labels.sizes(label["height_mm"]):
            need = labels.width(text, cap) + 2 * labels.MARGIN
            layout, found, _ = place(cap, units_for(need, pad, options["half"]))
            if layout is not None and found is not None:
                cells = layout.grid[0] * layout.grid[1]
                if best is None or cells < best[0].grid[0] * best[0].grid[1] - 1e-9:
                    best = (layout, found)
        if best is not None:
            return best
    if last_room is None:
        grid = options["grid"]
        bin_ = f"a {grid[0]:g} x {grid[1]:g} bin" if grid else "any bin"
        raise Refused(
            f"The tools do not fit in {bin_} with a strip along its back edge for a label "
            f"{labels.MIN_CAP:g} mm tall. Give a deeper grid, or put the label on the floor of the pockets."
        )
    across, room = last_room
    need = labels.width(text, labels.MIN_CAP) + 2 * labels.MARGIN
    raise Refused(
        f"The label {text!r} is too long for a bin {across:g} units across: at the smallest size, "
        f"{labels.MIN_CAP:g} mm tall, it needs {need:.0f} mm and the bin has {room:.0f} mm inside its lip. "
        "Give a shorter label, or a wider grid."
    )


def _floor_label(
    label: dict,
    detail: dict,
    placement: Any,
    rings: list,
    holes: list,
    depth: float,
    depths: list,
) -> tuple[Label | None, str]:
    """A pocket's floor label, at the largest size that fits, else None and why not."""
    own = depths[placement.index]
    if own is not None and abs(own - depth) > 1e-9:
        return None, f"its pocket is {own:g} mm deep, and Tracefinity puts floor labels {depth:g} mm down"
    text = labels.clean(label["text"] if label["text"] is not None else str(detail.get("name") or ""))
    if not text:
        return None, "its name has no letters Tracefinity's font draws"
    along = _half_turn(placement.rotation - long_side_angle(_points(detail.get("points"))))
    for cap in labels.sizes(label["height_mm"]):
        found = labels.in_pocket(
            text, cap, rings, holes, along, emboss=label["emboss"], depth=label["depth_mm"]
        )
        if found is not None:
            return found, ""
    return None, (
        f"it has no room for {text!r} at the smallest size, {labels.MIN_CAP:g} mm tall, "
        "clear of its edges and scoop"
    )


def _label_reply(
    label: dict, on_lip: Label | None, in_pockets: list[dict], unlabelled: list[dict], stacking_lip: bool
) -> dict:
    reply: dict[str, Any] = {
        "placement": label["placement"],
        "style": "emboss" if label["emboss"] else "deboss",
        "depth_mm": label["depth_mm"],
    }
    if on_lip is not None:
        reply["text"] = on_lip.text
        reply["height_mm"] = on_lip.cap
        if on_lip.cap < label["height_mm"]:
            reply["made_smaller"] = f"from {label['height_mm']:g} mm, to fit"
        if label["emboss"] and stacking_lip:
            reply["note"] = (
                "Raised letters on the top of a stacking bin can keep a bin stacked on it from sitting "
                "flat; a debossed label cannot."
            )
    else:
        reply["pockets"] = in_pockets
        if unlabelled:
            reply["unlabelled"] = unlabelled
    return reply


def _hole_reach(hole: dict) -> Hole | None:
    """A finger hole of any shape as the circle round it, for the layout."""
    x, y, r = hole.get("x"), hole.get("y"), hole.get("radius", 15.0)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y, r)):
        return None
    shape = hole.get("shape", "circle")
    if shape in ("circle", "cylinder"):
        reach = r
    else:
        w, h = hole.get("width") or 2 * r, hole.get("height") or 2 * r
        reach = math.hypot(w, h) / 2 if shape != "square" else r * math.sqrt(2)
    return Hole(float(x), float(y), float(reach))


class Gridfinity:
    """The tools (see the module notes). ``client`` makes the Tracefinity client on the first
    call that needs it; ``photos`` and ``bins`` are the folders (default
    :func:`default_photos` and :func:`default_bins`)."""

    def __init__(
        self,
        client: Callable[[], Tracefinity] | None = None,
        *,
        photos: str | None = None,
        bins: str | None = None,
        home: str | None = None,
    ) -> None:
        self._make_client = client or Tracefinity
        self._client: Tracefinity | None = None
        self._photos = photos
        self._bins = bins
        self.home = os.path.normcase(os.path.normpath(home or os.path.expanduser("~")))
        self._lock = threading.Lock()
        self._traces: dict[str, list[str]] = {}  # a trace: its outlines' ids, in the order numbered
        self._saved: dict[tuple[str, str], str] = {}  # (trace, outline id): the tool saved from it

    @property
    def client(self) -> Tracefinity:
        with self._lock:
            if self._client is None:
                try:
                    self._client = self._make_client()
                except TracefinityError as exc:
                    raise Refused(str(exc)) from None
            return self._client

    def close(self) -> None:
        """End what the tools opened: the SSH tunnel to Tracefinity, if there is one."""
        with self._lock:
            client = self._client
        if client is not None:
            client.close()

    @property
    def photos(self) -> str:
        return self._photos or default_photos()

    @property
    def bins(self) -> str:
        return self._bins or default_bins()

    def shown(self, path: str) -> str:
        """``path`` for a reply: under the person's profile as ``%USERPROFILE%``."""
        normal = os.path.normpath(path)
        if os.path.normcase(normal).startswith(self.home + os.sep):
            return "%USERPROFILE%" + normal[len(self.home) :]
        return normal

    def call(self, name: str, args: dict, cancel: Cancel | None = None) -> tuple[dict, list[bytes]]:
        """Carry out tool ``name``: the reply and the PNG drawings that go with it."""
        handler = getattr(self, _HANDLERS[name], None) if name in _HANDLERS else None
        if handler is None:
            raise BadArguments(f"there is no tool {name[:64]!r}")
        try:
            return handler(args, cancel)
        except (TracefinityError, LayoutError, LabelError) as exc:
            raise Refused(str(exc)) from None

    # ----------------------------------------------------------------- photos
    def _list_photos(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(args)
        folder = self.photos
        data: dict[str, Any] = {"folder": self.shown(folder)}
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
            data["photos"] = []
            data["note"] = "The folder was just made: ask the person to put photos of their tools in it."
            return data, []
        found = []
        with os.scandir(folder) as entries:
            for entry in entries:
                if (
                    os.path.splitext(entry.name)[1].lower() not in CONTENT_TYPES
                    or not entry.name.isprintable()
                ):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                info = entry.stat(follow_symlinks=False)
                found.append((info.st_mtime, entry.name, info.st_size))
        found.sort(reverse=True)
        data["photos"] = [
            {
                "photo": name,
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                "size_kb": max(1, round(size_bytes / 1024)),
            }
            for mtime, name, size_bytes in found[:MAX_PHOTOS_LISTED]
        ]
        if len(found) > MAX_PHOTOS_LISTED:
            data["more"] = len(found) - MAX_PHOTOS_LISTED
        if not found:
            data["note"] = "No photos yet: ask the person to put photos of their tools in the folder."
        return data, []

    def _photo(self, name: Any) -> tuple[bytes, str]:
        """A photo in the photos folder, by its file name there: its bytes and suffix."""
        if not isinstance(name, str) or not name or name in (".", "..") or any(c in name for c in "/\\:"):
            raise BadArguments("photo is a file name from gridfinity_photos")
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in CONTENT_TYPES:
            raise Refused(f"{name[:80]} is not a photo Tracefinity reads ({', '.join(CONTENT_TYPES)}).")
        path = os.path.join(self.photos, name)
        try:
            info = os.lstat(path)
        except OSError:
            raise Refused(
                f"There is no photo {name[:80]!r} in the Gridfinity folder: list them first."
            ) from None
        if not stat.S_ISREG(info.st_mode):
            raise Refused(f"{name[:80]} is not a plain file in the Gridfinity folder.")
        if info.st_size > MAX_PHOTO_BYTES:
            raise Refused(f"{name[:80]} is larger than the 20 MB Tracefinity takes.")
        with open(path, "rb") as f:
            return f.read(MAX_PHOTO_BYTES + 1), suffix

    # ----------------------------------------------------------------- tracing
    @staticmethod
    def _numbered(polygons: list, scale: float) -> list[tuple[str, list[list[tuple[float, float]]]]]:
        """The outlines in mm, numbered left to right: (id, [outline, inner rings...])."""
        found = []
        for p in polygons:
            if not isinstance(p, dict) or not isinstance(p.get("id"), str):
                continue
            outline = [(x * scale, y * scale) for x, y in _points(p.get("points"))]
            if len(outline) < 3:
                continue
            rings = [outline]
            for ring in p.get("interior_rings") or []:
                inner = [(x * scale, y * scale) for x, y in _points(ring)]
                if len(inner) >= 3:
                    rings.append(inner)
            x0, x1 = min(q[0] for q in outline), max(q[0] for q in outline)
            y0, y1 = min(q[1] for q in outline), max(q[1] for q in outline)
            found.append(((round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)), p["id"], rings))
        found.sort(key=lambda f: f[0])
        return [(pid, rings) for _, pid, rings in found]

    def _trace(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(args, ("photo", "paper"))
        if args["paper"] not in PAPER_SIZES:
            raise BadArguments(f"paper is one of {', '.join(PAPER_SIZES)}")
        data, suffix = self._photo(args["photo"])
        client = self.client
        upload = client.upload(data, suffix, cancel=cancel)
        trace = segment(upload.get("session_id"), "trace")
        corners = upload.get("detected_corners")
        if not isinstance(corners, list) or len(corners) != 4:
            raise Refused(
                "Tracefinity did not find the paper's four corners. Take the photo again with the whole "
                "sheet in view, flat on a darker plain surface, from straight above, or mark the corners "
                f"by hand at {client.page('trace', trace)}."
            )
        corrected = client.set_corners(trace, corners, args["paper"], cancel=cancel)
        scale = corrected.get("scale_factor")
        if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise Refused("Tracefinity did not give the photo's scale.")
        traced = client.trace(trace, cancel=cancel)
        outlines = self._numbered(traced.get("polygons") or [], float(scale))
        if not outlines:
            raise Refused(
                "No tools were found on the paper. Tools should lie apart, flat, and darker or lighter "
                "than the paper."
            )
        with self._lock:
            self._traces[trace] = [pid for pid, _ in outlines]
        listed = []
        for number, (_, rings) in enumerate(outlines, start=1):
            length, width = size(rings[0])
            entry: dict[str, Any] = {
                "outline": number,
                "length_mm": _mm(length),
                "width_mm": _mm(width),
                "area_mm2": round(area(rings[0]) - sum(area(r) for r in rings[1:])),
            }
            if len(rings) > 1:
                entry["openings"] = len(rings) - 1
            listed.append(entry)
        data_out: dict[str, Any] = {
            "trace": trace,
            "paper": args["paper"],
            "outlines": listed,
            "mm_per_pixel": round(float(scale), 5),
            "drawing": "attached: the outlines, numbered left to right",
            "edit": client.page("trace", trace),
            "next": (
                "Check the sizes and ask what each tool is, then save the ones that are tools with "
                "gridfinity_save_tools. The person can correct an outline by hand at the edit address."
            ),
        }
        warnings = [w for w in corrected.get("warnings") or [] if isinstance(w, str)]
        if warnings:
            data_out["photo_warnings"] = [w[:200] for w in warnings[:5]]
        return data_out, [trace_drawing([rings for _, rings in outlines])]

    # ----------------------------------------------------------------- the library
    def _save_tools(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(args, ("trace", "tools"))
        trace = segment(args["trace"], "trace")
        wanted = args["tools"]
        if not isinstance(wanted, list) or not 1 <= len(wanted) <= MAX_BIN_TOOLS:
            raise BadArguments(f"tools is a list of 1 to {MAX_BIN_TOOLS} outlines to save")
        client = self.client
        session = client.session(trace, cancel=cancel)
        scale = session.get("scale_factor")
        if not isinstance(scale, (int, float)) or scale <= 0:
            raise Refused("That trace has no scale yet: trace the photo again.")
        outlines = self._numbered(session.get("polygons") or [], float(scale))
        ids = [pid for pid, _ in outlines]
        with self._lock:
            known = self._traces.get(trace)
        if known is not None and set(known) != set(ids):
            raise Refused(
                "The trace's outlines changed since it was traced (edited in Tracefinity?): trace the photo "
                "again before saving."
            )
        order = known if known is not None else ids
        picks: list[tuple[str, str, bool, int]] = []
        for item in wanted:
            if not isinstance(item, dict):
                raise BadArguments("each tool is an object with outline and name")
            _only(item, ("outline", "name"), ("finger_scoop",))
            number = item["outline"]
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(order):
                raise BadArguments(f"outline is a number from 1 to {len(order)}")
            pid = order[number - 1]
            if any(p[0] == pid for p in picks):
                raise BadArguments(f"outline {number} is listed twice")
            picks.append((pid, _text(item["name"], "name"), _flag(item, "finger_scoop", True), number))
        for pid, _, _, number in picks:
            with self._lock:
                earlier = self._saved.get((trace, pid))
            if earlier is not None:
                raise Refused(f"Outline {number} was already saved, as tool {earlier}.")
        chosen = {p[0] for p in picks}
        saved_ids = client.save_tools(trace, [p[0] for p in picks], cancel=cancel)
        in_session_order = [
            pid for pid in (p.get("id") for p in session.get("polygons") or []) if pid in chosen
        ]
        if len(saved_ids) != len(in_session_order):
            raise Refused(
                "Tracefinity saved a different number of tools than asked; list them with gridfinity_tools."
            )
        tool_for = dict(zip(in_session_order, saved_ids, strict=True))
        saved = []
        for pid, name, scoop, number in picks:
            tool_id = tool_for[pid]
            with self._lock:
                self._saved[(trace, pid)] = tool_id
            detail = client.tool(tool_id, cancel=cancel)
            points = _points(detail.get("points"))
            fields: dict[str, Any] = {"name": name}
            if scoop and len(points) >= 3:
                fields["finger_holes"] = list(detail.get("finger_holes") or []) + [self._scoop(points)]
            client.update_tool(tool_id, fields, cancel=cancel)
            length, width = size(points) if len(points) >= 3 else (0.0, 0.0)
            saved.append(
                {
                    "tool": tool_id,
                    "outline": number,
                    "name": name,
                    "length_mm": _mm(length),
                    "width_mm": _mm(width),
                    "finger_scoop": "finger_holes" in fields,
                }
            )
        return {"tools": saved, "next": "Make a bin with gridfinity_make_bin."}, []

    @staticmethod
    def _scoop(points: list[tuple[float, float]]) -> dict:
        hole = finger_scoop(points)
        return {
            "id": f"{SCOOP_ID}-{uuid.uuid4().hex[:12]}",
            "x": hole.x,
            "y": hole.y,
            "radius": hole.radius,
            "shape": "circle",
        }

    def _list_tools(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(args)
        found = self.client.tools(cancel=cancel)
        found.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)
        listed = []
        for t in found[:MAX_TOOLS_LISTED]:
            points = _points(t.get("points"))
            if not isinstance(t.get("id"), str) or len(points) < 3:
                continue
            length, width = size(points)
            listed.append(
                {
                    "tool": t["id"],
                    "name": "".join(c for c in str(t.get("name", "")) if c.isprintable())[:MAX_NAME],
                    "length_mm": _mm(length),
                    "width_mm": _mm(width),
                }
            )
        data: dict[str, Any] = {"tools": listed}
        if len(found) > MAX_TOOLS_LISTED:
            data["more"] = len(found) - MAX_TOOLS_LISTED
        return data, []

    def _edit_tool(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(args, ("tool",), ("name", "finger_scoop"))
        if "name" not in args and "finger_scoop" not in args:
            raise BadArguments("give a new name, finger_scoop, or both")
        tool_id = segment(args["tool"], "tool")
        client = self.client
        detail = client.tool(tool_id, cancel=cancel)
        holes = [h for h in detail.get("finger_holes") or [] if isinstance(h, dict)]
        ours = [h for h in holes if str(h.get("id", "")).startswith(SCOOP_ID)]
        fields: dict[str, Any] = {}
        if "name" in args:
            fields["name"] = _text(args["name"], "name")
        if "finger_scoop" in args:
            want = _flag(args, "finger_scoop", True)
            points = _points(detail.get("points"))
            if want and not ours and len(points) >= 3:
                fields["finger_holes"] = holes + [self._scoop(points)]
            elif not want and ours:
                fields["finger_holes"] = [h for h in holes if h not in ours]
        if fields:
            client.update_tool(tool_id, fields, cancel=cancel)
        has_scoop = (
            bool(ours)
            if "finger_holes" not in fields
            else any(str(h.get("id", "")).startswith(SCOOP_ID) for h in fields["finger_holes"])
        )
        return {
            "tool": tool_id,
            "name": fields.get(
                "name", "".join(c for c in str(detail.get("name", "")) if c.isprintable())[:MAX_NAME]
            ),
            "finger_scoop": has_scoop,
            "changed": bool(fields),
        }, []

    # ----------------------------------------------------------------- bins
    def _make_bin(self, args: dict, cancel: Cancel | None) -> tuple[dict, list[bytes]]:
        _only(
            args,
            ("tools", "depth_mm"),
            (
                "name",
                "grid",
                "height_units",
                "magnets",
                "stacking_lip",
                "half_grid",
                "clearance_mm",
                "gap_mm",
                "bed_mm",
                "label",
            ),
        )
        entries = args["tools"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_BIN_TOOLS:
            raise BadArguments(f"tools is a list of 1 to {MAX_BIN_TOOLS} tools")
        depth = _number(args["depth_mm"], "depth_mm", 2, max_depth(MAX_HEIGHT_UNITS))
        half = _flag(args, "half_grid", False)
        lip = _flag(args, "stacking_lip", True)
        magnets = _flag(args, "magnets", True)
        clearance = _number(args.get("clearance_mm", 1.0), "clearance_mm", 0, 5)
        gap = _number(args.get("gap_mm", 3.0), "gap_mm", 1, 30)
        bed = _number(args.get("bed_mm", 256.0), "bed_mm", 0, 1000)
        if 0 < bed < 100:
            raise BadArguments("bed_mm is 0 (never split) or from 100 to 1000")
        grid = None
        if "grid" in args:
            raw = args["grid"]
            if not isinstance(raw, list) or len(raw) != 2:
                raise BadArguments("grid is [units across, units deep]")
            grid = (_number(raw[0], "grid", 1, MAX_UNITS), _number(raw[1], "grid", 1, MAX_UNITS))
            step = 0.5 if half else 1.0
            if any(abs(v / step - round(v / step)) > 1e-9 for v in grid):
                raise BadArguments("grid is in whole units, or halves with half_grid")
        depths: list[float | None] = []
        tool_ids: list[str] = []
        for item in entries:
            if not isinstance(item, dict):
                raise BadArguments("each tool is an object with a tool id")
            _only(item, ("tool",), ("depth_mm",))
            tool_ids.append(segment(item["tool"], "tool"))
            depths.append(
                _number(item["depth_mm"], "depth_mm", 2, max_depth(MAX_HEIGHT_UNITS))
                if "depth_mm" in item
                else None
            )
        deepest = max(d if d is not None else depth for d in depths)
        if "height_units" in args:
            height = args["height_units"]
            if isinstance(height, bool) or not isinstance(height, int) or not 2 <= height <= MAX_HEIGHT_UNITS:
                raise BadArguments(f"height_units is a whole number from 2 to {MAX_HEIGHT_UNITS}")
            if deepest > max_depth(height) + 1e-9:
                raise Refused(
                    f"A {height}-unit bin holds pockets up to {max_depth(height):g} mm deep; "
                    f"{deepest:g} mm needs {height_units_for(deepest)} units."
                )
        else:
            height = height_units_for(deepest)
        name = _text(args["name"], "name") if "name" in args else None
        label = _label_args(args["label"]) if "label" in args else None

        client = self.client
        details: dict[str, dict] = {}
        for tool_id in dict.fromkeys(tool_ids):
            details[tool_id] = client.tool(tool_id, cancel=cancel)
        shapes = []
        for tool_id in tool_ids:
            detail = details[tool_id]
            points = _points(detail.get("points"))
            if len(points) < 3:
                raise Refused(f"Tool {tool_id} has no outline.")
            holes = [
                h
                for h in (_hole_reach(f) for f in detail.get("finger_holes") or [] if isinstance(f, dict))
                if h
            ]
            shapes.append(Shape(tuple(points), tuple(holes)))
        options = {"clearance": clearance, "gap": gap, "stacking_lip": lip, "grid": grid, "half": half}
        layout = lay_out(shapes, **options)
        names = list(dict.fromkeys(str(details[t].get("name") or "tool") for t in tool_ids))
        if name is None:
            name = _text(" + ".join(names), "name")
        on_lip: Label | None = None
        if label is not None and label["placement"] == "lip":
            text = label["text"] if label["text"] is not None else names[0] if len(names) == 1 else name
            layout, on_lip = _lip_label(labels.clean(text), label, shapes, options)
        elif label is not None and label["text"] is not None and len(set(tool_ids)) > 1:
            raise BadArguments(
                "a floor label names each tool in its own pocket: give label text only for a lip label "
                "or a bin of one tool"
            )
        across, deep = layout.grid

        placed, pockets, scoops = [], [], []
        for p in layout.placements:
            tool_id = tool_ids[p.index]
            detail = details[tool_id]
            points = _points(detail.get("points"))
            pivot = mean(points)
            outline = placed_points(points, p)
            rings = [placed_about(_points(r), pivot, p) for r in detail.get("interior_rings") or []]
            holes = []
            for hole in detail.get("finger_holes") or []:
                if not isinstance(hole, dict) or _hole_reach(hole) is None:
                    continue
                hx, hy = placed_about([(hole["x"], hole["y"])], pivot, p)[0]
                holes.append({**hole, "x": hx, "y": hy})
            placed.append(
                {
                    "id": str(uuid.uuid4()),
                    "tool_id": tool_id,
                    "name": str(detail.get("name") or "tool")[:200],
                    "points": _xy(outline),
                    "finger_holes": holes,
                    "interior_rings": [_xy(r) for r in rings if len(r) >= 3],
                    "rotation": p.rotation,
                    "depth_override": depths[p.index],
                }
            )
            pockets.append([outline, *[r for r in rings if len(r) >= 3]])
            scoops.append([(h["x"], h["y"], _hole_reach(h).radius) for h in holes])

        placed_labels: list[Label] = [on_lip] if on_lip is not None else []
        in_pockets: list[dict] = []
        unlabelled: list[dict] = []
        if label is not None and label["placement"] == "floor":
            for p, rings_, holes_ in zip(layout.placements, pockets, scoops, strict=True):
                found, why = _floor_label(label, details[tool_ids[p.index]], p, rings_, holes_, depth, depths)
                if found is None:
                    unlabelled.append({"number": p.index + 1, "why": why})
                else:
                    placed_labels.append(found)
                    in_pockets.append({"number": p.index + 1, "text": found.text, "height_mm": found.cap})
            if not placed_labels:
                raise Refused(
                    "No pocket has room for a floor label: "
                    + "; ".join(f"tool {u['number']}: {u['why']}" for u in unlabelled)
                    + ". A lip label along the bin's back edge may fit."
                )

        config = {
            "grid_x": across,
            "grid_y": deep,
            "height_units": height,
            "magnets": magnets,
            "stacking_lip": lip,
            "half_grid_base": half,
            "cutout_depth": depth,
            "cutout_clearance": clearance,
            "wall_thickness": WALL,
            "bed_size": bed,
            "partial_bins_values": [True] * (math.ceil(across) * math.ceil(deep)),
        }
        made = client.create_bin(name, config, cancel=cancel)
        bin_id = segment(made.get("id"), "bin")
        fields: dict[str, Any] = {"bin_config": config, "placed_tools": placed}
        if placed_labels:
            fields["text_labels"] = [lb.for_tracefinity() for lb in placed_labels]
        client.update_bin(bin_id, fields, cancel=cancel)
        generated = client.generate(bin_id, cancel=cancel)
        wanted = [("bin.stl", ".stl")]
        if generated.get("threemf_url"):
            wanted.append(("bin.3mf", ".3mf"))
        split = generated.get("split_count") if isinstance(generated.get("split_count"), int) else 1
        if generated.get("zip_url"):
            wanted.append(("bin_parts.zip", " parts.zip"))
        contents = [(client.bin_file(bin_id, remote, cancel=cancel), ending) for remote, ending in wanted]
        files = self._save(safe_file_name(f"{name} {across:g}x{deep:g}x{height}"), contents)

        data: dict[str, Any] = {
            "bin": bin_id,
            "name": name,
            "grid": [across, deep],
            "height_units": height,
            "outside_mm": [_mm(across * GRID - 0.5), _mm(deep * GRID - 0.5), _mm(height * HEIGHT_UNIT)],
            "pocket_depth_mm": depth,
            "tools": [
                {
                    "number": p.index + 1,
                    "tool": tool_ids[p.index],
                    "name": "".join(
                        c for c in str(details[tool_ids[p.index]].get("name", "")) if c.isprintable()
                    )[:MAX_NAME],
                    "turned_deg": round(p.rotation, 1),
                    "centre_mm": [_mm(p.centre[0]), _mm(p.centre[1])],
                }
                for p in layout.placements
            ],
            "folder": self.shown(self.bins),
            "files": files,
            "drawing": "attached: the bin from above, the tools numbered as given",
            "edit": client.page("bins", bin_id),
            "next": (
                "Tell the person where the files are. The height is without the stacking lip. To move a "
                "tool or a label, or add one, the person can open the edit address in Tracefinity."
            ),
        }
        if label is not None:
            data["label"] = _label_reply(label, on_lip, in_pockets, unlabelled, lip)
        if lip:
            data["stacking_lip"] = True
        if half and magnets:
            data["magnets"] = "a half-grid base has no magnet holes"
        if split > 1:
            data["split_into"] = split
        warning = generated.get("warning")
        if isinstance(warning, str) and warning.strip():
            data["warning"] = warning[:300]
        drawing = bin_drawing(
            layout,
            pockets,
            scoops,
            stacking_lip=lip,
            height_units=height,
            labels=[lb.box for lb in placed_labels],
        )
        return data, [drawing]

    def _save(self, stem: str, contents: list[tuple[bytes, str]]) -> list[str]:
        """Write a bin's files in the bins folder under one name none of them has yet (``stem``,
        else ``stem (2)`` and on), never over a file: their names."""
        folder = self.bins
        os.makedirs(folder, exist_ok=True)
        for n in range(1, 1000):
            base = stem if n == 1 else f"{stem} ({n})"
            names = [base + ending for _, ending in contents]
            if not any(os.path.lexists(os.path.join(folder, name)) for name in names):
                break
        else:
            raise Refused("The bins folder already holds a thousand bins of that name.")
        for (content, _), name in zip(contents, names, strict=True):
            path = os.path.join(folder, name)
            part = path + ".part"
            with open(part, "wb") as f:
                f.write(content)
            try:
                if os.name == "nt":
                    os.rename(part, path)  # never replaces a file on Windows
                else:
                    os.link(part, path)  # nor does a hard link elsewhere
                    os.unlink(part)
            except FileExistsError:
                os.unlink(part)
                raise Refused(f"{name} appeared in the bins folder while it was being written.") from None
        return names


__all__ = [
    "BINS_ENV",
    "INSTRUCTIONS",
    "PHOTOS_ENV",
    "TOOLS",
    "TOOL_NAMES",
    "BadArguments",
    "Gridfinity",
    "Refused",
    "default_bins",
    "default_photos",
    "safe_file_name",
]
