"""The contracts between the stages of a drawing (``docs/DRAWINGS.md`` 6).

Plain frozen dataclasses, no behaviour beyond small helpers: the options a
drawing is made with, the feature set recognition produces, the view
specifications and geometry, the requirements and planned dimensions, and the
in-memory drawing. Each stage's branch fills its own outputs; outside the one
planned revision (section 6) a branch may add optional fields to a type it
produces and never changes or removes one.

Model quantities are metres and radians, sheet quantities millimetres. Ids are
strings matching ``[a-z0-9-]{1,64}``: features ``f-1``, dimensions ``d-1``,
views ``v-1``, notes ``n-1``. Requirement keys are the role, the feature ids and
the axis (``loc/f-7/x``, ``size/f-3``); the view is never part of a key.

What the slice found the contracts must say is in ``docs/drawings/README.md``;
the items it settled are marked here with their number there (C1 to C28).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import InvalidArgumentError

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

PROCESSES = ("machined", "printed", "turned")
# The manufacturing types made by machining: a turned (lathe) part is noted and checked
# as a machined one, and takes the machined entries of Drawing Settings (settings_type)
MACHINING = ("machined", "turned")
SCHEMES = ("datum", "plusminus")
# How much a part's drawing says (docs/DRAWINGS.md, "Detail level"): the overall size and
# each hole and boss by size; every feature sized and located; or that, proven to define
# the part fully, with datums and GD&T as the scheme says
DETAIL_LEVELS = ("simplified", "complex", "full")
# How the drawing was started (docs/DRAWINGS.md, "Drawing modes"): every option chosen in
# the wizard (expert), or straight to the editor with the key sizes (express). An express
# drawing is a simplified one that also locates its holes and leaves out bosses, the
# shop's general notes and every question. The viewer's Guided mode chooses the wizard's
# options through plain questions, so its drawings are expert ones.
DRAWING_MODES = ("expert", "express")
UNIT_CHOICES = ("part", "in", "mm")
QUALITIES = ("normal", "draft", "fine")
TANGENT_MODES = ("hidden", "thin", "phantom")
ARRANGEMENTS = ("baseline", "ordinate")
DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")
SHEET_CHOICES = ("auto", "A", "B", "C", "D", "E")
VIEW_NAMES = ("front", "top", "right", "left", "bottom", "back", "isometric")
STATUSES = ("PRELIMINARY", "CHECKED", "RELEASED")

ID_PATTERN = re.compile(r"[a-z0-9-]{1,64}")


def check_id(value: Any, what: str = "id") -> str:
    """``value`` when it is an id (``[a-z0-9-]{1,64}``), else InvalidArgumentError."""
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise InvalidArgumentError(f"{what} must match [a-z0-9-]{{1,64}}", detail={"parameter": what})
    return value


def _choice(value: Any, choices: tuple[str, ...], name: str) -> None:
    if value not in choices:
        raise InvalidArgumentError(f"{name} must be one of {', '.join(choices)}", detail={"parameter": name})


def settings_type(process: str) -> str:
    """The manufacturing type whose entries of Drawing Settings a drawing of ``process``
    takes (default views, dimensioning, scheme, notes, materials and finishes): a turned
    part takes the machined ones, which Settings hold per type as machined and printed."""
    return "machined" if process == "turned" else process


# --------------------------------------------------------------------------- options (14)


def parts_list_spec(text: str) -> Any:
    """The :class:`~solidseas.bomtable.BomTableSpec` a drawing's ``parts_list`` option
    holds, checked; :class:`InvalidArgumentError` when it holds none."""
    import json

    from ..bomtable import spec_from_json

    if not isinstance(text, str):
        raise InvalidArgumentError(
            "parts_list is a BOM table's JSON text", detail={"parameter": "parts_list"}
        )
    try:
        data = json.loads(text)
    except ValueError:
        raise InvalidArgumentError("parts_list is not JSON", detail={"parameter": "parts_list"}) from None
    return spec_from_json(data)


def parts_list_text(table_spec: Any) -> str:
    """The ``parts_list`` option's text for a :class:`~solidseas.bomtable.BomTableSpec`:
    its JSON, keys sorted, so the same table is the same text."""
    import json

    return json.dumps(table_spec.to_json(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


MAX_BALLOON_OFFSET = 2000.0  # paper millimetres, more than the largest sheet


def _check_balloons(balloons: Any) -> None:
    def bad(why: str) -> InvalidArgumentError:
        return InvalidArgumentError(f"balloons: {why}", detail={"parameter": "balloons"})

    if not isinstance(balloons, tuple) or len(balloons) > 10000:
        raise bad("a tuple of (item, dx, dy)")
    seen = set()
    for entry in balloons:
        if not (isinstance(entry, tuple) and len(entry) == 3):
            raise bad("each is (item, dx, dy)")
        item, dx, dy = entry
        if not isinstance(item, str) or not item or len(item) > 40 or item in seen:
            raise bad("each names one item once")
        seen.add(item)
        for v in (dx, dy):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise bad("offsets are numbers")
            if abs(v) > MAX_BALLOON_OFFSET:
                raise bad(f"offsets are at most {MAX_BALLOON_OFFSET:g} mm")


@dataclass(frozen=True)
class DrawingOptions:
    """What a drawing is made with (14). Frozen in the drawing after its first save
    (6.8). ``views`` is ``auto`` or names from ``VIEW_NAMES``; ``scale`` is ``auto`` or
    (sheet, model) such as (1, 2); ``arrangement`` maps ``view/axis`` (``v-1/x``) to
    baseline or ordinate; ``bodies`` names the bodies drawn (None: the solid ones)."""

    process: str = "machined"
    scheme: str | None = None  # None: the process's default (datum machined, plusminus printed)
    units: str = "part"
    views: str | tuple[str, ...] = "auto"
    front: str | None = None  # None: chosen (8.2)
    turn: int = 0  # quarter turns of the front, 0 to 3
    hidden: bool | None = None  # None: the process's default view settings
    tangent: str | None = None
    sheet: str = "auto"
    scale: str | tuple[int, int] = "auto"
    arrangement: tuple[tuple[str, str], ...] = ()
    bodies: tuple[str, ...] | None = None
    quality: str = "normal"
    configuration: str | None = None
    # an assembly's parts list as the BOM editor left it: the BomTableSpec's JSON text
    # (solidseas.bomtable), None for the parts list SolidSeas makes by default
    parts_list: str | None = None
    detail: str = "full"
    # balloons the user moved: (item, dx, dy), each its circle's centre from the point its
    # leader ends on, paper millimetres, so it follows its part when the views move
    balloons: tuple[tuple[str, float, float], ...] = ()
    mode: str = "expert"

    def __post_init__(self) -> None:
        _choice(self.process, PROCESSES, "process")
        _choice(self.detail, DETAIL_LEVELS, "detail")
        _choice(self.mode, DRAWING_MODES, "mode")
        _check_balloons(self.balloons)
        if self.parts_list is not None:
            parts_list_spec(self.parts_list)
        if self.scheme is not None:
            _choice(self.scheme, SCHEMES, "scheme")
        _choice(self.units, UNIT_CHOICES, "units")
        if self.views != "auto":
            if not isinstance(self.views, tuple) or not self.views:
                raise InvalidArgumentError(
                    "views must be 'auto' or a tuple of view names", detail={"parameter": "views"}
                )
            for v in self.views:
                _choice(v, VIEW_NAMES, "views")
        if self.front is not None:
            _choice(self.front, DIRECTIONS, "front")
        if not isinstance(self.turn, int) or isinstance(self.turn, bool) or not 0 <= self.turn <= 3:
            raise InvalidArgumentError("turn must be 0 to 3 quarter turns", detail={"parameter": "turn"})
        if self.hidden is not None and not isinstance(self.hidden, bool):
            raise InvalidArgumentError("hidden must be true, false or None", detail={"parameter": "hidden"})
        if self.tangent is not None:
            _choice(self.tangent, TANGENT_MODES, "tangent")
        _choice(self.sheet, SHEET_CHOICES, "sheet")
        if self.scale != "auto":
            ok = (
                isinstance(self.scale, tuple)
                and len(self.scale) == 2
                and all(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 1000 for n in self.scale)
            )
            if not ok:
                raise InvalidArgumentError(
                    "scale must be 'auto' or (sheet, model)", detail={"parameter": "scale"}
                )
        for key, value in self.arrangement:
            if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]{1,64}/[xyz]", key):
                raise InvalidArgumentError(
                    "arrangement keys are view/axis", detail={"parameter": "arrangement"}
                )
            _choice(value, ARRANGEMENTS, "arrangement")
        if self.bodies is not None and not all(isinstance(b, str) for b in self.bodies):
            raise InvalidArgumentError("bodies must be names", detail={"parameter": "bodies"})
        _choice(self.quality, QUALITIES, "quality")

    @property
    def effective_scheme(self) -> str:
        """The tolerancing scheme in force: the option, else datum for a fully defined
        machined part and plus/minus for printed parts and for the simplified and complex
        detail levels (10.5)."""
        if self.scheme is not None:
            return self.scheme
        return "plusminus" if self.process == "printed" or self.detail != "full" or self.express else "datum"

    @property
    def express(self) -> bool:
        """Whether this is an Express drawing (its overall size, its holes by size and
        location, and nothing else)."""
        return self.mode == "express"


# --------------------------------------------------------------------------- features (6.4)


@dataclass(frozen=True)
class Descriptor:
    """What matching compares between two versions of a model (6.4.1): the type, the
    size signature, the adjacency pattern and the position in the datum frame, in
    metres. Never a Parasolid node id."""

    type: str
    size: tuple[tuple[str, Any], ...] = ()
    adjacency: tuple[tuple[str, Any], ...] = ()
    position: tuple[float, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "size": {k: _plain(v) for k, v in self.size},
            "adjacency": {k: _plain(v) for k, v in self.adjacency},
            "position": list(self.position),
        }


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class Feature:
    """Shared by every feature: the faces it claims (``BrepModel`` face indices), its
    descriptor, and ``exact`` (false when a value came from a fit). Ids are not part
    of a feature; the drawing assigns them (13.4)."""

    faces: tuple[int, ...]
    descriptor: Descriptor
    exact: bool = True


@dataclass(frozen=True)
class Axis:
    """A line in the model: a point on it and a unit direction."""

    point: Vec3
    direction: Vec3


@dataclass(frozen=True)
class HoleSegment:
    """One segment of a hole, from its entry: ``cylinder`` (diameter, depth), ``cone``
    (diameters at both ends, included angle), ``annulus`` (a shoulder between two
    diameters), ``flat_bottom`` or ``drill_point`` (included angle)."""

    kind: str
    diameter: float = 0.0
    diameter_end: float = 0.0
    depth: float = 0.0
    angle: float = 0.0
    faces: tuple[int, ...] = ()


@dataclass(frozen=True)
class Hole(Feature):
    """A hole (6.4). ``kind`` is simple, counterbore, spotface, countersink, stepped,
    tapered or a combination joined by ``+``; ``ends`` each ``open``, ``blind`` or
    ``into_bore``; ``depth`` is the full-diameter depth from ``depth_from`` (a face
    index). ``entry_break`` holds the entry round or chamfer and its faces, which
    belong to the hole (C12)."""

    axis: Axis = Axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    entry_face: int = -1
    entry_kind: str = "planar_square"  # planar_square, planar_oblique, curved
    segments: tuple[HoleSegment, ...] = ()
    kind: str = "simple"
    ends: tuple[str, str] = ("open", "open")
    depth: float = 0.0
    depth_from: int = -1
    cover: float = 6.283185307179586  # radians of a full circle the hole's walls cover
    entry_break: tuple[str, float, tuple[int, ...]] | None = None  # ("round" | "chamfer", size, faces)
    thread: tuple[str, ...] = ()  # candidate designations; nothing is a thread until confirmed
    needs_auxiliary: bool = False

    @property
    def diameter(self) -> float:
        """The diameter of the hole's last (smallest through) cylinder."""
        for seg in reversed(self.segments):
            if seg.kind == "cylinder":
                return seg.diameter
        return 0.0

    @property
    def through(self) -> bool:
        return self.ends == ("open", "open")


