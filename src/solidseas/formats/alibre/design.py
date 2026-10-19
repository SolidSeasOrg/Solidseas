"""``STEP_DATA``: an Alibre Design document's design database, and an assembly's
inclusions with their placements (provisional, ``docs/formats/alibre.md``).

The database is ISO 10303-21 text under the schemas ``ALIBRE_SCHEMA`` and
``CONFIG_CONTROL_DESIGN``: AP203-style product data and Alibre's own design
history, and no B-rep. SolidSeas reads only what places an assembly's parts:

* ``DESIGNPART`` or ``DESIGNASSEMBLY`` (what the document is); an assembly lists
  its ``DESIGNINCLUSION`` records;
* ``DESIGNINCLUSION((), (#member), path, #reference, $, #placement, $, .F., $,
  instance-guid, .F., #profile, 0, $, configuration)``, read by position, a
  record of any other shape skipped;
* ``REPOSITORYVERSIONREFERENCE(version, drive, path, document-guid, '', '', 1, 1,
  $)``: which document the inclusion places, by GUID and version;
* ``CARTESIAN_TRANSFORMATION_OPERATOR_3D($, $, $, axis1, axis2, local_origin,
  scale, axis3)`` with ``DIRECTION($, (x, y, z))`` and ``CARTESIAN_POINT($,
  (x, y, z))``: the placement, in the ISO 10303-42 attribute order, its axes
  completed by the standard rules (``base_axis``).

Person and organisation records are never read.
"""

import math
from dataclasses import dataclass

from ...errors import SldFormatError, SldLimitError
from .._source import Clock
from ..limits import Limits
from ..solidworks.components import Placement
from ._p21 import Part21, Ref
from .identity import normal_guid

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Inclusion:
    """One placed document: ``guid`` (the document's), ``version`` referenced,
    ``stored_path`` (the repository path the reference stores), ``configuration``,
    ``instance`` (the inclusion's own GUID), ``placement`` in database units (the
    translation not yet scaled) and ``scale``."""

    record: int
    guid: str
    version: int | None
    stored_path: str | None
    configuration: str | None
    instance: str | None
    rotation: tuple[Vec, Vec, Vec]
    origin: Vec
    scale: float

    @property
    def stored_name(self) -> str | None:
        if not self.stored_path:
            return None
        return self.stored_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or None

    def placement(self, metres_per_unit: float) -> Placement:
        """The placement with its translation in metres (``origin`` times the unit)."""
        s = self.scale
        rot = tuple(tuple(self.rotation[i][j] * s for j in range(3)) for i in range(3))
        return Placement(rot, tuple(x * metres_per_unit for x in self.origin))  # type: ignore[arg-type]


@dataclass(frozen=True)
class DesignDatabase:
    """``kind`` is ``part``, ``assembly`` or None; ``inclusions`` an assembly's
    readable inclusions; ``skipped`` how many inclusion records were not."""

    kind: str | None
    inclusions: tuple[Inclusion, ...]
    skipped: int
    schemas: tuple[str, ...]


def _unit(v, what: str) -> Vec:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not (math.isfinite(n) and n > 1e-12):
        raise SldFormatError(f"a placement's {what} is not a direction", detail={"stream": "STEP_DATA"})
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def base_axis(axis1: Vec | None, axis2: Vec | None, axis3: Vec | None) -> tuple[Vec, Vec, Vec]:
    """ISO 10303-42 ``base_axis`` for three dimensions: ``u3`` the unit ``axis3`` (z when
    absent), ``u1`` ``axis1`` with its part along ``u3`` removed (x, or y when x is
    parallel, when absent), ``u2`` ``axis2`` with its parts along ``u3`` and ``u1``
    removed (``u3 x u1`` when absent), each normalised."""
    u3 = _unit(axis3, "third axis") if axis3 is not None else (0.0, 0.0, 1.0)
    a1 = axis1 if axis1 is not None else ((1.0, 0.0, 0.0) if abs(u3[0]) < 0.9 else (0.0, 1.0, 0.0))
    d = _dot(a1, u3)
    u1 = _unit((a1[0] - d * u3[0], a1[1] - d * u3[1], a1[2] - d * u3[2]), "first axis")
    if axis2 is None:
        u2 = _cross(u3, u1)
    else:
        d3, d1 = _dot(axis2, u3), _dot(axis2, u1)
        u2 = _unit(
            (
                axis2[0] - d3 * u3[0] - d1 * u1[0],
                axis2[1] - d3 * u3[1] - d1 * u1[1],
                axis2[2] - d3 * u3[2] - d1 * u1[2],
            ),
            "second axis",
        )
    return u1, u2, u3


