"""The drawing's frame and its datums (``docs/DRAWINGS.md`` 8.1, 9).

The frame is the model's axes when the largest planar faces lie square to them
(89 % of sampled parts and every drawn part), otherwise the frame of those faces.
Datum A is the largest planar face, B the largest square to A, C the largest
square to both; each keeps the reason it was chosen so the wizard can say it.
Once a drawing exists its datums follow their matched faces (``dwg-file``), never
"the largest" again: ``frame_hint`` carries them in.
"""

from __future__ import annotations

from ..facegraph import BrepModel, Plane
from ..types import Datum, Frame
from ._common import AXIS_NAMES, SQUARE_TOL, Vec3, cross, dot, extent, unit

REASONS = (
    "the largest planar face",
    "the largest planar face square to datum A",
    "the largest planar face square to datums A and B",
)
MODEL_AXES: tuple[Vec3, Vec3, Vec3] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _low_side(face) -> int:
    """0 for a face looking toward the low side of the axis it is square to, where the
    drawing's origin sits, else 1."""
    n = face.surface.normal
    k = max(range(3), key=lambda i: abs(n[i]))
    return 0 if n[k] < 0 else 1


def _planes(model: BrepModel):
    """Planar faces, largest first. Faces of equal area (to a millionth of the largest)
    put the one on the low side first, so a plate's datums sit on its bottom, left and
    front faces as a drawing's origin usually does; then by index so the order is
    stable."""
    faces = [f for f in model.faces if isinstance(f.surface, Plane)]
    if not faces:
        return []
    big = max(f.area for f in faces) or 1.0
    return sorted(faces, key=lambda f: (-round(f.area / big, 6), _low_side(f), f.index))


def _square(a: Vec3, b: Vec3) -> bool:
    return abs(dot(a, b)) <= SQUARE_TOL


def _parallel(a: Vec3, b: Vec3) -> bool:
    return abs(abs(dot(a, b)) - 1.0) <= SQUARE_TOL


def directions(model: BrepModel) -> tuple[tuple[Vec3, Vec3, Vec3], bool]:
    """The frame's three directions, named x, y, z, and whether they are the model's
    axes."""
    planes = _planes(model)
    if not planes:
        return MODEL_AXES, True
    a = planes[0].surface.normal
    b = next((f.surface.normal for f in planes if _square(f.surface.normal, a)), None)
    on_axes = any(_parallel(a, m) for m in MODEL_AXES) and (
        b is None or any(_parallel(b, m) for m in MODEL_AXES)
    )
    if on_axes:
        return MODEL_AXES, True
    if b is None:
        helper = MODEL_AXES[min(range(3), key=lambda i: abs(dot(a, MODEL_AXES[i])))]
        b = unit(cross(a, helper))
    c = unit(cross(a, b))
    dirs = [unit(a), unit(b), c]
    # name each direction after the model axis it lies closest to, pointing its way
    out: list[Vec3 | None] = [None, None, None]
    for d in sorted(dirs, key=lambda d: -max(abs(x) for x in d)):
        free = [i for i in range(3) if out[i] is None]
        i = max(free, key=lambda k: abs(d[k]))
        out[i] = d if d[i] >= 0 else (-d[0], -d[1], -d[2])
    x, y, _z = out
    z = cross(x, y)  # keep the frame right-handed
    return (x, y, z), False


def datums(model: BrepModel, frame: tuple[Vec3, Vec3, Vec3]) -> tuple[Datum, ...]:
    """Datums A, B and C on the largest planar faces square to the frame's axes."""
    chosen: list[Datum] = []
    normals: list[Vec3] = []
    for letter, why in zip("ABC", REASONS, strict=True):
        for f in _planes(model):
            n = f.surface.normal
            if not any(_parallel(n, d) for d in frame):
                continue
            if any(not _square(n, m) for m in normals):
                continue
            chosen.append(Datum(letter, f.index, why))
            normals.append(n)
            break
    return tuple(chosen)


def make_frame(model: BrepModel, frame_hint: Frame | None = None) -> Frame:
    """The frame of the part: directions, datums and extents along each axis. A hint
    (a drawing's own frame) is taken as it is, with its extents measured again."""
    if frame_hint is not None:
        dirs, model_axes, ds = frame_hint.directions, frame_hint.model_axes, frame_hint.datums
    else:
        dirs, model_axes = directions(model)
        ds = datums(model, dirs)
    extents = []
    for d in dirs:
        lo, hi = None, None
        for f in model.faces:
            a, b = extent(model, f, d)
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        extents.append((lo or 0.0, hi or 0.0))
    return Frame(tuple(dirs), tuple(ds), tuple(extents), model_axes)


def datum_axis(model: BrepModel, frame: Frame, datum: Datum) -> str | None:
    """The frame axis a datum face is square to."""
    n = model.faces[datum.face].surface.normal
    for name, d in zip(AXIS_NAMES, frame.directions, strict=True):
        if _parallel(n, d):
            return name
    return None


__all__ = ["REASONS", "datum_axis", "datums", "directions", "make_frame"]