@dataclass(frozen=True)
class Pattern(Feature):
    """A group of equal holes (6.4). ``members`` are the members' indices in the
    feature set, ordered: by angle from the first for a circular pattern, the first
    being a member on a principal axis when one is, else the one whose angle is under
    the step (C13); from one end to the other for an arc, whose included angle is
    ``step`` times one less than the count; by position otherwise. ``first_angle`` is
    the first member's own angle from the frame's first axis, in [0, 2 pi)."""

    kind: str = "scattered"  # linear, grid, circular, arc, scattered
    members: tuple[int, ...] = ()
    pitches: tuple[float, ...] = ()
    counts: tuple[int, ...] = ()
    centre: Vec3 | None = None
    pitch_diameter: float = 0.0
    step: float = 0.0
    first_angle: float = 0.0


@dataclass(frozen=True)
class Boss(Feature):
    axis: Axis = Axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    diameter: float = 0.0
    length: float = 0.0


@dataclass(frozen=True)
class Width(Feature):
    """Two antiparallel planar faces: ``material`` (tab, rib, wall, thickness, the
    envelope) or ``gap`` (pocket, slot, keyseat, groove), along a frame axis."""

    pair: tuple[int, int] = (-1, -1)
    axis: str = "x"
    kind: str = "material"
    role: str = "wall"  # envelope, tab, rib, wall, thickness, pocket, slot, keyseat, groove
    size: float = 0.0
    overlap: float = 0.0
    symmetric_about: str | None = None


