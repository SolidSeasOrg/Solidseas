# Rolling blends approximated by rational B-spline surfaces, deviation measured.
#
# Derived work. The construction (the spine sampled, the feet of the sphere on its two
# supports, an exact circular arc between the feet at each spine point as a rational
# quadratic row, the rows lofted cubically along the spine through their homogeneous
# control points, sections inserted where the error is largest), the cliff-edge
# support (a pipe round the edge's curve) and the offset supports come from
#   BlinkingSun/sldprt2step, files sldprt2step_lib/step/mapper.py (blend_surface,
#   spine_samples, curve_support, _CurveSupport, _OffsetEval, _section_angle,
#   _degenerate_arc, blend_boundary_curve) and sldprt2step_lib/xt/geom.py (arc_nurbs,
#   interpolate_cubic_surface_rows, _col_tangent)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03, 2026-10-04): see solidseas/tessellate/blend.py,
# where the construction now lives so that the tessellator shares it (2026-10-04); this
# file keeps what only the export needs: the surface item written, the approximations
# counted and checked against the export's limits, and the export's reasons.
"""Rolling blends (BLENDED_EDGE) for the STEP export: the approximation of
:mod:`solidseas.tessellate.blend` written as a B-spline surface.

The construction, its measured deviation and how a face's side is found are
described there. The export counts each approximation, refuses one beyond
``max_deviation_m`` (:meth:`.mapper.BodyMapper.note_approximation`) and gives every
refusal as :class:`.mapper.Refused` with the export's reason.
"""

from ..tessellate import blend as core
from ..tessellate.fit import FitFailed
from . import entities as E
from .mapper import FACTS, Refused, SurfaceMap


def refused(exc: FitFailed) -> Refused:
    """The export's refusal for a blend that cannot be approximated."""
    return Refused(exc.reason, exc.detail)


class Blends(core.Blends):
    """The blends of one body (its :class:`.approx.Approximator` ``a``), built on demand,
    each once."""

    def __init__(self, approximator) -> None:
        m = approximator.m
        super().__init__(
            m.topo, m.geom, m.sampler, m._points.p, m.clock, approximator.tol, m.opts.max_deviation_m, FACTS
        )
        self.a, self.m = approximator, m

    def noted(self, cls: str, deviation: float, what: str) -> None:
        try:
            self.m.note_approximation(cls, deviation, what)
        except Refused as exc:
            raise FitFailed(exc.reason, str(exc)) from None

    def fit(self, s, hint=None) -> core.BlendFit:
        """The approximation of blend ``s``, or raises :class:`.mapper.Refused`."""
        try:
            return self.fitted(s, hint)
        except FitFailed as exc:
            raise refused(exc) from None

    def surface(self, s) -> SurfaceMap:
        """The blend's surface item; its faces' orientation comes from
        :meth:`same_sense`, so ``match`` is None."""
        bf = self.fit(s)
        self.m.note_approximation("BLENDED_EDGE", bf.deviation, "rolling blend")
        return SurfaceMap(E.BSplineSurface(bf.spline), None, bf.deviation, "BLENDED_EDGE")

    def same_sense(self, f, snode) -> bool:
        try:
            return super().same_sense(f, snode)
        except FitFailed as exc:
            raise refused(exc) from None
