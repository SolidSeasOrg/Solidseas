"""Automatic drawings from 3D parts (``docs/DRAWINGS.md``). Provisional until the
first release; ``docs/API.md`` documents what is here.

:func:`make_drawing` runs the stages of :mod:`.pipeline` on a part: its source, the
B-rep model, feature recognition, the views, the plan and its layout, and the
drawing itself, which comes back with the checks of 20.1 and the run kept beside
it for editing. :func:`save` and :func:`load` write and read the ``.ssdrw``;
:func:`write_pdf` and :func:`write_dxf` export its sheet; :func:`regenerate` updates
it from its model, keeping the user's edits; :mod:`.edit` holds every edit of
10.12 (each returning the new drawing and its checks) and :mod:`.checks` the
checklist. A stage this SolidSeas lacks raises ``not_implemented`` with rule
``stage_missing``.
"""

from __future__ import annotations

import importlib
from typing import Any

from .limits import DEFAULT_LIMITS, DrawingLimits
from .pipeline import ENTRY_POINTS, make_drawing, resolve
from .settings import DrawingSettings, default_settings, load_settings, save_settings
from .types import Drawing, DrawingOptions

_LAZY = ("checks", "edit")  # modules loaded when first used, so importing drawing stays light


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def load(path, **kw) -> Any:
    """Read a ``.ssdrw`` (``dwg-file``)."""
    return resolve("load", ENTRY_POINTS["load"])(path, **kw)


def save(drawing, path, **kw) -> Any:
    """Write a ``.ssdrw`` (``dwg-file``); ``replaces`` as section 12.6 says."""
    return resolve("save", ENTRY_POINTS["save"])(drawing, path, **kw)


def regenerate(drawing, source=None, **kw) -> Any:
    """Update a drawing from its model, keeping the user's edits (13.5)."""
    return resolve("regenerate", ENTRY_POINTS["regenerate"])(drawing, source, **kw)


def write_pdf(drawing, fh, **kw) -> Any:
    """Write the drawing's sheet as PDF (``dwg-pdf``)."""
    return resolve("write_pdf", ENTRY_POINTS["write_pdf"])(drawing, fh, **kw)


def write_dxf(drawing, fh, **kw) -> Any:
    """Write the drawing's sheet as DXF (``dwg-dxf``)."""
    return resolve("write_dxf", ENTRY_POINTS["write_dxf"])(drawing, fh, **kw)


__all__ = [
    "DEFAULT_LIMITS",
    "Drawing",
    "DrawingLimits",
    "DrawingOptions",
    "DrawingSettings",
    "checks",
    "default_settings",
    "edit",
    "load",
    "load_settings",
    "make_drawing",
    "regenerate",
    "save",
    "save_settings",
    "write_dxf",
    "write_pdf",
]