@dataclass(frozen=True)
class Groove(Feature):
    axis: Axis = Axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    inner: float = 0.0
    outer: float = 0.0
    width: float = 0.0
    depth: float = 0.0
    opens_on: int = -1


@dataclass(frozen=True)
class Blend(Feature):
    radius: float = 0.0
    kind: str = "fillet"  # fillet (concave) or round (convex)
    derived: bool = False  # a full-round end: half a width
    of_hole: bool = False


@dataclass(frozen=True)
class Chamfer(Feature):
    legs: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    shape: str = "planar"  # planar or conical


@dataclass(frozen=True)
class Slot(Feature):
    width: float = 0.0
    centre_distance: float = 0.0
    ends: tuple[Vec3, Vec3] = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    direction: Vec3 = (1.0, 0.0, 0.0)
    depth: float | None = None  # None: through


@dataclass(frozen=True)
class Pocket(Feature):
    floor: int = -1
    walls: tuple[int, ...] = ()
    depth: float = 0.0
    corner_radius: float = 0.0
    open_sides: int = 0


@dataclass(frozen=True)
class Depth:
    """A depth as its own record (C11): the floor face, the open face it is measured
    from, the frame axis, and the value."""

    floor: int
    open_face: int
    axis: str
    value: float
    feature: int = -1  # the feature it belongs to, by index in the set


