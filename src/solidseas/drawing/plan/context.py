"""What every planning step reads: the model, its features with their drawing ids,
the views drawn, the options and settings, and the drawing's unit and scheme.

Feature ids are given here, once, in recognition order (``f-1``, ``f-2`` ...), so
requirement keys name features rather than graph nodes (C14). A drawing that already
exists passes its own ids in, matched by ``dwg-file``, and they are kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..facegraph import BrepModel, Plane
from ..types import DrawingOptions, FeatureSet, ViewGeometry, ViewSpec, settings_type

AXES = ("x", "y", "z")
Vec3 = tuple[float, float, float]


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def feature_ids(features: FeatureSet, given: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """The drawing's id for each feature, by index: ``given`` when a drawing already
    holds them, else ``f-1`` onward in recognition order."""
    if given is not None and len(given) == len(features.features):
        return tuple(given)
    return tuple(f"f-{k}" for k in range(1, len(features.features) + 1))


@dataclass
class Context:
    """One planning run's inputs, read by every step."""

    model: BrepModel
    features: FeatureSet
    views: tuple[tuple[ViewSpec, ViewGeometry], ...]
    options: DrawingOptions
    settings: Any
    unit: str = "mm"
    ids: tuple[str, ...] = ()
    hints: tuple[float, ...] = ()
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ids:
            self.ids = feature_ids(self.features)
        self.index_of = {fid: k for k, fid in enumerate(self.ids)}

    # ------------------------------------------------------------------ the drawing's choices

    @property
    def process(self) -> str:
        return self.options.process

    @property
    def scheme(self) -> str:
        return self.options.effective_scheme

    @property
    def tol(self) -> float:
        """Positions closer than this along an axis are one position."""
        return max(self.model.tolerance * 10.0, 1e-9)

    @property
    def dimensioning(self) -> dict:
        return self.settings.defaults.dimensioning[settings_type(self.process)]

    # ------------------------------------------------------------------ the frame

    def direction(self, axis: str) -> Vec3:
        return self.features.frame.directions[AXES.index(axis)]

    def along(self, axis: str, p) -> float:
        """A model point's coordinate along a frame axis, metres."""
        return dot(p, self.direction(axis))

    def axis_of(self, v, tol: float = 1e-6) -> str | None:
        """The frame axis a direction lies along, either way, or None."""
        for name in AXES:
            if abs(abs(dot(v, self.direction(name))) - 1.0) <= tol:
                return name
        return None

    def plane_axis(self, face: int) -> str | None:
        """The frame axis a planar face is square to, or None."""
        s = self.model.faces[face].surface
        if not isinstance(s, Plane):
            return None
        return self.axis_of(s.normal)

    def plane_at(self, face: int, axis: str) -> float:
        s = self.model.faces[face].surface
        return self.along(axis, s.origin)

    # ------------------------------------------------------------------ views

    def view(self, view_id: str) -> tuple[ViewSpec, ViewGeometry]:
        for spec, geom in self.views:
            if spec.id == view_id:
                return spec, geom
        raise KeyError(view_id)

    def sheet_axis(self, spec: ViewSpec, axis: str) -> tuple[str, int] | None:
        """The sheet axis (``x`` or ``y``) a frame axis shows along in a view, with its
        sign, or None when the axis is not in the view's plane."""
        right, up, _d = spec.frame()
        d = self.direction(axis)
        for name, vec in (("x", right), ("y", up)):
            c = dot(vec, d)
            if abs(abs(c) - 1.0) <= 1e-9:
                return name, 1 if c > 0 else -1
        return None

    def looks_along(self, spec: ViewSpec, v) -> bool:
        """Whether a view looks along direction ``v`` (either way): a hole on that axis
        is seen end on, in its circular view."""
        _r, _u, d = spec.frame()
        return abs(abs(dot(d, v)) - 1.0) <= 1e-6

    def orthographic(self) -> list[tuple[ViewSpec, ViewGeometry]]:
        return [(s, g) for s, g in self.views if s.kind != "isometric"]


__all__ = ["AXES", "Context", "Vec3", "dot", "feature_ids"]
