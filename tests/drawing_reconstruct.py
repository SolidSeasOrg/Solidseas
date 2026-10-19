"""The reconstruction oracle (``docs/DRAWINGS.md`` 19.3).

Written apart from the planner and without importing it: from the dimensions a
drawing shows (their values, kinds, axes, the positions they join and the
features they name) and the implied conventions of
``docs/drawings/conventions.md``, :func:`reconstruct` rebuilds every recognised
planar face's offset along its frame axis, every round feature's axis position,
every radius and diameter, the countersinks, chamfers, pitch-circle angles and
the steps of arc patterns, and compares each with the B-rep.

A recovered quantity is one the shown dimensions determine. The oracle writes
every dimension and every implied link as one linear equation in the unknown
positions and radii, fixes the frame's origins from the B-rep, and solves by
Gauss-Jordan elimination one equation at a time, implied links first and then
the dimensions in the order given:

- a target the equations leave undetermined is **missing**;
- a dimension whose equation adds nothing (it closes a loop through other
  toleranced or basic dimensions) is **redundant**, and the finding names the
  dimensions of the loop;
- a target determined at a value other than the B-rep's is **wrong**, and the
  finding names the dimensions it was rebuilt from;
- a dimension the oracle cannot attach to the model is **unresolved**.

Reference dimensions add no equation and are only compared with the model;
basic dimensions count like toleranced ones (conventions.md says why). The
oracle is bounded (by :class:`~solidseas.drawing.limits.DrawingLimits` and a
fixed amount of elimination work) and deterministic: the same inputs give the
same report, findings in a fixed order.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from solidseas.drawing import facegraph as F
from solidseas.drawing.limits import DEFAULT_LIMITS, DrawingLimits
from solidseas.drawing.types import Datum, FeatureSet, Frame, Pattern, PlannedDimension, Position
from solidseas.errors import InvalidArgumentError

AXES = ("x", "y", "z")
FINDING_KINDS = ("missing", "redundant", "wrong", "unresolved")
COUNT = re.compile(
    "^\\s*(\\d+)\\s*[Xx\u00d7]"
)  # the nX at the start of a prefix (Y14.5), or ISO's n times sign
DIAMETER_KINDS = ("diameter", "hole_callout", "leader_note")
RADIUS_NOTE = re.compile("(^|[\\sXx\u00d7])R\\s*$")  # a leader note whose symbol is R states a radius
IGNORED_KINDS = ("datum_feature", "frame")

_SQUARE = 1e-9  # a direction is a frame axis when its cosine is within this of 1
_ZERO = 1e-10  # coefficients smaller than this are nought
_WORK = 20_000_000  # coefficient updates the elimination may make
_CHAMFER_SHARE = 0.1  # a chamfer's legs are under this share of the part's diagonal (DRAWINGS.md 9)


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Conventions:
    """The implied conventions in force (``docs/drawings/conventions.md``). Each can be
    turned off to show what it carries; the defaults are the ones the planner is held
    to. ``share`` is how close a rebuilt value must be to the model's, as a share of the
    model's tolerance (``BrepModel.tolerance``, 1e-6 of its diagonal);
    ``angle_tolerance`` the same for angles, in radians. ``origins`` names a face per
    frame axis the frame's datums give no origin for."""

    coplanar: bool = True
    coaxial: bool = True
    tangent: bool = True
    square: bool = True
    equal_spacing: bool = True
    derived: bool = True
    share: float = 0.5
    angle_tolerance: float = 1e-7
    origins: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        for name in ("coplanar", "coaxial", "tangent", "square", "equal_spacing", "derived"):
            if not isinstance(getattr(self, name), bool):
                raise InvalidArgumentError(f"{name} must be true or false", detail={"parameter": name})
        for name in ("share", "angle_tolerance"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
                raise InvalidArgumentError(
                    f"{name} must be more than 0 and at most 1", detail={"parameter": name}
                )
        for item in self.origins:
            ok = (
                isinstance(item, tuple)
                and len(item) == 2
                and item[0] in AXES
                and isinstance(item[1], int)
                and not isinstance(item[1], bool)
            )
            if not ok:
                raise InvalidArgumentError(
                    "origins are (axis, face index) pairs", detail={"parameter": "origins"}
                )


DEFAULT_CONVENTIONS = Conventions()


@dataclass(frozen=True)
class Coincident:
    """Axes, centre planes or faces the drawing shows on one line across ``axis`` (a
    centre line drawn through them, or faces drawn in line): a zero basic dimension
    between each of ``positions``. This is how a drawing says a feature is symmetric
    about another's centre plane, or that holes share a centre line."""

    axis: str
    positions: tuple[Position, ...]
    id: str = ""


# --------------------------------------------------------------------------- the report


@dataclass(frozen=True)
class Finding:
    """One finding. ``what`` is the kind of quantity (``plane``, ``axis``, ``end``,
    ``extreme``, ``centre``, ``radius``, ``angle``, ``leg``, ``sharp``, ``count``,
    ``relation``, ``dimension``); ``faces`` the model faces it stands for; ``dimensions`` the ids of
    the dimensions involved; ``expected`` the B-rep's value and ``found`` the rebuilt
    one, metres or radians, when there are values to compare."""

    kind: str
    what: str
    axis: str | None
    faces: tuple[int, ...]
    dimensions: tuple[str, ...]
    words: str
    expected: float | None = None
    found: float | None = None

    def __str__(self) -> str:
        dims = f" [{', '.join(self.dimensions)}]" if self.dimensions else ""
        return f"{self.kind}: {self.words}{dims}"


@dataclass(frozen=True)
class Report:
    """What the oracle found. ``targets`` counts the quantities it checks and
    ``recovered`` those rebuilt at the model's value; ``uncovered`` lists the faces
    outside the oracle (face, reason); ``origins`` the origin of each frame axis."""

    findings: tuple[Finding, ...]
    targets: int
    recovered: int
    uncovered: tuple[tuple[int, str], ...] = ()
    origins: tuple[tuple[str, str], ...] = ()
    dimensions: int = 0

    @property
    def ok(self) -> bool:
        return not self.findings

    def of_kind(self, kind: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == kind)

    def counts(self) -> dict[str, int]:
        """Numbers only, as the corpus sweep prints them (20.3)."""
        out = {"targets": self.targets, "recovered": self.recovered}
        for kind in FINDING_KINDS:
            out[kind] = sum(1 for f in self.findings if f.kind == kind)
        out["uncovered"] = len(self.uncovered)
        out["dimensions"] = self.dimensions
        return out

    def summary(self) -> str:
        """The counts on one line: the corpus sweep's ``counts only``."""
        return ", ".join(f"{k} {v}" for k, v in self.counts().items())


# --------------------------------------------------------------------------- small helpers


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def _wrap(a: float) -> float:
    """An angle in (-pi, pi]."""
    a = math.fmod(a, 2 * math.pi)
    if a <= -math.pi:
        a += 2 * math.pi
    elif a > math.pi:
        a -= 2 * math.pi
    return a


def _mm(v: float) -> str:
    return f"{v * 1000:.4f} mm"


def _faces(faces) -> str:
    return ", ".join(str(f) for f in faces)


class _Unresolved(Exception):
    pass


@dataclass
class _Q:
    """One unknown: what it is, along which frame axis, the faces it stands for, the
    B-rep's value and whether the oracle must recover it (a target) or only uses it."""

    key: tuple
    what: str
    axis: str | None
    faces: tuple[int, ...]
    truth: float
    target: bool
    words: str


@dataclass
class _Row:
    coeffs: dict[int, float]
    rhs: float
    kind: str  # origin, implied, dim
    dims: tuple[str, ...]
    words: str
    located: int | None = None


@dataclass
class _Direct:
    """A size outside the linear equations: a countersink's angle, a chamfer's leg, a
    circular or arc pattern's first angle, an arc's step. ``said`` holds (dimension id,
    value, counts)."""

    what: str
    axis: str | None
    faces: tuple[int, ...]
    truth: float
    angle: bool
    words: str
    said: list = field(default_factory=list)
    implied: bool = False


@dataclass
class _Round:
    """A radius quantity: the cylinder faces of one radius on one axis, or a
    countersink cone at its entry."""

    key: tuple
    kind: str  # cylinder or csk
    faces: tuple[int, ...]
    radius: float
    point: tuple
    ka: int
    unit: tuple
    qid: int = -1


@dataclass
class _Unit:
    """One axis node's worth of round faces: an axis group when coaxiality is implied,
    else a single radius quantity."""

    key: tuple
    point: tuple
    ka: int
    faces: tuple[int, ...]
    radius: float


@dataclass
class _Circle:
    """Round units whose axes lie on one circle in the B-rep. ``start`` is, for an arc
    (members at one equal step that leave the circle open), the member the arc starts
    from going counter-clockwise, the one after its widest gap; None round a whole
    circle or at uneven steps."""

    key: tuple
    members: tuple[tuple, ...]  # unit keys, in angle order from +u
    ka: int
    uv: tuple[int, int]
    centre: tuple[float, float]
    radius: float
    angles: tuple[float, ...]
    faces: tuple[int, ...]
    start: int | None = None

    def ends(self) -> tuple[int, ...]:
        """The members an arc's first angle may be measured to or implied at: its two
        ends, or every member round a circle."""
        if self.start is None:
            return tuple(range(len(self.members)))
        return (self.start, (self.start - 1) % len(self.members))

    def beside(self, i: int) -> tuple[int, int]:
        n = len(self.members)
        return ((i + 1) % n, (i - 1) % n)


# --------------------------------------------------------------------------- the solver


class _Solver:
    """Gauss-Jordan elimination one equation at a time, kept reduced: each pivot appears
    in its own row only. Every row remembers which input equations it is made of, so
    a loop or a rebuilt value can name the dimensions behind it."""

    def __init__(self, limits: DrawingLimits) -> None:
        self.rows: dict[int, list] = {}  # pivot -> [coeffs, rhs, provenance]
        self.holding: dict[int, set[int]] = {}  # unknown -> pivots whose rows hold it
        self.work = 0
        self.limits = limits

    def _spend(self, n: int) -> None:
        self.work += n
        if self.work > _WORK:
            raise self.limits.exceeded(
                "requirements", "the reconstruction needs more elimination than the oracle allows"
            )

    def add(self, coeffs: dict[int, float], rhs: float, rid: int) -> tuple[bool, float, dict[int, float]]:
        """Add one equation. Returns (independent, residual, provenance): a dependent
        equation leaves its residual and the input equations it is a combination of."""
        c = {q: v for q, v in coeffs.items() if abs(v) > _ZERO}
        prov = {rid: 1.0}
        for q in sorted(k for k in c if k in self.rows):
            f = c.get(q, 0.0)
            if abs(f) <= _ZERO:
                continue
            rc, rr, rp = self.rows[q]
            for k, v in rc.items():
                c[k] = c.get(k, 0.0) - f * v
            rhs -= f * rr
            for k, v in rp.items():
                prov[k] = prov.get(k, 0.0) - f * v
            self._spend(len(rc) + len(rp))
        c = {k: v for k, v in c.items() if abs(v) > _ZERO}
        prov = {k: v for k, v in prov.items() if abs(v) > _ZERO}
        if not c:
            return False, rhs, prov
        p = min(c, key=lambda k: (-abs(c[k]), k))
        f = c[p]
        c = {k: v / f for k, v in c.items()}
        c[p] = 1.0
        rhs /= f
        prov = {k: v / f for k, v in prov.items()}
        for piv in sorted(self.holding.pop(p, ())):
            row = self.rows[piv]
            rc = row[0]
            g = rc.pop(p, 0.0)
            if abs(g) <= _ZERO:
                continue
            for k, v in c.items():
                if k == p:
                    continue
                nv = rc.get(k, 0.0) - g * v
                if abs(nv) > _ZERO:
                    rc[k] = nv
                    self.holding.setdefault(k, set()).add(piv)
                else:
                    rc.pop(k, None)
                    self.holding.get(k, set()).discard(piv)
            row[1] -= g * rhs
            rp = row[2]
            for k, v in prov.items():
                nv = rp.get(k, 0.0) - g * v
                if abs(nv) > _ZERO:
                    rp[k] = nv
                else:
                    rp.pop(k, None)
            self._spend(len(c) + len(prov))
        self.rows[p] = [c, rhs, prov]
        for k in c:
            if k != p:
                self.holding.setdefault(k, set()).add(p)
        return True, 0.0, prov

    def value(self, q: int) -> tuple[float, dict[int, float]] | None:
        """The value of ``q`` and its provenance when the equations determine it."""
        row = self.rows.get(q)
        if row is None or len(row[0]) != 1:
            return None
        return row[1], row[2]


# --------------------------------------------------------------------------- the oracle


def _feature_map(features, n_faces: int) -> dict[str, frozenset[int]] | None:
    if features is None:
        return None
    out: dict[str, frozenset[int]] = {}
    if isinstance(features, FeatureSet):
        fs = features.features
        for i, feat in enumerate(fs):
            faces = set(feat.faces)
            if isinstance(feat, Pattern):
                for m in feat.members:
                    if isinstance(m, int) and 0 <= m < len(fs):
                        faces.update(fs[m].faces)
            out[f"f-{i + 1}"] = frozenset(faces)
    elif isinstance(features, Mapping):
        for fid, faces in features.items():
            if not isinstance(fid, str) or isinstance(faces, (str, bytes)) or not isinstance(faces, Sequence):
                raise InvalidArgumentError(
                    "features map ids to sequences of face indices", detail={"parameter": "features"}
                )
            out[fid] = frozenset(faces)
    else:
        raise InvalidArgumentError(
            "features must be a FeatureSet or a mapping of ids to faces", detail={"parameter": "features"}
        )
    for faces in out.values():
        for f in faces:
            if isinstance(f, bool) or not isinstance(f, int) or not 0 <= f < n_faces:
                raise InvalidArgumentError(
                    "a feature names a face the model does not have", detail={"parameter": "features"}
                )
    return out


def _directions(frame: Frame):
    dirs = []
    try:
        for v in frame.directions:
            if len(v) != 3 or not all(math.isfinite(c) for c in v):
                raise ValueError
            dirs.append(_unit(tuple(float(c) for c in v)))
    except (TypeError, ValueError, ZeroDivisionError):
        raise InvalidArgumentError(
            "the frame needs three directions", detail={"parameter": "frame"}
        ) from None
    if len(dirs) != 3:
        raise InvalidArgumentError("the frame needs three directions", detail={"parameter": "frame"})
    for i in range(3):
        for j in range(i + 1, 3):
            if abs(_dot(dirs[i], dirs[j])) > 1e-9:
                raise InvalidArgumentError(
                    "the frame's directions must be square to each other", detail={"parameter": "frame"}
                )
    return tuple(dirs)


class _Oracle:
    def __init__(self, model, frame, conventions, features, limits) -> None:
        self.m = model
        self.frame = frame
        self.c = conventions
        self.limits = limits
        self.dirs = _directions(frame)
        self.tol = max(model.tolerance, 1e-12)  # merging, as the B-rep's own tolerance
        self.match = 10 * self.tol  # identifying what a position or anchor points at
        self.cmp = max(model.tolerance * conventions.share, 1e-12)  # comparing values
        self.features = _feature_map(features, len(model.faces))
        self.qkey: dict[tuple, int] = {}
        self.qs: list[_Q] = []
        self.origin_rows: list[_Row] = []
        self.implied: list[_Row] = []
        self.dim_rows: list[_Row] = []
        self.joined: set[tuple[int, int]] = set()
        self.stated: set[int] = set()  # radius quantities a size statement covers
        self.direct: dict[tuple, _Direct] = {}
        self.findings: list[Finding] = []
        self.uncovered: list[tuple[int, str]] = []
        self.references: list[tuple] = []
        self.origins: list[tuple[str, str]] = []
        self.circles: dict[tuple, _Circle] = {}
        self.pcd: dict[tuple, list[str]] = {}  # circle key -> dimension ids stating its diameter
        self.angles: dict[tuple, list] = {}  # circle key -> [(dimension, reference axis, counts)]
        self.steps: dict[tuple, list] = {}  # circle key -> [(dimension, counts)] stating an arc's step
        self.tangent: dict[int, list[tuple[int, int, int]]] = {}  # radius qid -> (axis, plane qid, side)
        self.sharps: list[list[tuple[float, tuple[int, ...], int]]] = [[], [], []]  # by axis
        self.angled: dict[int, list[int]] = {}  # angled face -> its meet lines' quantities
        self._catalogue()

    # ------------------------------------------------------------------ quantities

    def q(self, key, what, axis, faces, truth, target, words) -> int:
        qid = self.qkey.get(key)
        if qid is None:
            if len(self.qs) >= self.limits.requirements:
                raise self.limits.exceeded(
                    "requirements", "the model has more quantities than the oracle checks"
                )
            qid = self.qkey[key] = len(self.qs)
            self.qs.append(_Q(key, what, axis, tuple(sorted(faces)), truth, target, words))
        return qid

    def implied_row(self, coeffs, rhs, dims, words, located=None, check=True) -> None:
        """An implied link. It must hold for the B-rep's own values: one that does not is
        a relation the drawing shows wrongly (a centre line through features that are
        not in line, a derived radius that is not half its width)."""
        broken = sum(c * self.qs[q].truth for q, c in coeffs.items()) - rhs
        if check and abs(broken) > self.match:
            faces = tuple(sorted({f for q in coeffs for f in self.qs[q].faces}))
            self.findings.append(
                Finding(
                    "wrong",
                    "relation",
                    None,
                    faces,
                    tuple(dims),
                    f"the model breaks an implied relation: {words}",
                    0.0,
                    broken,
                )
            )
        self.implied.append(_Row(dict(coeffs), rhs, "implied", tuple(dims), words, located))

    def join(self, a: int, b: int, dims, words) -> None:
        if a == b:
            return
        pair = (min(a, b), max(a, b))
        if pair in self.joined:
            return
        self.joined.add(pair)
        self.implied_row({a: 1.0, b: -1.0}, 0.0, dims, words)

    def coord(self, p, k: int) -> float:
        return _dot(p, self.dirs[k])

    def square_to(self, v) -> int | None:
        for k in range(3):
            if abs(abs(_dot(v, self.dirs[k])) - 1.0) <= _SQUARE:
                return k
        return None

    # ------------------------------------------------------------------ the B-rep

    def _catalogue(self) -> None:
        m = self.m
        self.face_edges: dict[int, list] = {}
        for key in sorted(m.edges):
            e = m.edges[key]
            for f in sorted(set(e.faces)):
                if f >= 0:
                    self.face_edges.setdefault(f, []).append(e)
        planes: list[list[tuple[float, int]]] = [[], [], []]
        oblique: list[int] = []
        rounds: list[tuple[F.Face, int]] = []
        for f in m.faces:
            s = f.surface
            if f.kind == "plane":
                k = self.square_to(s.normal)
                if k is None:
                    oblique.append(f.index)
                else:
                    planes[k].append((self.coord(s.origin, k), f.index))
            elif f.kind in ("cylinder", "cone"):
                ka = self.square_to(s.axis)
                if ka is None:
                    self.uncovered.append((f.index, "an axis on no frame direction"))
                else:
                    rounds.append((f, ka))
            elif f.kind in ("torus", "sphere"):
                self.uncovered.append((f.index, f.kind))
            else:
                self.uncovered.append((f.index, "free-form"))
        self._planes(planes)
        self._rounds(rounds)
        self._tangency()
        self._chamfers(oblique)

    def _planes(self, planes) -> None:
        self.plane_nodes: list[list[tuple[float, tuple[int, ...], int]]] = [[], [], []]
        self.plane_of: dict[tuple[int, int], int] = {}
        for k in range(3):
            groups: list[list[tuple[float, int]]] = []
            for q, face in sorted(planes[k]):
                if self.c.coplanar and groups and abs(q - groups[-1][0][0]) <= self.tol:
                    groups[-1].append((q, face))
                else:
                    groups.append([(q, face)])
            for g in groups:
                q0 = g[0][0]
                faces = tuple(face for _q, face in g)
                qid = self.q(
                    ("plane", k, faces),
                    "plane",
                    AXES[k],
                    faces,
                    q0,
                    True,
                    f"plane {AXES[k]} = {_mm(q0)} (faces {_faces(faces)})",
                )
                self.plane_nodes[k].append((q0, faces, qid))
                for face in faces:
                    self.plane_of[(k, face)] = qid

    def _rounds(self, rounds) -> None:
        m = self.m
        group_of = {}
        for gi, g in enumerate(m.axis_groups):
            for face in g.faces:
                group_of[face] = gi
        self.rqs: list[_Round] = []
        self.units: dict[tuple, _Unit] = {}
        self.ends: list[list[tuple[float, tuple[int, ...], int]]] = [[], [], []]
        by_group: dict[int, list[_Round]] = {}
        cones: list[tuple[F.Face, int]] = []
        for f, ka in rounds:
            gi = group_of.get(f.index, -1 - f.index)
            if f.kind == "cone":
                cones.append((f, ka))
                continue
            s = f.surface
            group = by_group.setdefault(gi, [])
            for rq in group:
                if rq.kind == "cylinder" and abs(rq.radius - s.radius) <= self.tol:
                    rq.faces = (*rq.faces, f.index)
                    break
            else:
                point = m.axis_groups[gi].point if gi >= 0 else s.point
                group.append(_Round(("cyl", gi, f.index), "cylinder", (f.index,), s.radius, point, ka, ()))
        for f, ka in cones:
            self._cone(f, ka, group_of, by_group)
        for gi in sorted(by_group):
            for rq in by_group[gi]:
                rq.unit = ("g", gi) if self.c.coaxial else rq.key
                self.rqs.append(rq)
        for rq in self.rqs:
            unit = self.units.get(rq.unit)
            if unit is None:
                self.units[rq.unit] = _Unit(rq.unit, rq.point, rq.ka, rq.faces, rq.radius)
            else:
                unit.faces = tuple(sorted({*unit.faces, *rq.faces}))
                unit.radius = max(unit.radius, rq.radius)
        for key in sorted(self.units):
            unit = self.units[key]
            for k in range(3):
                if k == unit.ka:
                    continue
                v = self.coord(unit.point, k)
                self.q(
                    ("axis", k, key),
                    "axis",
                    AXES[k],
                    unit.faces,
                    v,
                    True,
                    f"axis of faces {_faces(unit.faces)} along {AXES[k]} at {_mm(v)}",
                )
        for rq in self.rqs:
            what = "radius" if rq.kind == "cylinder" else "countersink diameter"
            rq.qid = self.q(
                ("radius", rq.key),
                "radius",
                None,
                rq.faces,
                rq.radius,
                True,
                f"{what} of faces {_faces(rq.faces)} (R {_mm(rq.radius)})",
            )

    def _cone(self, f, ka, group_of, by_group) -> None:
        """A countersink is a target (its diameter at the surface and its angle); a drill
        point or a step's cone is the drill's and implied, the end of the full diameter
        before it a target; any other cone is outside the oracle."""
        s = f.surface
        circles = []
        for e in self.face_edges.get(f.index, []):
            if e.curve.kind != "circle":
                continue
            others = [o for o in e.faces if o != f.index and o >= 0]
            if others:
                circles.append((e, others[0]))
        kinds = {o: self.m.faces[o].kind for _e, o in circles}
        gi = group_of.get(f.index, -1 - f.index)
        if s.concave and circles:
            widest = max(circles, key=lambda c: c[0].curve.radius)
            other = self.m.faces[widest[1]]
            if other.kind == "plane" and self.square_to(other.surface.normal) == ka:
                point = self.m.axis_groups[gi].point if gi >= 0 else s.point
                rq = _Round(("csk", f.index), "csk", (f.index,), widest[0].curve.radius, point, ka, ())
                by_group.setdefault(gi, []).append(rq)
                angle = 2 * s.half_angle
                self.direct[("csk", f.index)] = _Direct(
                    "angle",
                    None,
                    (f.index,),
                    angle,
                    True,
                    f"countersink angle of face {f.index} ({math.degrees(angle):.3f} degrees)",
                )
                return
            if all(kinds[o] == "cylinder" for _e, o in circles) and len(circles) in (1, 2):
                if len(circles) == 1 and s.apex is None:
                    self.uncovered.append((f.index, "cone"))
                    return
                e, cyl = widest
                v = self.coord(e.curve.point, ka)
                qid = self.q(
                    ("end", ka, f.index),
                    "end",
                    AXES[ka],
                    (cyl, f.index),
                    v,
                    True,
                    f"end of the full diameter of face {cyl} along {AXES[ka]} at {_mm(v)}",
                )
                self.ends[ka].append((v, (cyl, f.index), qid))
                return
        self.uncovered.append((f.index, "cone"))

    def _tangency(self) -> None:
        """Where a plane square to a frame axis meets a cylinder along a tangent edge, the
        plane is the cylinder's extreme: plane = axis + side x radius."""
        cyl_rq = {}
        for rq in self.rqs:
            if rq.kind == "cylinder":
                for face in rq.faces:
                    cyl_rq[face] = rq
        seen = set()
        for key in sorted(self.m.edges):
            e = self.m.edges[key]
            if e.kind != "tangent" or len(set(e.faces)) != 2:
                continue
            a, b = e.faces[0], e.faces[1]
            for plane, cyl in ((a, b), (b, a)):
                rq = cyl_rq.get(cyl)
                fp = self.m.faces[plane] if plane >= 0 else None
                if rq is None or fp is None or fp.kind != "plane":
                    continue
                k = self.square_to(fp.surface.normal)
                if k is None or k == rq.ka:
                    continue
                pq = self.plane_of[(k, plane)]
                aq = self.qkey[("axis", k, rq.unit)]
                gap = self.qs[pq].truth - self.qs[aq].truth
                if abs(abs(gap) - rq.radius) > self.match:
                    continue
                side = 1 if gap > 0 else -1
                if (pq, aq, rq.qid, side) in seen:
                    continue
                seen.add((pq, aq, rq.qid, side))
                self.tangent.setdefault(rq.qid, []).append((k, pq, side))
                if self.c.tangent:
                    self.implied_row(
                        {pq: 1.0, aq: -1.0, rq.qid: -float(side)},
                        0.0,
                        (),
                        f"{self.qs[pq].words} is tangent to faces {_faces(rq.faces)}",
                    )

    def _chamfers(self, oblique) -> None:
        for face in oblique:
            f = self.m.faces[face]
            n = f.surface.normal
            flat = [k for k in range(3) if abs(_dot(n, self.dirs[k])) <= _SQUARE]
            legs = None
            if len(flat) == 1:
                a, b = (k for k in range(3) if k != flat[0])
                pa = pb = None
                for e in self.face_edges.get(face, []):
                    if e.curve.kind != "line" or e.kind != "convex":
                        continue
                    for o in e.faces:
                        if o == face or o < 0 or self.m.faces[o].kind != "plane":
                            continue
                        k = self.square_to(self.m.faces[o].surface.normal)
                        if k == a and pa is None:
                            pa = o
                        elif k == b and pb is None:
                            pb = o
                if pa is not None and pb is not None:
                    na, nb = _dot(n, self.dirs[a]), _dot(n, self.dirs[b])
                    off = _dot(n, f.surface.origin)
                    ua = self.qs[self.plane_of[(a, pa)]].truth
                    vb = self.qs[self.plane_of[(b, pb)]].truth
                    leg_b = abs((off - na * ua) / nb - vb)
                    leg_a = abs((off - nb * vb) / na - ua)
                    if max(leg_a, leg_b) < _CHAMFER_SHARE * self.m.diagonal:
                        legs = ((a, leg_a), (b, leg_b))
            if legs is None:
                if len(flat) != 1 or not self._angled(face, n, flat[0]):
                    self.uncovered.append((face, "angled face"))
                continue
            for k, leg in legs:
                self.direct[("leg", face, k)] = _Direct(
                    "leg",
                    AXES[k],
                    (face,),
                    leg,
                    False,
                    f"chamfer leg of face {face} along {AXES[k]} ({_mm(leg)})",
                )

    def _angled(self, face: int, n, flat: int) -> bool:
        """An angled face square to frame axis ``flat`` (conventions 2): its angle to the
        nearest principal plane, stated once, and a line it meets a principal face on,
        through a sharp edge or, past a round or chamfer, a virtual sharp, located along
        the axis across that face. Any one neighbour's line will do. False when it meets
        no principal face square to the other two axes."""
        lines = []
        off = _dot(n, self.m.faces[face].surface.origin)
        for o in self._principal_neighbours(face):
            g = self.m.faces[o]
            kk = self.square_to(g.surface.normal)
            if kk is None or kk == flat:
                continue
            jj = 3 - flat - kk
            across = _dot(n, self.dirs[jj])
            if abs(across) <= _SQUARE:
                continue
            value = (off - _dot(n, self.dirs[kk]) * self.coord(g.surface.origin, kk)) / across
            qid = self.q(
                ("sharp", jj, face, o),
                "sharp",
                AXES[jj],
                (face,),
                value,
                False,
                f"the line face {face} meets face {o} on, along {AXES[jj]} at {_mm(value)}",
            )
            self.sharps[jj].append((value, (face,), qid))
            lines.append(qid)
        if not lines:
            return False
        self.angled[face] = lines
        angle = math.acos(min(1.0, max(abs(_dot(n, d)) for d in self.dirs)))
        self.direct[("angled", face)] = _Direct(
            "angle",
            None,
            (face,),
            angle,
            True,
            f"angle of the angled face {face} ({math.degrees(angle):.3f} degrees)",
        )
        return True

    def _principal_neighbours(self, face: int) -> list[int]:
        """The planar faces square to a frame axis that ``face`` meets along a sharp
        edge, or past one round or chamfer it meets tangentially."""
        out = set()
        for e in self.face_edges.get(face, []):
            for o in e.faces:
                if o == face or o < 0:
                    continue
                if e.kind != "tangent":
                    if self._principal(o):
                        out.add(o)
                    continue
                for e2 in self.face_edges.get(o, []):
                    out.update(f for f in e2.faces if f not in (o, face) and f >= 0 and self._principal(f))
        return sorted(out)

    def _principal(self, face: int) -> bool:
        g = self.m.faces[face]
        return g.kind == "plane" and self.square_to(g.surface.normal) is not None

    # ------------------------------------------------------------------ origins

    def _origins(self) -> None:
        """One origin per frame axis, fixed at the model's value: the first datum (A, B, C)
        whose face gives that axis (a plane square to it, or a round whose axis is
        square to it), else the face the conventions name, else the largest face square
        to the axis, else the largest round feature."""
        letters: dict[str, int] = {}
        for d in self.frame.datums:
            ok = isinstance(d, Datum) and not isinstance(d.face, bool) and isinstance(d.face, int)
            if not ok or not 0 <= d.face < len(self.m.faces):
                raise InvalidArgumentError(
                    "a datum names a face the model does not have", detail={"parameter": "frame"}
                )
            letters.setdefault(str(d.letter), d.face)
        for _axis, face in self.c.origins:
            if not 0 <= face < len(self.m.faces):
                raise InvalidArgumentError(
                    "an origin names a face the model does not have", detail={"parameter": "conventions"}
                )
        for k in range(3):
            qid, why = None, ""
            given = [
                (f"the origin given for {AXES[k]}", face) for axis, face in self.c.origins if axis == AXES[k]
            ]
            for why_, face in [(f"datum {letter}", face) for letter, face in sorted(letters.items())] + given:
                qid = self._origin_of(face, k)
                if qid is not None:
                    why = why_
                    break
            if qid is None:
                qid, why = self._fallback_origin(k)
            if qid is None:
                continue
            self.origins.append((AXES[k], f"{why}: {self.qs[qid].words}"))
            self.origin_rows.append(_Row({qid: 1.0}, self.qs[qid].truth, "origin", (), why))

    def _origin_of(self, face: int, k: int) -> int | None:
        f = self.m.faces[face]
        if f.kind == "plane":
            return self.plane_of.get((k, face))
        for rq in self.rqs:
            if face in rq.faces and rq.ka != k:
                return self.qkey.get(("axis", k, rq.unit))
        return None

    def _fallback_origin(self, k: int) -> tuple[int | None, str]:
        nodes = self.plane_nodes[k]
        if nodes:
            best = min(nodes, key=lambda n: (-sum(self.m.faces[f].area for f in n[1]), n[0], n[2]))
            return best[2], "the largest face square to the axis"
        best = None
        for key in sorted(self.units):
            unit = self.units[key]
            qid = self.qkey.get(("axis", k, key))
            if qid is None:
                continue
            rank = (-unit.radius, self.qs[qid].truth, qid)
            if best is None or rank < best[0]:
                best = (rank, qid)
        if best is None:
            return None, ""
        return best[1], "the largest round feature"

    # ------------------------------------------------------------------ what dimensions point at

    def allowed(self, names) -> frozenset[int] | None:
        if self.features is None or not names:
            return None
        faces: set[int] = set()
        for name in names:
            if name not in self.features:
                raise _Unresolved(f"feature {name} is not in the feature table")
            faces |= self.features[name]
        return frozenset(faces)

    @staticmethod
    def _ok(faces, allowed) -> bool:
        return allowed is None or any(f in allowed for f in faces)

    def resolve(self, pos: Position, k: int, dim_id: str) -> int:
        """The unknown a position stands for along frame axis ``k``. A position that meets
        several axes, centre planes or faces at its value joins them (the drawing shows
        one line through them)."""
        if not isinstance(pos, Position):
            raise _Unresolved("a position is not a Position")
        v = pos.value
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise _Unresolved("a position has no finite value")
        allowed = self.allowed(pos.features)
        hits = self._centres(v, k, allowed) if pos.centre else self._surfaces(v, k, allowed)
        if not hits:  # an angled face's meet line (a sharp)
            hits = [
                qid
                for q, faces, qid in self.sharps[k]
                if abs(q - v) <= self.match and self._ok(faces, allowed)
            ]
        if not hits:
            kind = "axis or centre plane" if pos.centre else "face or extreme"
            raise _Unresolved(f"no {kind} at {_mm(v)} along {AXES[k]}")
        hits = sorted(set(hits))
        for other in hits[1:]:
            self.join(hits[0], other, (dim_id,), f"{dim_id} meets {self.qs[other].words} on one line")
        return hits[0]

    def _surfaces(self, v, k, allowed) -> list[int]:
        hits = [
            qid
            for q, faces, qid in self.plane_nodes[k]
            if abs(q - v) <= self.match and self._ok(faces, allowed)
        ]
        if hits:
            return hits
        hits = [
            qid for q, faces, qid in self.ends[k] if abs(q - v) <= self.match and self._ok(faces, allowed)
        ]
        if hits:
            return hits
        for rq in self.rqs:
            if rq.kind != "cylinder" or rq.ka == k or not self._ok(rq.faces, allowed):
                continue
            aq = self.qkey[("axis", k, rq.unit)]
            c = self.qs[aq].truth
            for side in (-1, 1):
                if abs(c + side * rq.radius - v) <= self.match:
                    hits.append(self.extreme(rq, k, side))
        return hits

    def extreme(self, rq: _Round, k: int, side: int) -> int:
        aq = self.qkey[("axis", k, rq.unit)]
        truth = self.qs[aq].truth + side * rq.radius
        key = ("ext", k, rq.key, side)
        new = key not in self.qkey
        qid = self.q(
            key,
            "extreme",
            AXES[k],
            rq.faces,
            truth,
            False,
            f"tangent extreme of faces {_faces(rq.faces)} along {AXES[k]} at {_mm(truth)}",
        )
        if new:
            self.implied_row(
                {qid: 1.0, aq: -1.0, rq.qid: -float(side)},
                0.0,
                (),
                f"{self.qs[qid].words} is its centre and radius",
            )
        return qid

    def _centres(self, v, k, allowed) -> list[int]:
        hits = []
        for key in sorted(self.units):
            unit = self.units[key]
            if unit.ka == k or not self._ok(unit.faces, allowed):
                continue
            qid = self.qkey[("axis", k, key)]
            if abs(self.qs[qid].truth - v) <= self.match:
                hits.append(qid)
        if allowed is None:
            return hits
        circle = self.circle(allowed)
        if circle is not None and k != circle.ka:
            qid = self.centre_q(circle, k)
            if abs(self.qs[qid].truth - v) <= self.match:
                hits.append(qid)
        nodes = [(q, qid) for q, faces, qid in self.plane_nodes[k] if self._ok(faces, allowed)]
        best = None
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                (qa, a), (qb, b) = nodes[i], nodes[j]
                if abs((qa + qb) / 2 - v) <= self.match:
                    width = abs(qb - qa)
                    if best is None or width > best[0]:
                        best = (width, a, b)
        if best is not None:
            hits.append(self.midplane(best[1], best[2], k))
        return hits

    def midplane(self, a: int, b: int, k: int) -> int:
        a, b = sorted((a, b))
        truth = (self.qs[a].truth + self.qs[b].truth) / 2
        key = ("mid", k, a, b)
        new = key not in self.qkey
        faces = (*self.qs[a].faces, *self.qs[b].faces)
        qid = self.q(
            key,
            "centre",
            AXES[k],
            faces,
            truth,
            False,
            f"centre plane of faces {_faces(sorted(faces))} along {AXES[k]}",
        )
        if new:
            self.implied_row({qid: 2.0, a: -1.0, b: -1.0}, 0.0, (), f"{self.qs[qid].words} is midway")
        return qid

    # ------------------------------------------------------------------ circular patterns

    def circle(self, allowed) -> _Circle | None:
        """The circular pattern the faces ``allowed`` form: three or more parallel round
        units whose axes lie on one circle in the B-rep."""
        units = [u for k, u in sorted(self.units.items()) if self._ok(u.faces, allowed)]
        if len(units) < 3 or len({u.ka for u in units}) != 1:
            return None
        key = tuple(u.key for u in units)
        if key in self.circles:
            return self.circles[key]
        ka = units[0].ka
        uv = ((ka + 1) % 3, (ka + 2) % 3)
        pts = [(self.coord(u.point, uv[0]), self.coord(u.point, uv[1])) for u in units]
        centre = None
        for i in range(2, len(pts)):
            (ax, ay), (bx, by), (cx, cy) = pts[0], pts[1], pts[i]
            d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            if abs(d) > 1e-18:
                a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
                centre = (
                    (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d,
                    (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d,
                )
                break
        if centre is None:
            return None
        radii = [math.dist(p, centre) for p in pts]
        if max(radii) - min(radii) > self.match:
            return None
        angles = [math.atan2(p[1] - centre[1], p[0] - centre[0]) % (2 * math.pi) for p in pts]
        order = sorted(range(len(units)), key=lambda i: (angles[i], i))
        faces = tuple(sorted({f for u in units for f in u.faces}))
        ordered = tuple(angles[i] for i in order)
        c = _Circle(
            key,
            tuple(units[i].key for i in order),
            ka,
            uv,
            centre,
            sum(radii) / len(radii),
            ordered,
            faces,
            self._arc_start(ordered),
        )
        self.circles[key] = c
        return c

    def _arc_start(self, angles) -> int | None:
        """Where an arc starts counter-clockwise (after its widest gap) when the angles,
        in order, are at one equal step that leaves the circle open; else None."""
        n = len(angles)
        gaps = [(angles[(i + 1) % n] - angles[i]) % (2 * math.pi) for i in range(n)]
        wide = max(range(n), key=lambda i: (gaps[i], -i))
        inner = [gaps[(wide + 1 + i) % n] for i in range(n - 1)]
        tol = 10 * self.c.angle_tolerance
        if any(abs(g - inner[0]) > tol for g in inner) or gaps[wide] <= inner[0] + tol:
            return None
        return (wide + 1) % n

    def centre_q(self, c: _Circle, k: int) -> int:
        truth = c.centre[c.uv.index(k)]
        key = ("pcentre", c.key, k)
        new = key not in self.qkey
        qid = self.q(
            key,
            "centre",
            AXES[k],
            c.faces,
            truth,
            False,
            f"pitch circle centre of faces {_faces(c.faces)} along {AXES[k]}",
        )
        if new and self.c.coaxial:
            for ukey in sorted(self.units):
                unit = self.units[ukey]
                if unit.ka != c.ka or ukey in c.members:
                    continue
                at = (self.coord(unit.point, c.uv[0]), self.coord(unit.point, c.uv[1]))
                if math.dist(at, c.centre) <= self.match:
                    self.join(
                        qid, self.qkey[("axis", k, ukey)], (), f"{self.qs[qid].words} is drawn concentric"
                    )
        return qid

    # ------------------------------------------------------------------ reading the dimensions

    def fillet_note(self, radius: float | None) -> None:
        """Rule 14: a fillet note states the radius of every fillet and round no
        dimension sizes. A round is told from a hole by its tangency to a face: those of
        the note's radius that nothing else states are stated by the note, and their
        tangency then places their axes."""
        if radius is None:
            return
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius):
            raise InvalidArgumentError(
                "fillet_radius must be a number", detail={"parameter": "fillet_radius"}
            )
        for rq in self.rqs:
            if rq.kind != "cylinder" or rq.qid in self.stated or rq.qid not in self.tangent:
                continue
            if abs(rq.radius - radius) > self.cmp:
                continue
            self.stated.add(rq.qid)
            self.dim_rows.append(
                _Row(
                    {rq.qid: 1.0},
                    float(radius),
                    "dim",
                    ("fillet note",),
                    "the fillet note sizes faces",
                    rq.qid,
                )
            )

    def read(self, dimensions, coincident) -> int:
        shown = 0
        for dim in dimensions:
            if dim.state == "removed" or dim.kind in IGNORED_KINDS:
                continue
            shown += 1
            try:
                self._read(dim)
            except _Unresolved as why:
                self.findings.append(Finding("unresolved", "dimension", dim.axis, (), (dim.id,), str(why)))
        for n, rel in enumerate(coincident):
            name = rel.id or f"coincident-{n + 1}"
            try:
                if rel.axis not in AXES or len(rel.positions) < 2:
                    raise _Unresolved("a coincidence joins two or more positions along a frame axis")
                k = AXES.index(rel.axis)
                ids = [self.resolve(p, k, name) for p in rel.positions]
                for other in ids[1:]:
                    self.join(ids[0], other, (name,), f"{name} shows {self.qs[other].words} on one line")
            except _Unresolved as why:
                self.findings.append(Finding("unresolved", "relation", rel.axis, (), (name,), str(why)))
        self._circles()
        return shown

    def _read(self, dim: PlannedDimension) -> None:
        v = dim.value
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise _Unresolved("the value is not a finite number of nought or more")
        if dim.kind == "angle":
            self._angle(dim)
        elif dim.kind == "chamfer":
            self._chamfer(dim)
        elif dim.axis is not None and len(dim.positions) == 2:
            self._linear(dim)
        elif dim.kind in DIAMETER_KINDS or dim.kind == "radius":
            self._size(dim)
        else:
            raise _Unresolved(f"a {dim.kind} dimension needs an axis and two positions")

    def _count(self, dim) -> int | None:
        m = COUNT.match(dim.prefix or "")
        return int(m.group(1)) if m else None

    def _count_finding(self, dim, said, found, faces, words) -> None:
        self.findings.append(
            Finding("wrong", "count", None, tuple(sorted(faces)), (dim.id,), words, float(found), float(said))
        )

    def _linear(self, dim) -> None:
        if dim.axis not in AXES:
            raise _Unresolved(f"axis {dim.axis!r} is not a frame axis")
        k = AXES.index(dim.axis)
        p0, p1 = dim.positions
        a = self.resolve(p0, k, dim.id)
        b = self.resolve(p1, k, dim.id)
        if a == b:
            raise _Unresolved("both ends are the same position")
        side = 1.0 if p1.value >= p0.value else -1.0
        if dim.kind in ("diameter", "radius"):
            ea, eb = self.qs[a].key, self.qs[b].key
            if ea[0] == eb[0] == "ext" and ea[2] == eb[2]:
                self.stated.add(self.qkey[("radius", ea[2])])
        n = self._count(dim)
        if n is not None and self.c.equal_spacing and dim.kind in ("linear", "ordinate"):
            self._pitch(dim, p0, p1, k, n)  # on a callout's depth line nX counts the holes
        if dim.tolerance == "reference":
            self.references.append(("linear", dim, a, b, side))
            return
        self.dim_rows.append(
            _Row({b: 1.0, a: -1.0}, side * dim.value, "dim", (dim.id,), f"{dim.id} along {dim.axis}", b)
        )

    def _pitch(self, dim, p0, p1, k, n) -> None:
        """nX on a dimension between two members of a pattern: the members lie on
        equally spaced lines square to the axis, n spaces of the stated pitch."""
        names = tuple(x for x in p0.features if x in p1.features) or (*p0.features, *p1.features)
        allowed = self.allowed(names)
        members = [u for key, u in sorted(self.units.items()) if u.ka != k and self._ok(u.faces, allowed)]
        if allowed is None or len(members) < 2:
            raise _Unresolved(f"{dim.prefix.strip()} needs a pattern of two or more members")
        lines: list[list[tuple[float, int]]] = []
        for q, qid in sorted(
            (self.qs[self.qkey[("axis", k, u.key)]].truth, self.qkey[("axis", k, u.key)]) for u in members
        ):
            if lines and abs(q - lines[-1][0][0]) <= self.match:
                lines[-1].append((q, qid))
            else:
                lines.append([(q, qid)])
        for line in lines:
            for _q, qid in line[1:]:
                self.join(
                    line[0][1], qid, (dim.id,), f"{dim.id}'s pattern puts {self.qs[qid].words} on one line"
                )
        if n != len(lines) - 1:
            faces = {f for u in members for f in u.faces}
            self._count_finding(
                dim, n, len(lines) - 1, faces, f"{dim.id} says {n} spaces; the pattern has {len(lines) - 1}"
            )
        reps = [line[0][1] for line in lines]
        for i in range(1, len(reps) - 1):
            self.implied_row(
                {reps[i + 1]: 1.0, reps[i]: -2.0, reps[i - 1]: 1.0},
                0.0,
                (dim.id,),
                f"{dim.id} spaces its pattern equally",
            )

    def _size(self, dim) -> None:
        diameter = dim.kind in DIAMETER_KINDS
        if dim.kind == "leader_note" and RADIUS_NOTE.search(dim.prefix or ""):
            diameter = False
        r_said = dim.value / 2 if diameter else dim.value
        n = self._count(dim)
        allowed = self.allowed(dim.features)
        if dim.kind == "diameter" and allowed is not None and dim.radius > 0:
            c = self.circle(allowed)
            if c is not None and abs(c.radius - dim.radius) <= self.match:
                self._pitch_circle(dim, c, r_said)
                return
        if allowed is None and dim.anchor is None and not dim.radius > 0:
            raise _Unresolved("a size names no feature, anchor or radius")
        found = []
        for rq in self.rqs:
            if not self._ok(rq.faces, allowed):
                continue
            if dim.radius > 0 and abs(rq.radius - dim.radius) > self.match:
                continue
            if dim.anchor is not None and n is None and not self._on_axis(dim.anchor, rq):
                continue
            found.append(rq)
        if not found:
            raise _Unresolved("no round face of that radius on the features named")
        faces = {f for rq in found for f in rq.faces}
        if n is None and len(found) > 1:
            self._count_finding(
                dim, 1, len(found), faces, f"{dim.id} has no nX but sizes {len(found)} rounds"
            )
        elif n is not None and n != len(found):
            self._count_finding(
                dim, n, len(found), faces, f"{dim.id} says {n}X; it sizes {len(found)} rounds"
            )
        for rq in found:
            if dim.tolerance == "derived":
                if self.c.derived:
                    self._derived(dim, rq)
                continue
            if dim.tolerance == "reference":
                self.references.append(("size", dim, rq.qid, r_said))
                continue
            self.stated.add(rq.qid)
            self.dim_rows.append(
                _Row({rq.qid: 1.0}, r_said, "dim", (dim.id,), f"{dim.id} sizes faces", rq.qid)
            )

    def _on_axis(self, anchor, rq: _Round) -> bool:
        try:
            rel = _sub(tuple(float(c) for c in anchor), rq.point)
        except (TypeError, ValueError, IndexError):
            raise _Unresolved("the anchor is not a point") from None
        d = self.dirs[rq.ka]
        t = _dot(rel, d)
        return _norm((rel[0] - t * d[0], rel[1] - t * d[1], rel[2] - t * d[2])) <= self.match

    def _derived(self, dim, rq: _Round) -> None:
        """ "R" with no value: the radius is half the width between the two parallel faces
        tangent to the round on either side."""
        self.stated.add(rq.qid)
        pairs = {}
        for k, pq, side in self.tangent.get(rq.qid, []):
            pairs.setdefault(k, {})[side] = pq
        for k in sorted(pairs):
            if -1 in pairs[k] and 1 in pairs[k]:
                lo, hi = pairs[k][-1], pairs[k][1]
                self.implied_row(
                    {rq.qid: 2.0, hi: -1.0, lo: 1.0}, 0.0, (dim.id,), f"{dim.id}: R is half the width", rq.qid
                )
                return
        self.findings.append(
            Finding(
                "wrong",
                "radius",
                None,
                rq.faces,
                (dim.id,),
                f"{dim.id} calls faces {_faces(rq.faces)} a full-round end, "
                "but no two parallel faces are tangent to it",
                rq.radius,
            )
        )

    def _pitch_circle(self, dim, c: _Circle, r_said) -> None:
        rq = self.q(
            ("pcd", c.key),
            "radius",
            None,
            c.faces,
            c.radius,
            False,
            f"pitch circle of faces {_faces(c.faces)}",
        )
        self.pcd.setdefault(c.key, [])
        if dim.tolerance == "reference":
            self.references.append(("size", dim, rq, r_said))
            return
        self.pcd[c.key].append(dim.id)
        self.dim_rows.append(
            _Row({rq: 1.0}, r_said, "dim", (dim.id,), f"{dim.id} states the pitch circle", rq)
        )

    def _angle(self, dim) -> None:
        allowed = self.allowed(dim.features)
        if allowed is None:
            raise _Unresolved("an angle names no feature")
        counts = dim.tolerance != "reference"
        angled = [self.direct[("angled", f)] for f in sorted(allowed) if ("angled", f) in self.direct]
        if dim.axis is None and angled:
            for d in angled:
                d.said.append((dim.id, dim.value, counts, d.truth))
            return
        if dim.axis is None and dim.radius > 0:
            c = self.circle(allowed)
            if c is not None and abs(c.radius - dim.radius) <= self.match:
                # an arc's step, drawn on its pitch circle as the pitch circle's
                # diameter is: from the first end to the second member, nX the spaces
                self.steps.setdefault(c.key, []).append((dim, counts))
                return
        if dim.axis is None:
            n = self._count(dim)
            found = []
            for key in sorted(k for k in self.direct if k[0] == "csk"):
                d = self.direct[key]
                if not self._ok(d.faces, allowed):
                    continue
                if dim.anchor is not None and n is None:
                    rq = next(r for r in self.rqs if r.key == key)
                    if not self._on_axis(dim.anchor, rq):
                        continue
                found.append(d)
            if not found:
                raise _Unresolved("no countersink on the features named")
            if (n or 1) != len(found):
                faces = {f for d in found for f in d.faces}
                self._count_finding(
                    dim, n or 1, len(found), faces, f"{dim.id} angles {len(found)} countersinks"
                )
            for d in found:
                d.said.append((dim.id, dim.value, counts, d.truth))
            return
        c = self.circle(allowed)
        if c is None or dim.axis not in AXES or AXES.index(dim.axis) not in c.uv:
            raise _Unresolved("an angle with an axis needs a circular pattern square to that axis")
        self.angles.setdefault(c.key, []).append((dim, AXES.index(dim.axis), counts))

    def _chamfer(self, dim) -> None:
        allowed = self.allowed(dim.features)
        if allowed is None:
            raise _Unresolved("a chamfer names no feature")
        n = self._count(dim)
        faces = sorted({key[1] for key in self.direct if key[0] == "leg" and key[1] in allowed})
        if not faces:
            raise _Unresolved("no chamfer on the features named")
        if (n or 1) != len(faces):
            self._count_finding(
                dim, n or 1, len(faces), faces, f"{dim.id} says {n or 1}X; it names {len(faces)} chamfers"
            )
        if dim.axis is not None and dim.axis not in AXES:
            raise _Unresolved(f"axis {dim.axis!r} is not a frame axis")
        for face in faces:
            for key in sorted(k for k in self.direct if k[0] == "leg" and k[1] == face):
                if dim.axis is None or AXES[key[2]] == dim.axis:
                    d = self.direct[key]
                    d.said.append((dim.id, dim.value, dim.tolerance != "reference", d.truth))

    def _circles(self) -> None:
        """Each circular or arc pattern the drawing gives a pitch circle, an angle or a
        step. Round a circle the members lie on the pitch circle at equal steps of 360
        degrees over the count, from the first member's angle, which a dimension states
        or a centre line implies. On an arc they lie from the first end at the step the
        drawing states, as many steps as its nX counts, the way the step is drawn."""
        quarter_turn = math.pi / 2
        for key in sorted(set(self.pcd) | set(self.angles) | set(self.steps)):
            c = self.circles[key]
            n = len(c.members)
            steps = self.steps.get(key, [])
            arc = c.start is not None or bool(steps)
            d = _Direct(
                "angle", None, c.faces, c.angles[0], True, f"angle of the pattern of faces {_faces(c.faces)}"
            )
            first, theta, dims = None, None, list(self.pcd.get(key, []))
            for dim, kref, counts in self.angles.get(key, []):
                i, ray, ang = self._first(dim, kref, c, c.ends() if arc else None)
                d.said.append((dim.id, dim.value, counts, abs(_wrap(c.angles[i] - ray))))
                if counts and theta is None:
                    first, theta = i, ang
                    dims.append(dim.id)
            second = self._second(steps, c)
            if self.c.square:
                # an arc's first angle is implied only at an end, and at the end the step
                # is drawn from when both are on centre lines: from a hole in the middle
                # the drawing would not say which way the step runs
                ends = range(n)
                if arc:
                    ends = sorted(c.ends(), key=lambda i: (second not in c.beside(i), i))
                for i in ends:
                    a = c.angles[i]
                    if abs(_wrap(a - round(a / quarter_turn) * quarter_turn)) <= self.c.angle_tolerance:
                        d.implied = True
                        if theta is None:
                            first, theta = i, round(a / quarter_turn) * quarter_turn
                        break
            self.direct[("pattern", key)] = d
            if arc:
                self._arc(c, steps, first, theta, second, dims)
                continue
            if theta is None or not self.c.equal_spacing:
                continue
            step = 2 * math.pi / n
            radius, cu, cv = self._pitch_quantities(c)
            for i, ukey in enumerate(c.members):
                t = round(((c.angles[i] - c.angles[first]) % (2 * math.pi)) / step) % n
                self._on_pitch_circle(c, ukey, theta + t * step, (radius, cu, cv), dims)
                gap = _wrap(c.angles[i] - c.angles[first] - t * step)
                if abs(gap) > self.c.angle_tolerance:
                    self._uneven(c, ukey, dims, t * step, c.angles[i] - c.angles[first])

    def _pitch_quantities(self, c: _Circle) -> tuple[int, int, int]:
        """The pitch circle's radius and its centre along the two axes square to it."""
        radius = self.q(
            ("pcd", c.key),
            "radius",
            None,
            c.faces,
            c.radius,
            False,
            f"pitch circle of faces {_faces(c.faces)}",
        )
        return radius, self.centre_q(c, c.uv[0]), self.centre_q(c, c.uv[1])

    def _on_pitch_circle(self, c: _Circle, ukey, ang: float, pitch, dims) -> None:
        radius, cu, cv = pitch
        for k, cq, trig in ((c.uv[0], cu, math.cos(ang)), (c.uv[1], cv, math.sin(ang))):
            mq = self.qkey[("axis", k, ukey)]
            self.implied_row(
                {mq: 1.0, cq: -1.0, radius: -trig},
                0.0,
                tuple(dims),
                f"{self.qs[mq].words} is on the pitch circle",
                check=False,  # the angle is stated, not implied: a wrong one shows on the members
            )

    def _uneven(self, c: _Circle, ukey, dims, expected: float, found: float) -> None:
        self.findings.append(
            Finding(
                "wrong",
                "relation",
                None,
                self.units[ukey].faces,
                tuple(dims),
                f"the pattern of faces {_faces(c.faces)} is not equally spaced",
                expected,
                found,
            )
        )

    def _second(self, steps, c: _Circle) -> int | None:
        """The member the first step dimension with an anchor is drawn to: the second
        from the first end. An anchor that is not a point says nothing."""
        p = None
        for dim, _counts in steps:
            try:
                at = tuple(float(x) for x in dim.anchor)
                p = (self.coord(at, c.uv[0]), self.coord(at, c.uv[1]))
                break
            except (TypeError, ValueError, IndexError):
                continue
        if p is None:
            return None

        def gap(j):
            a = c.angles[j]
            return math.dist(p, (c.centre[0] + c.radius * math.cos(a), c.centre[1] + c.radius * math.sin(a)))

        return min(range(len(c.members)), key=lambda j: (gap(j), j))

    def _arc(self, c: _Circle, steps, first, theta, second, dims) -> None:
        """An arc pattern rebuilt from the drawing alone: the first end at its angle, then
        the members the stated step apart, as many as the step's nX counts spaces (one
        without nX), running from the first end towards the member the step is drawn to
        (into the arc when the step has no anchor). The step is a target of its own, so
        a drawing that leaves it out leaves it, and every member past the first, missing."""
        n = len(c.members)
        if first is None:
            # nothing places the first end: the step is still compared with the model's
            at = c.start if c.start is not None else 0
            truth = (c.angles[(at + 1) % n] - c.angles[at]) % (2 * math.pi)
            self.direct[("step", c.key)] = self._step_direct(c, truth, steps)
            return
        if second in c.beside(first):
            sign = 1.0 if second == (first + 1) % n else -1.0
        else:
            sign = -1.0 if c.start is not None and first == (c.start - 1) % n else 1.0
        model_step = (sign * (c.angles[c.beside(first)[0 if sign > 0 else 1]] - c.angles[first])) % (
            2 * math.pi
        )
        self.direct[("step", c.key)] = self._step_direct(c, model_step, steps)
        counted = [dim for dim, counts in steps if counts]
        stated, spaces = None, 0
        if counted:
            dim = counted[0]
            stated = dim.value
            said = self._count(dim)
            spaces = 1 if said is None else said
            if said is not None and said != n - 1:
                self._count_finding(
                    dim, said, n - 1, c.faces, f"{dim.id} says {said} spaces; the arc has {n - 1}"
                )
            dims = [*dims, dim.id]
        if theta is None or not self.c.equal_spacing:
            return
        pitch = self._pitch_quantities(c)
        for i, ukey in enumerate(c.members):
            t = round(((sign * (c.angles[i] - c.angles[first])) % (2 * math.pi)) / model_step)
            if t > spaces:
                continue  # past the spaces the drawing gives: left missing
            self._on_pitch_circle(c, ukey, theta + sign * t * (stated or 0.0), pitch, dims)
            gap = _wrap(c.angles[i] - c.angles[first] - sign * t * model_step)
            if abs(gap) > self.c.angle_tolerance:
                self._uneven(c, ukey, dims, sign * t * model_step, c.angles[i] - c.angles[first])

    def _step_direct(self, c: _Circle, truth: float, steps) -> _Direct:
        sd = _Direct("angle", None, c.faces, truth, True, f"step of the arc of faces {_faces(c.faces)}")
        for dim, counts in steps:
            sd.said.append((dim.id, dim.value, counts, truth))
        return sd

    def _first(self, dim, kref: int, c: _Circle, among=None) -> tuple[int, float, float]:
        """The member an angle dimension measures (the one at its anchor, else the one of
        ``among``, every member by default, nearest the reference direction), that
        direction (the frame axis ``kref`` either way through the centre, whichever is
        nearer the member), and the angle the dimension gives the member, on the side it
        is drawn."""
        p = None
        if dim.anchor is not None:
            try:
                at = tuple(float(x) for x in dim.anchor)
                p = (self.coord(at, c.uv[0]), self.coord(at, c.uv[1]))
            except (TypeError, ValueError, IndexError):
                raise _Unresolved("the anchor is not a point") from None
        rays = (0.0, math.pi) if kref == c.uv[0] else (math.pi / 2, -math.pi / 2)

        def at_member(j):
            a = c.angles[j]
            return (c.centre[0] + c.radius * math.cos(a), c.centre[1] + c.radius * math.sin(a))

        if p is not None:
            i = min(range(len(c.members)), key=lambda j: (math.dist(p, at_member(j)), j))
        else:
            pool = range(len(c.members)) if among is None else among
            i = min(pool, key=lambda j: (min(abs(_wrap(c.angles[j] - r)) for r in rays), j))
        ray = min(rays, key=lambda r: abs(_wrap(c.angles[i] - r)))
        side = 1.0 if _wrap(c.angles[i] - ray) >= 0 else -1.0
        return i, ray, ray + side * dim.value

    # ------------------------------------------------------------------ solving and reporting

    def solve(self) -> None:
        solver = _Solver(self.limits)
        rows = self.origin_rows + self.implied + self.dim_rows
        self.rows = rows
        for rid, row in enumerate(rows):
            independent, residual, prov = solver.add(row.coeffs, row.rhs, rid)
            if independent:
                continue
            if row.kind == "dim":
                self._redundant(row, residual, prov)
        self.solver = solver

    def _dims(self, prov) -> tuple[str, ...]:
        out = []
        for rid in sorted(prov):
            for d in self.rows[rid].dims:
                if d not in out:
                    out.append(d)
        return tuple(out)

    def _redundant(self, row, residual, prov) -> None:
        q = self.qs[row.located]
        dims = self._dims(prov)
        words = f"{q.words} is recovered twice: {row.dims[0]} closes a loop"
        if abs(residual) > self.cmp:
            words += f" and disagrees by {_mm(abs(residual))}"
        self.findings.append(Finding("redundant", q.what, q.axis, q.faces, dims, words))

    def report(self, shown: int) -> Report:
        targets = recovered = 0
        touching: dict[int, list[str]] = {}
        for row in self.rows:
            for qid in row.coeffs:
                for d in row.dims:
                    if d not in touching.setdefault(qid, []):
                        touching[qid].append(d)
        for qid, q in enumerate(self.qs):
            if not q.target:
                continue
            targets += 1
            got = self.solver.value(qid)
            radius = q.key[0] == "radius"
            if got is None or (radius and qid not in self.stated):
                why = "its size is not stated" if got is not None else "the dimensions do not determine it"
                self.findings.append(
                    Finding(
                        "missing",
                        q.what,
                        q.axis,
                        q.faces,
                        tuple(touching.get(qid, ())),
                        f"{q.words}: {why}",
                        q.truth,
                    )
                )
                continue
            value, prov = got
            if abs(value - q.truth) > self.cmp:
                self.findings.append(
                    Finding(
                        "wrong",
                        q.what,
                        q.axis,
                        q.faces,
                        self._dims(prov),
                        f"{q.words} is rebuilt at {_mm(value)}",
                        q.truth,
                        value,
                    )
                )
                continue
            recovered += 1
        for key in sorted(self.direct, key=repr):
            d = self.direct[key]
            targets += 1
            counted = [s for s in d.said if s[2]]
            sources = len(counted) + (1 if d.implied else 0)
            tol = self.c.angle_tolerance if d.angle else self.cmp
            bad = [s for s in d.said if abs(s[1] - s[3]) > tol]
            if sources == 0:
                self.findings.append(
                    Finding(
                        "missing",
                        d.what,
                        d.axis,
                        d.faces,
                        tuple(s[0] for s in d.said),
                        f"{d.words}: not stated",
                        d.truth,
                    )
                )
                continue
            if sources > 1:
                self.findings.append(
                    Finding(
                        "redundant",
                        d.what,
                        d.axis,
                        d.faces,
                        tuple(s[0] for s in counted),
                        f"{d.words} is stated {sources} times"
                        + (", once by a centre line" if d.implied else ""),
                    )
                )
            for s in bad:
                shown = f"{math.degrees(s[1]):.4f} degrees" if d.angle else _mm(s[1])
                model = f"{math.degrees(s[3]):.4f} degrees" if d.angle else _mm(s[3])
                self.findings.append(
                    Finding(
                        "wrong",
                        d.what,
                        d.axis,
                        d.faces,
                        (s[0],),
                        f"{d.words}: {s[0]} says {shown}, the model {model}",
                        s[3],
                        s[1],
                    )
                )
            if not bad:
                recovered += 1
        for face in sorted(self.angled):
            targets += 1
            located = [(qid, self.solver.value(qid)) for qid in self.angled[face]]
            located = [(qid, got) for qid, got in located if got is not None]
            if not located:
                self.findings.append(
                    Finding(
                        "missing",
                        "sharp",
                        None,
                        (face,),
                        (),
                        f"the angled face {face}: no line it meets a principal face on is located",
                    )
                )
                continue
            bad = [(qid, got) for qid, got in located if abs(got[0] - self.qs[qid].truth) > self.cmp]
            for qid, (value, prov) in bad:
                q = self.qs[qid]
                self.findings.append(
                    Finding(
                        "wrong",
                        "sharp",
                        q.axis,
                        q.faces,
                        self._dims(prov),
                        f"{q.words} is rebuilt at {_mm(value)}",
                        q.truth,
                        value,
                    )
                )
            if not bad:
                recovered += 1
        for ref in self.references:
            if ref[0] == "linear":
                _k, dim, a, b, side = ref
                truth = side * (self.qs[b].truth - self.qs[a].truth)
                said, faces, what = dim.value, (*self.qs[a].faces, *self.qs[b].faces), "dimension"
            else:
                _k, dim, qid, said = ref
                truth, faces, what = self.qs[qid].truth, self.qs[qid].faces, "radius"
            if abs(said - truth) > self.cmp:
                self.findings.append(
                    Finding(
                        "wrong",
                        what,
                        dim.axis,
                        tuple(sorted(set(faces))),
                        (dim.id,),
                        f"reference {dim.id} says {_mm(said)} where the model has {_mm(truth)}",
                        truth,
                        said,
                    )
                )
        order = {k: i for i, k in enumerate(FINDING_KINDS)}
        findings = sorted(
            self.findings, key=lambda f: (order[f.kind], f.axis or "", f.what, f.faces, f.dimensions, f.words)
        )
        return Report(
            tuple(findings),
            targets,
            recovered,
            tuple(sorted(self.uncovered)),
            tuple(self.origins),
            shown,
        )


def reconstruct(
    model: F.BrepModel,
    frame: Frame,
    dimensions: Sequence[PlannedDimension],
    conventions: Conventions = DEFAULT_CONVENTIONS,
    *,
    features: FeatureSet | Mapping[str, Sequence[int]] | None = None,
    coincident: Sequence[Coincident] = (),
    limits: DrawingLimits = DEFAULT_LIMITS,
    fillet_radius: float | None = None,
) -> Report:
    """Rebuild the model from the dimensions a drawing shows and say what is missing,
    redundant or wrong (``docs/DRAWINGS.md`` 19.3, ``docs/drawings/conventions.md``).

    ``frame`` gives the frame's directions and its datums, whose faces are the origins.
    ``features`` maps the feature ids the dimensions and positions name to model faces:
    a mapping, or a ``FeatureSet`` whose features are ``f-1``, ``f-2``... in order
    (13.4); without one, positions are matched by value alone. ``coincident`` lists the
    centre lines and in-line faces the drawing shows without a value. ``fillet_radius``
    is the radius the drawing's fillet note states (rule 14), or None without one."""
    if not isinstance(model, F.BrepModel):
        raise InvalidArgumentError("model must be a BrepModel", detail={"parameter": "model"})
    if not isinstance(frame, Frame):
        raise InvalidArgumentError("frame must be a Frame", detail={"parameter": "frame"})
    if not isinstance(conventions, Conventions):
        raise InvalidArgumentError("conventions must be a Conventions", detail={"parameter": "conventions"})
    if not isinstance(limits, DrawingLimits):
        raise InvalidArgumentError("limits must be a DrawingLimits", detail={"parameter": "limits"})
    if isinstance(dimensions, (str, bytes)) or not isinstance(dimensions, Sequence):
        raise InvalidArgumentError("dimensions must be a sequence", detail={"parameter": "dimensions"})
    if len(dimensions) > limits.dimensions:
        raise limits.exceeded(
            "dimensions", f"the drawing shows {len(dimensions):,} dimensions, more than the oracle reads"
        )
    if not all(isinstance(d, PlannedDimension) for d in dimensions):
        raise InvalidArgumentError(
            "dimensions must be PlannedDimension records", detail={"parameter": "dimensions"}
        )
    if isinstance(coincident, (str, bytes)) or not isinstance(coincident, Sequence):
        raise InvalidArgumentError("coincident must be a sequence", detail={"parameter": "coincident"})
    if not all(isinstance(c, Coincident) for c in coincident):
        raise InvalidArgumentError(
            "coincident must hold Coincident records", detail={"parameter": "coincident"}
        )
    if len(coincident) > limits.dimensions:
        raise limits.exceeded("dimensions", "the drawing shows more relations than the oracle reads")
    oracle = _Oracle(model, frame, conventions, features, limits)
    oracle._origins()
    shown = oracle.read(dimensions, coincident)
    oracle.fillet_note(fillet_radius)  # after the dimensions: what they size, they state
    oracle.solve()
    return oracle.report(shown)


__all__ = [
    "AXES",
    "DEFAULT_CONVENTIONS",
    "FINDING_KINDS",
    "Coincident",
    "Conventions",
    "Finding",
    "Report",
    "reconstruct",
]