@dataclass(frozen=True)
class Step(Feature):
    face: int = -1
    axis: str = "z"
    offset: float = 0.0


@dataclass(frozen=True)
class AngledFace(Feature):
    face: int = -1
    angle: float = 0.0
    meet_line: Axis | None = None
    virtual_sharp: bool = False


@dataclass(frozen=True)
class Datum:
    """One datum of the frame: its letter, its face and why it was chosen (9)."""

    letter: str
    face: int
    reason: str


@dataclass(frozen=True)
class Frame:
    """The datum frame: three orthonormal directions (x, y, z of the drawing), the
    datums A, B and C, and the part's extents along each direction."""

    directions: tuple[Vec3, Vec3, Vec3] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    datums: tuple[Datum, ...] = ()
    extents: tuple[tuple[float, float], ...] = ()
    model_axes: bool = True


@dataclass(frozen=True)
class Unclaimed:
    face: int
    area: float
    reason: str  # free_form, needs_auxiliary, skipped, unrecognised, model_defined


@dataclass(frozen=True)
class Coverage:
    """How much of a part the features claim: by feature count, face count and area."""

    features: int = 0
    features_unclaimed: int = 0
    faces: int = 0
    faces_claimed: int = 0
    area: float = 0.0
    area_claimed: float = 0.0

    @property
    def complete(self) -> bool:
        return self.faces_claimed >= self.faces and self.features_unclaimed == 0

    def words(self) -> str:
        """The wizard's sentence (10.10)."""
        if self.complete:
            return "every recognised face is dimensioned"
        left = self.faces - self.faces_claimed
        share = 0.0 if self.area <= 0 else 100.0 * (self.area - self.area_claimed) / self.area
        return (
            f"reduced-dimension drawing: {left} face{'s' if left != 1 else ''} "
            f"({share:.0f} % of the area, {self.features_unclaimed} feature"
            f"{'s' if self.features_unclaimed != 1 else ''}) are defined by the model"
        )


