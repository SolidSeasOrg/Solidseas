"""Every bound of a drawing in one place: ``DrawingLimits`` (``docs/DRAWINGS.md`` 17.1).

A stage reads its bounds from here and nowhere else, so a hostile or huge part meets
the same limits in the viewer, the command line and a test. The defaults are the
design's; a caller may lower any of them (tests do), never raise one past its
ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from ..errors import DrawingTooComplexError, InvalidArgumentError

# (default, ceiling) of each bound; seconds are per stage, ``seconds_total`` the whole run.
_BOUNDS: dict[str, tuple[float, float]] = {
    "bodies": (64, 1024),
    "instances": (1000, 10_000),
    "faces": (50_000, 200_000),
    "edges": (150_000, 600_000),
    "triangles": (400_000, 5_000_000),
    "child_memory_mb": (3072, 65_536),
    "visibility_queries": (2_000_000, 20_000_000),
    "seconds_source": (30.0, 600.0),
    "seconds_tessellation": (30.0, 600.0),
    "seconds_features": (20.0, 600.0),
    "seconds_views": (90.0, 1800.0),
    "seconds_plan": (20.0, 600.0),
    "seconds_layout": (20.0, 600.0),
    "seconds_total": (150.0, 3600.0),
    "extent_min_m": (1e-6, 1e-6),
    "extent_max_m": (100.0, 100.0),
    "requirements": (5000, 50_000),
    "dimensions": (2000, 20_000),
    "views": (12, 24),
    "sheets": (16, 64),
    "title_chars": (256, 256),
    "note_chars": (2000, 2000),
    "string_chars": (4096, 4096),
    "settings_bytes": (256 * 1024, 256 * 1024),
    "drawing_bytes": (16 * 1024 * 1024, 16 * 1024 * 1024),
    "sheet_bytes": (12 * 1024 * 1024, 12 * 1024 * 1024),
    "unknown_bytes": (1024 * 1024, 1024 * 1024),
    "logo_bytes": (512 * 1024, 512 * 1024),
    "logo_pixels": (1200, 1200),
    "output_bytes": (64 * 1024 * 1024, 64 * 1024 * 1024),
    "json_depth": (32, 32),
}


@dataclass(frozen=True)
class DrawingLimits:
    """The bounds of one drawing run (DRAWINGS.md 17.1). Every field is checked when it
    is made: a number, more than nought (the extent's minimum excepted) and no more
    than its ceiling."""

    bodies: int = 64
    instances: int = 1000  # an assembly's part instances drawn; its bodies count once a part
    faces: int = 50_000
    edges: int = 150_000
    triangles: int = 400_000
    child_memory_mb: int = 3072
    visibility_queries: int = 2_000_000
    seconds_source: float = 30.0
    seconds_tessellation: float = 30.0
    seconds_features: float = 20.0
    seconds_views: float = 90.0
    seconds_plan: float = 20.0
    seconds_layout: float = 20.0
    seconds_total: float = 150.0
    extent_min_m: float = 1e-6
    extent_max_m: float = 100.0
    requirements: int = 5000
    dimensions: int = 2000
    views: int = 12
    sheets: int = 16  # a drawing's sheets: the first, and those a long parts list goes on to
    title_chars: int = 256
    note_chars: int = 2000
    string_chars: int = 4096
    settings_bytes: int = 256 * 1024
    drawing_bytes: int = 16 * 1024 * 1024
    sheet_bytes: int = 12 * 1024 * 1024
    unknown_bytes: int = 1024 * 1024
    logo_bytes: int = 512 * 1024
    logo_pixels: int = 1200
    output_bytes: int = 64 * 1024 * 1024
    json_depth: int = 32

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            _default, ceiling = _BOUNDS[f.name]
            whole = f.type in ("int", int)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (whole and not isinstance(value, int))
            ):
                raise InvalidArgumentError(f"{f.name} must be a number", detail={"parameter": f.name})
            if not 0 < value <= ceiling:
                raise InvalidArgumentError(
                    f"{f.name} must be more than 0 and at most {ceiling:g}", detail={"parameter": f.name}
                )

    def exceeded(self, name: str, what: str) -> DrawingTooComplexError:
        """The error for bound ``name`` passed, said as ``what``: code ``drawing_too_complex``,
        an ``SldLimitError`` still."""
        return DrawingTooComplexError(what, detail={"limit": name, "value": getattr(self, name)})

    def refuse(self, *, bodies: int = 0, faces: int = 0, edges: int = 0) -> str | None:
        """Why a part this size is refused before any work starts (17.1), or None. The
        wizard says it on its first page; the library raises ``drawing_too_complex``."""
        for name, n in (("bodies", bodies), ("faces", faces), ("edges", edges)):
            bound = getattr(self, name)
            if n > bound:
                return f"the part has {n:,} {name}, more than the {bound:,} a drawing takes"
        return None


DEFAULT_LIMITS = DrawingLimits()

__all__ = ["DEFAULT_LIMITS", "DrawingLimits"]
