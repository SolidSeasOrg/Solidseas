"""ACIS SAB files (provisional, ``docs/formats/alibre.md``, ``docs/API.md`` 3.20.8).

:mod:`.sab` tokenizes the binary stream, :mod:`.entities` decodes the B-rep
classes, :mod:`.bspline` the B-splines, and :mod:`.geometry` maps a body to an
in-memory Parasolid transmit that :mod:`solidseas.tessellate` draws. Alibre
Design parts store their bodies this way; a standalone ``.sab`` file of the
verified version (2100) is read the same way. A ``.sat`` text file, and a SAB
file of another version or an ASM one, are refused (``format_not_supported``,
rules ``sat_text`` and ``acis_version``).
"""

from ...errors import FormatNotSupportedError, SldFormatError
from .._source import Clock
from ..base import BodyRef, ModelDocument, ModelNode, SceneBuilder, _stem
from . import sab as sabmod
from .geometry import tessellation_limits

REVISION = 1
_UNIT_TOKENS = {25.4: "in", 10.0: "cm", 1.0: "mm", 1000.0: "m", 304.8: "ft", 0.001: "micron"}


class AcisDocument(ModelDocument):
    """A standalone ACIS SAB file: its bodies, tessellated for the scene."""

    format = "acis"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        head = source.head(4096)
        if self.variant == "sat" or not (
            head.startswith(sabmod.SIGNATURE) or head.startswith(sabmod.ASM_SIGNATURE)
        ):
            raise FormatNotSupportedError(
                "ACIS text files (.sat) are not read yet", detail={"rule": "sat_text", "value": "acis"}
            )
        self.header = sabmod.read_header(head, limits)
        if not self.header.verified:
            raise FormatNotSupportedError(
                "this ACIS file's version is not one whose layout SolidSeas has verified",
                detail={"rule": "acis_version", "value": "acis"},
            )
        self.variant = "sab"
        self.kind = "brep"
        self.doc_type = "part"
        mm = self.header.mm_per_unit
        if not (mm > 0 and mm < float("inf")):
            raise SldFormatError("the ACIS header's unit of length is not a positive number")
        token = next((v for k, v in _UNIT_TOKENS.items() if abs(mm - k) <= 1e-9 * k), None)
        self.units = {"length": token, "scale_m": mm / 1000.0, "source": "file"}
        self._model = None
        self._builds = None

    def model(self, clock: Clock | None = None):
        """The tokenized SAB stream (read once), within ``limits.seconds`` and the
        caller's ``clock`` when one is given, whichever ends first."""
        if self._model is None:
            from .entities import Model

            data = self.source.read_all(self.limits.alibre_stream_bytes, "alibre_stream_bytes")
            c = Clock(self.limits.seconds) if clock is None else clock.child(self.limits.seconds)
            self._model = Model(sabmod.read(data, self.limits, c), self.limits)
        return self._model

    def builds(self, clock: Clock):
        if self._builds is None:
            from .entities import AcisError
            from .geometry import bodies, build_body

            m = self.model(clock)
            out = []
            stem = _stem(self.name) or "body"
            found = bodies(m)
            for k, b in enumerate(found):
                label = stem if len(found) == 1 else f"{stem}#{k + 1}"
                try:
                    out.append(build_body(m, b, self.limits, clock, label=label))
                except AcisError as exc:
                    self.warn("bodies_left_out", f"an ACIS body could not be mapped: {exc}"[:300])
            self._builds = out
        return self._builds

    def _counts(self):
        return {"bodies": self.header.entities if self.header.entities > 0 else None}

    def _tree(self, clock: Clock):
        builds = self.builds(clock)
        stem = _stem(self.name)
        if len(builds) <= 1:
            return [ModelNode("1", None, stem, "object", 0)]
        nodes = [ModelNode("1", None, stem, "assembly")]
        nodes += [ModelNode(str(k + 2), "1", b.label, "body", k, color=b.color) for k, b in enumerate(builds)]
        return nodes

    def _bodies(self, clock: Clock):
        return [
            BodyRef(
                b.label, b.transmit, b.color, "1" if len(self.builds(clock)) == 1 else str(k + 2), b.body_type
            )
            for k, b in enumerate(self.builds(clock))
        ]

    def _scene(self, sb: SceneBuilder) -> None:
        from ...tessellate import tessellate_transmit

        builds = self.builds(sb.clock)
        cap = sb.options.max_triangles
        for k, b in enumerate(builds):
            node = "1" if len(builds) == 1 else str(k + 2)
            left = sb.clock.left()
            tess = tessellate_transmit(
                b.transmit,
                max_seconds=max(0.0, left) if left is not None else sb.options.max_seconds,
                max_triangles=self.limits.triangles if cap is None else min(self.limits.triangles, cap + 1),
                **sb.options.tessellation(),
            )
            sb.skipped.extend(b.skipped)
            sb.skipped.extend(tess.skipped)
            sb.warnings.extend(w for w in b.warnings if w.code != "faces_left_out")
            sb.counts["bodies"] = (sb.counts.get("bodies") or 0) + 1
            sb.counts["faces"] = (sb.counts.get("faces") or 0) + b.faces
            sb.counts["faces_done"] = (sb.counts.get("faces_done") or 0) + tess.counts.get("faces_done", 0)
            tessellation_limits(sb, tess, self.limits)
            positions, triangles = tess.welded()
            if not triangles:
                continue
            mb = sb.mesh(name=b.label, source="bodies", scale_m=1.0, color=b.color, node=node)
            mb.add_vertices(positions)
            mb.add_triangles(triangles)
            sb.add_item(mb.finish(), node)


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> AcisDocument:
    """Open an ACIS file's :class:`~solidseas.formats._source.Source` (the registry's
    reader for ``acis``)."""
    return AcisDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "AcisDocument", "open"]