@dataclass(frozen=True)
class TurnedSegment:
    """One face of revolution of a turned part, along its axis: ``kind`` is cylinder,
    cone, torus or sphere; ``start`` and ``end`` its extent along the axis, metres
    from the larger end; ``diameter`` a cylinder's or sphere's, a cone's at ``start``
    with ``diameter_end`` its diameter at ``end``, a torus's at its tube's centre;
    ``internal`` for a face the material lies outside of (a bore). Faces of one
    cylinder split into several (seam halves) are one segment."""

    faces: tuple[int, ...]
    kind: str
    start: float
    end: float
    diameter: float
    diameter_end: float = 0.0
    internal: bool = False

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class TurnedProfile:
    """Why a part is a turned (lathe) part, and what its drawing is laid out on
    (``docs/DRAWINGS.md`` 10.5, 10.6; stage 2). Its faces of revolution share one axis,
    along frame axis ``frame_axis``, and ``axis`` points from the larger end toward the
    other, from a point on the larger end's plane. ``segments`` are those faces along
    it, outside faces before bores; ``length`` the part's extent along the axis;
    ``ends`` the planar end faces at the larger end and at the other (None where an end
    is not a plane). ``datum_a`` is a face of the default datum A, the longest
    cylindrical segment, and ``datum_b`` the default datum B, the end face at the larger
    end. ``mixed`` when other faces remain (flats, cross holes, keyseats), which the
    machined rules draw; ``share`` the part's area on the axis and the planes square to
    it; ``reason`` says it in words."""

    axis: Axis
    frame_axis: str
    segments: tuple[TurnedSegment, ...]
    length: float
    ends: tuple[int | None, int | None]
    datum_a: int
    datum_b: int | None
    mixed: bool = False
    share: float = 1.0
    reason: str = ""

    def cylinder_of(self, face: int) -> TurnedSegment | None:
        """The cylindrical segment a face belongs to, or None."""
        for s in self.segments:
            if s.kind == "cylinder" and face in s.faces:
                return s
        return None


@dataclass(frozen=True)
class FeatureSet:
    """Everything recognition found (6.4). ``features`` in recognition order, which is
    the order drawing ids are given in. ``model_defined`` holds the indices of the
    features a key-dimensions drawing leaves to the model (10.10), which the planner
    neither states nor locates; ``lettering`` those of them that are engraved letters,
    whose shared depth it still states once. ``turned`` is the part's
    :class:`TurnedProfile` when it looks turned (or mixed), else None."""

    features: tuple[Feature, ...] = ()
    frame: Frame = Frame()
    depths: tuple[Depth, ...] = ()
    unclaimed: tuple[Unclaimed, ...] = ()
    coverage: Coverage = Coverage()
    warnings: tuple[str, ...] = ()
    model_defined: frozenset[int] = frozenset()
    lettering: frozenset[int] = frozenset()
    turned: TurnedProfile | None = None

    def of_type(self, cls: type) -> list[tuple[int, Feature]]:
        """The features of a type, by index, but those left to the model."""
        return [
            (i, f) for i, f in enumerate(self.features) if isinstance(f, cls) and i not in self.model_defined
        ]


# --------------------------------------------------------------------------- views (6.5)

VIEW_KINDS = ("base", "projected", "section", "detail", "isometric")
STYLES = ("visible", "hidden", "tangent", "centre", "phantom", "border", "thin")

# The standard view frames (C5): d points from the part to the viewer, right = up x d.
STANDARD_VIEWS: dict[str, tuple[Vec3, Vec3]] = {
    "front": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "back": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "top": ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
    "bottom": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "isometric": ((1.0, 1.0, 1.0), (-1.0, 2.0, -1.0)),
}


def _unit(v: Vec3) -> Vec3:
    n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    if n == 0.0:
        raise InvalidArgumentError("a direction must not be zero", detail={"parameter": "direction"})
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class ViewSpec:
    """One view (6.5). ``direction`` points from the part toward the viewer and ``up``
    is the sheet's up; :meth:`frame` gives (right, up, direction) orthonormal and
    :meth:`axis_map` which model axis shows along each sheet axis (C5)."""

    id: str
    kind: str
    direction: Vec3
    up: Vec3
    name: str = ""  # front, top, right... for a principal view
    parent: str | None = None
    letter: str | None = None
    scale: tuple[int, int] | None = None  # None: the sheet's
    hidden: bool = True
    tangent: str = "hidden"
    cut: tuple[Vec3, Vec3] | None = None  # a section's plane (point, normal)
    circle: tuple[Vec3, float] | None = None  # a detail's centre and radius
    replaces: str | None = None

    def __post_init__(self) -> None:
        check_id(self.id, "view id")
        _choice(self.kind, VIEW_KINDS, "view kind")
        _choice(self.tangent, TANGENT_MODES, "tangent")

    def frame(self) -> tuple[Vec3, Vec3, Vec3]:
        """(right, up, d), orthonormal: ``up`` made square to ``d``, right = up x d."""
        d = _unit(self.direction)
        u = self.up
        u = _unit((u[0] - d[0] * _dot(u, d), u[1] - d[1] * _dot(u, d), u[2] - d[2] * _dot(u, d)))
        return _cross(u, d), u, d

    def project(self, p: Vec3) -> Vec2:
        """A model point's (x, y) in the view plane, metres, before scale and placement."""
        right, up, _d = self.frame()
        return _dot(p, right), _dot(p, up)

    def axis_map(self) -> dict[str, tuple[str, int]]:
        """For each sheet axis (``x``, ``y``) the model axis that shows along it and its
        sign, when one does: the front view gives {"x": ("x", 1), "y": ("y", 1)}."""
        out: dict[str, tuple[str, int]] = {}
        for sheet_axis, vec in zip(("x", "y"), self.frame()[:2], strict=True):
            for k, name in enumerate("xyz"):
                if abs(abs(vec[k]) - 1.0) < 1e-9:
                    out[sheet_axis] = (name, 1 if vec[k] > 0 else -1)
        return out