class _Shape(Exception):
    """A record whose shape is not the one this module reads."""


def _ref(p: Part21, v, want: str) -> int:
    if not isinstance(v, Ref) or p.type_of(v.id) != want:
        raise _Shape(want)
    return v.id


def _triple(p: Part21, rid: int, want: str) -> Vec:
    name, params = p.record(rid)
    if name != want or len(params) != 2 or not isinstance(params[1], tuple) or len(params[1]) != 3:
        raise _Shape(want)
    v = tuple(float(x) for x in params[1] if isinstance(x, (int, float)))
    if len(v) != 3 or not all(math.isfinite(x) for x in v):
        raise _Shape(want)
    return v  # type: ignore[return-value]


def _placement(p: Part21, rid: int) -> tuple[tuple[Vec, Vec, Vec], Vec, float]:
    name, params = p.record(rid)
    if name != "CARTESIAN_TRANSFORMATION_OPERATOR_3D" or len(params) != 8:
        raise _Shape("placement")
    a1 = _triple(p, params[3].id, "DIRECTION") if isinstance(params[3], Ref) else None
    a2 = _triple(p, params[4].id, "DIRECTION") if isinstance(params[4], Ref) else None
    origin = _triple(p, _ref(p, params[5], "CARTESIAN_POINT"), "CARTESIAN_POINT")
    scale = params[6] if isinstance(params[6], (int, float)) else 1.0
    a3 = _triple(p, params[7].id, "DIRECTION") if isinstance(params[7], Ref) else None
    if not (math.isfinite(scale) and scale != 0):
        raise _Shape("scale")
    u1, u2, u3 = base_axis(a1, a2, a3)
    rotation = tuple((u1[i], u2[i], u3[i]) for i in range(3))  # columns u1, u2, u3
    return rotation, origin, float(scale)  # type: ignore[return-value]


def _inclusion(p: Part21, rid: int) -> Inclusion:
    _name, q = p.record(rid)
    if len(q) != 15 or not isinstance(q[2], (str, type(None))):
        raise _Shape("DESIGNINCLUSION")
    ref = _ref(p, q[3], "REPOSITORYVERSIONREFERENCE")
    _rn, r = p.record(ref)
    if len(r) != 9 or not isinstance(r[3], str):
        raise _Shape("REPOSITORYVERSIONREFERENCE")
    guid = normal_guid(r[3])
    if guid is None:
        raise _Shape("guid")
    version = r[0] if isinstance(r[0], int) else None
    stored = r[2] if isinstance(r[2], str) and r[2] else (q[2] or None)
    if isinstance(q[5], Ref):
        rotation, origin, scale = _placement(p, _ref(p, q[5], "CARTESIAN_TRANSFORMATION_OPERATOR_3D"))
    elif q[5] is None:
        rotation, origin, scale = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0), 1.0
    else:
        raise _Shape("placement")
    instance = normal_guid(q[9]) if isinstance(q[9], str) else None
    config = q[14] if isinstance(q[14], str) and q[14] else None
    return Inclusion(rid, guid, version, stored, config, instance, rotation, origin, scale)


def read(data: bytes, limits: Limits, clock: Clock | None = None) -> DesignDatabase:
    """The design database (see the module notes)."""
    p = Part21(data, limits, clock)
    schemas = tuple(p.schemas)
    parts = p.ids_of_type("DESIGNPART")
    assemblies = p.ids_of_type("DESIGNASSEMBLY")
    kind = "assembly" if assemblies else ("part" if parts else None)
    inclusions: list[Inclusion] = []
    skipped = 0
    ids: list[int] = []
    for a in assemblies[:1]:
        _n, params = p.record(a)
        lists = [v for v in params if isinstance(v, tuple) and v and all(isinstance(x, Ref) for x in v)]
        for lst in lists:
            if all(p.type_of(x.id) == "DESIGNINCLUSION" for x in lst):
                ids.extend(x.id for x in lst)
    if not ids:
        ids = p.ids_of_type("DESIGNINCLUSION")
    if len(ids) > limits.inclusions:
        raise limits.exceeded(
            "inclusions", f"the assembly has more than {limits.inclusions:,} inclusions", len(ids)
        )
    for rid in ids:
        if clock is not None:
            clock.tick()
        try:
            inclusions.append(_inclusion(p, rid))
        except SldLimitError:
            raise
        except (_Shape, SldFormatError):
            skipped += 1
    return DesignDatabase(kind, tuple(inclusions), skipped, schemas)


__all__ = ["DesignDatabase", "Inclusion", "base_axis", "read"]
