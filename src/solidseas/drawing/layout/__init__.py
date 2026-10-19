"""Layout (``docs/DRAWINGS.md`` 11): sheet and scale, the arrangement of the views
with their bands, placement without collisions, the title block, notes and
stamps, and the layout checks. :func:`layout` is the entry point."""

from .checks import LayoutCheck
from .place import LayoutResult, layout

__all__ = ["LayoutCheck", "LayoutResult", "layout"]