@dataclass(frozen=True)
class Source:
    """What a piece of view geometry comes from (6.7): the body index, the edge or face
    (its signature, so it survives a save) and the view."""

    body: int = 0
    kind: str = "edge"  # edge, face, silhouette, centre
    signature: str = ""
    view: str = ""


@dataclass(frozen=True)
class Run:
    """A run of curve in one view (C6): its primitive (a display-list geometry item in
    view coordinates, metres, before scale), its style and its source, and the curve
    parameter range of the source edge it covers."""

    primitive: Any
    style: str
    source: Source = Source()
    t_range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        _choice(self.style, STYLES, "style")


@dataclass(frozen=True)
class Witness:
    """A visible straight run square to a sheet axis (C8): at ``position`` along that
    axis it spans ``low`` to ``high`` across it, in view metres."""

    axis: str
    position: float
    low: float
    high: float
    source: Source = Source()


@dataclass(frozen=True)
class ViewGeometry:
    """What the hidden-line engine made of one view (6.5)."""

    view: str
    runs: tuple[Run, ...] = ()
    centre_marks: tuple[tuple[Vec2, float], ...] = ()  # centre and radius in view metres
    centre_lines: tuple[tuple[Vec2, Vec2], ...] = ()
    hatch: tuple[tuple[Vec2, ...], ...] = ()
    edge_visible: tuple[tuple[str, bool], ...] = ()
    faces_true_shape: tuple[int, ...] = ()
    axes_end_on: tuple[int, ...] = ()
    axes_side_on: tuple[int, ...] = ()
    virtual_sharps: tuple[Vec2, ...] = ()
    witnesses: tuple[Witness, ...] = ()

    def witness_at(self, axis: str, position: float, tol: float) -> Witness | None:
        """The visible run square to sheet ``axis`` at ``position`` within ``tol``, longest
        first, or None: the planner's question before it attaches a dimension (C8)."""
        best = None
        for w in self.witnesses:
            if w.axis == axis and abs(w.position - position) <= tol:
                if best is None or w.high - w.low > best.high - best.low:
                    best = w
        return best

    def bounds(self) -> tuple[float, float, float, float] | None:
        """(xmin, ymin, xmax, ymax) of the runs, view metres, or None when empty."""
        xs: list[float] = []
        ys: list[float] = []
        for r in self.runs:
            box = getattr(r.primitive, "bounds", None)
            if box is None:
                continue
            x0, y0, x1, y1 = box()
            xs += [x0, x1]
            ys += [y0, y1]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------- plan (6.6)

REQUIREMENT_KINDS = ("size", "location", "angle", "note")
ROLES = ("envelope", "feature_size", "feature_location", "pattern", "form")
TOLERANCE_CLASSES = ("block", "basic", "frame")
DIMENSION_KINDS = (
    "linear",
    "diameter",
    "radius",
    "angle",
    "ordinate",
    "chamfer",
    "hole_callout",
    "leader_note",
    "datum_feature",
    "frame",
)


def requirement_key(role: str, feature_ids: tuple[str, ...] | list[str], axis: str | None = None) -> str:
    """A requirement key (13.4): ``loc/f-7/x``, ``size/f-3``, ``pitch/f-4/f-5/y``."""
    for fid in feature_ids:
        check_id(fid, "feature id")
    parts = [role, *feature_ids]
    if axis is not None:
        parts.append(axis)
    return "/".join(parts)


@dataclass(frozen=True)
class Requirement:
    """Something the drawing must state (6.6). ``satisfied_by`` lists the dimension
    kinds that can, a ``leader_note`` among them for a size whose witnesses are hidden
    in every view (C17)."""

    key: str
    kind: str
    features: tuple[str, ...]
    value: float
    role: str
    axis: str | None = None
    graph: str | None = None
    satisfied_by: tuple[str, ...] = ()
    tolerance_class: str = "block"

    def __post_init__(self) -> None:
        _choice(self.kind, REQUIREMENT_KINDS, "requirement kind")
        _choice(self.role, ROLES, "role")
        _choice(self.tolerance_class, TOLERANCE_CLASSES, "tolerance class")
        for k in self.satisfied_by:
            _choice(k, DIMENSION_KINDS, "dimension kind")


@dataclass(frozen=True)
class FrameCell:
    """A feature control frame (10.5): characteristic, zone, its Ø, the material
    modifier and up to three datum references."""

    characteristic: str
    value: float
    diameter: bool = False
    modifier: str | None = None  # mmc, lmc or None
    datums: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoteLine:
    """One note (C27): words and, after them, frames drawn inline."""

    text: str
    frames: tuple[FrameCell, ...] = ()


@dataclass(frozen=True)
class Position:
    """A position along a frame axis, in model metres (C23): ``centre`` when it is an
    axis (with the radius of the round feature, so the extension line starts at its
    centre mark's end), else a face."""

    value: float
    centre: bool = False
    radius: float = 0.0
    features: tuple[str, ...] = ()  # C16: what the node stands for


@dataclass(frozen=True)
class PlannedDimension:
    """A dimension the planner chose (6.6, C15). ``positions`` are the two positions
    along ``axis`` for a linear or ordinate dimension; ``anchor`` and ``radius`` place a
    leader item; ``lines`` are its text lines, the value's prefix, value and suffix
    kept apart."""

    key: str
    id: str
    kind: str
    view: str
    value: float
    axis: str | None = None
    positions: tuple[Position, ...] = ()
    anchor: Vec3 | None = None
    radius: float = 0.0
    features: tuple[str, ...] = ()
    places: int = 2
    places_source: str = "role"  # role or user
    tolerance: str = "block"  # block, basic, reference, or an explicit kind of numbers.Tolerance
    tolerance_values: tuple[float, float] = (0.0, 0.0)
    prefix: str = ""
    suffix: tuple[str, ...] = ()
    frame: FrameCell | None = None
    role: str = "feature_size"
    side: str | None = None
    serves: tuple[str, ...] = ()
    state: str = "shown"  # shown or removed
    origin: str = "generated"  # generated or user

    def __post_init__(self) -> None:
        check_id(self.id, "dimension id")
        _choice(self.kind, DIMENSION_KINDS, "dimension kind")
        _choice(self.state, ("shown", "removed"), "state")
        _choice(self.origin, ("generated", "user"), "origin")


@dataclass(frozen=True)
class GraphResult:
    """One linear or angular graph's verdict (10.2): complete when every node reaches
    the origin, not redundant when the toleranced edges form a tree."""

    graph: str
    complete: bool
    redundant: bool
    missing: tuple[str, ...] = ()
    loops: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class BomLine:
    """One row of an assembly drawing's parts list (``docs/drawings/assemblies.md``):
    its item number, PART NUMBER, DESCRIPTION and QTY. as the bill of materials gives
    them (:mod:`solidseas.bom`), its level in an indented list, and the component
    tree ids of the instances it stands for. ``drawing`` is the number of the item's
    own drawing (DWG NO.), empty for an item with no file of its own; ``file`` the
    item's file name and ``properties`` its properties as text, which the plan reads
    the drawing number from; ``own_file`` is false for a component stored inside the
    assembly."""

    item: str
    part_number: str
    description: str = ""
    quantity: int = 1
    level: int = 0
    instances: tuple[str, ...] = ()
    drawing: str = ""
    file: str = ""
    own_file: bool = True
    properties: tuple[tuple[str, str], ...] = ()
    cells: tuple[str, ...] = ()  # the line's cells under Plan.bom_columns, when the drawing sets its own


@dataclass(frozen=True)
class Balloon:
    """An item balloon: the parts list's ``item`` it names, the view it is drawn in,
    the instance its leader points at and the point it ends on, a visible edge of
    that instance (a hidden one when the item is hidden behind other parts in every
    view), in view metres before scale as a view's runs are. ``others`` are
    the same for the other views that show the item, in order, for a layout that
    leaves the view out (an isometric with no room)."""

    item: str
    view: str
    instance: str
    at: Vec2
    others: tuple[tuple[str, str, Vec2], ...] = ()


@dataclass(frozen=True)
class Plan:
    """The planner's output (6.6). An assembly's plan also holds its parts list and
    item balloons; a part's has neither."""

    views: tuple[ViewSpec, ...] = ()
    dimensions: tuple[PlannedDimension, ...] = ()
    datums: tuple[Datum, ...] = ()
    notes: tuple[NoteLine, ...] = ()
    title: tuple[tuple[str, str], ...] = ()
    tolerance_block: tuple[str, ...] = ()
    graphs: tuple[GraphResult, ...] = ()
    coverage: Coverage = Coverage()
    bands: tuple[tuple[str, int], ...] = ()
    bom: tuple[BomLine, ...] = ()
    balloons: tuple[Balloon, ...] = ()
    bom_columns: tuple[str, ...] = ()  # the parts list's headings when the drawing sets its own
    bom_narrow: tuple[int, ...] = ()  # those columns as wide as their headings, centred (item, quantities)


# --------------------------------------------------------------------------- the drawing (6.8)


@dataclass(frozen=True)
class TitleField:
    text: str
    source: str = "typed"  # part, list, typed

    def __post_init__(self) -> None:
        _choice(self.source, ("part", "list", "typed"), "title field source")


@dataclass(frozen=True)
class FeatureRecord:
    """A feature as the drawing keeps it: id, descriptor and the user's decisions
    (thread confirmations, depth references, datum letters)."""

    id: str
    descriptor: Descriptor
    decisions: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class Signature:
    row: str
    name: str
    date: str
    digest: str


@dataclass(frozen=True)
class Revision:
    rev: str
    description: str
    zones: tuple[str, ...] = ()
    date: str | None = None
    approved: str | None = None


@dataclass(frozen=True)
class Output:
    kind: str  # pdf or dxf
    name: str
    sha256: str
    revision: str
    released: bool = False


@dataclass(frozen=True)
class Drawing:
    """The in-memory ``.ssdrw`` (6.8, 13.1). ``sheet`` is the laid-out display list
    (:class:`~solidseas.drawing.display.Sheet`); ``model`` the source's identity as
    13.1 lists it; ``unknown`` the members a newer SolidSeas wrote, kept unread."""

    id: str
    options: DrawingOptions
    settings: Any
    model: dict[str, Any] = field(default_factory=dict)
    title: tuple[tuple[str, TitleField], ...] = ()
    features: tuple[FeatureRecord, ...] = ()
    datums: tuple[Datum, ...] = ()  # C28: a member of its own
    dimensions: tuple[PlannedDimension, ...] = ()
    notes: tuple[tuple[str, NoteLine], ...] = ()
    status: str = "PRELIMINARY"
    signatures: tuple[Signature, ...] = ()
    revisions: tuple[Revision, ...] = ()
    outputs: tuple[Output, ...] = ()
    next_id: tuple[tuple[str, int], ...] = (("f", 1), ("d", 1), ("n", 1), ("v", 1))
    sheet: Any = None
    checks: tuple[Any, ...] = ()
    coverage: Coverage = Coverage()
    seconds: tuple[tuple[str, float], ...] = ()
    warnings: tuple[str, ...] = ()
    unknown: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _choice(self.status, STATUSES, "status")


__all__ = [
    "ARRANGEMENTS",
    "DETAIL_LEVELS",
    "DRAWING_MODES",
    "DIMENSION_KINDS",
    "DIRECTIONS",
    "MACHINING",
    "PROCESSES",
    "QUALITIES",
    "REQUIREMENT_KINDS",
    "ROLES",
    "SCHEMES",
    "SHEET_CHOICES",
    "STANDARD_VIEWS",
    "STATUSES",
    "STYLES",
    "TANGENT_MODES",
    "TOLERANCE_CLASSES",
    "UNIT_CHOICES",
    "VIEW_KINDS",
    "VIEW_NAMES",
    "AngledFace",
    "Axis",
    "Balloon",
    "Blend",
    "BomLine",
    "parts_list_spec",
    "parts_list_text",
    "Boss",
    "Chamfer",
    "Coverage",
    "Datum",
    "Depth",
    "Descriptor",
    "Drawing",
    "DrawingOptions",
    "Feature",
    "FeatureRecord",
    "FeatureSet",
    "Frame",
    "FrameCell",
    "GraphResult",
    "Groove",
    "Hole",
    "HoleSegment",
    "NoteLine",
    "Output",
    "Pattern",
    "Plan",
    "PlannedDimension",
    "Pocket",
    "Position",
    "Requirement",
    "Revision",
    "Run",
    "Signature",
    "Slot",
    "Source",
    "Step",
    "TitleField",
    "TurnedProfile",
    "TurnedSegment",
    "Unclaimed",
    "ViewGeometry",
    "ViewSpec",
    "Width",
    "Witness",
    "check_id",
    "requirement_key",
    "settings_type",
]
