"""Colours of a STEP file (provisional).

ISO 10303-46 as AP214 and AP242 use it: a ``STYLED_ITEM`` (or an
``OVER_RIDING_STYLED_ITEM``, which wins over it) gives an item (a solid, a shell, a
face, a surface model) a list of ``PRESENTATION_STYLE_ASSIGNMENT``s. A surface's
colour is reached through ``SURFACE_STYLE_USAGE``, ``SURFACE_SIDE_STYLE`` and either
``SURFACE_STYLE_FILL_AREA``, ``FILL_AREA_STYLE`` and ``FILL_AREA_STYLE_COLOUR`` or
``SURFACE_STYLE_RENDERING`` (with properties, whose ``SURFACE_STYLE_TRANSPARENT``
sets the alpha), down to a ``COLOUR_RGB`` (red, green and blue from 0 to 1) or a
``DRAUGHTING_PRE_DEFINED_COLOUR`` (a named colour). Curve styles colour edges and
are not read. Styles that depend on an assembly context are not read.
"""

from typing import Any

from .part21 import Part21, Record, Ref, Typed

RGBA = tuple[float, float, float, float]
PREDEFINED = {
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "magenta": (1.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
}
MAX_STYLE_DEPTH = 12
_NOT_FOLLOWED = frozenset(
    {"CURVE_STYLE", "POINT_STYLE", "TEXT_STYLE", "STYLED_ITEM", "OVER_RIDING_STYLED_ITEM"}
)


def _unit_float(v: Any) -> float | None:
    if isinstance(v, Typed):
        v = v.value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    if v != v:  # NaN
        return None
    return min(1.0, max(0.0, v))


class Colours:
    """The colour each styled item is given (see the module notes)."""

    def __init__(self, p21: Part21, limits: Any, clock: Any = None) -> None:
        self.p = p21
        self.by_item: dict[int, RGBA] = {}
        self.styled = 0
        self._styles: dict[int, RGBA | None] = {}
        ids = sorted(set(p21.ids_of_type("STYLED_ITEM")) | set(p21.ids_of_type("OVER_RIDING_STYLED_ITEM")))
        if len(ids) > limits.step_styled_items:
            raise limits.exceeded(
                "step_styled_items", f"the file styles more than {limits.step_styled_items:,} items"
            )
        overriding: dict[int, RGBA] = {}
        for i in ids:
            if clock is not None:
                clock.tick()
            r = p21.record(i)
            prm = r.params if not r.complex else (r.part("STYLED_ITEM") or [])
            if r.complex:  # a complex instance keeps the name in REPRESENTATION_ITEM
                styles, item = (prm[0], prm[1]) if len(prm) >= 2 else (None, None)
            else:
                styles, item = (prm[1], prm[2]) if len(prm) >= 3 else (None, None)
            if not isinstance(item, Ref) or not isinstance(styles, list):
                continue
            self.styled += 1
            colour = None
            for s in styles:
                colour = self.style(s)
                if colour is not None:
                    break
            if colour is None:
                continue
            if r.has("OVER_RIDING_STYLED_ITEM"):
                overriding[int(item)] = colour
            else:
                self.by_item.setdefault(int(item), colour)
        self.by_item.update(overriding)

    def get(self, rid: int) -> RGBA | None:
        return self.by_item.get(rid)

    def style(self, ref: Any) -> RGBA | None:
        """The surface colour of a presentation style assignment, cached."""
        if not isinstance(ref, Ref):
            return None
        rid = int(ref)
        if rid in self._styles:
            return self._styles[rid]
        self._styles[rid] = None
        got = self._walk(ref, 0, None)
        self._styles[rid] = got
        return got

    def _walk(self, ref: Any, depth: int, alpha: float | None) -> RGBA | None:
        if depth > MAX_STYLE_DEPTH:
            return None
        r = self.p.get(ref)
        if r is None:
            return None
        t = r.types
        if "COLOUR_RGB" in t:
            prm = r.part("COLOUR_RGB") or []
            vals = [_unit_float(v) for v in prm[-3:]] if len(prm) >= 3 else []
            if len(vals) == 3 and all(v is not None for v in vals):
                return (vals[0], vals[1], vals[2], 1.0 if alpha is None else alpha)
            return None
        if "DRAUGHTING_PRE_DEFINED_COLOUR" in t or "PRE_DEFINED_COLOUR" in t:
            prm = r.params
            name = prm[0].lower() if prm and isinstance(prm[0], str) else ""
            rgb = PREDEFINED.get(name)
            return None if rgb is None else (*rgb, 1.0 if alpha is None else alpha)
        prm = _flat(r)
        if "SURFACE_SIDE_STYLE" in t and alpha is None:
            # a rendering's transparency sets the alpha of the side's colour, whichever
            # style of the side holds the colour
            for v in prm:
                for x in v if isinstance(v, list) else [v]:
                    xr = self.p.get(x)
                    if xr is not None and xr.has("SURFACE_STYLE_RENDERING_WITH_PROPERTIES"):
                        alpha = self._transparency(xr)
                        if alpha is not None:
                            break
        if "SURFACE_STYLE_RENDERING_WITH_PROPERTIES" in t and alpha is None:
            alpha = self._transparency(r)
        if "CURVE_STYLE" in t or "POINT_STYLE" in t or "TEXT_STYLE" in t:
            return None
        if "PRESENTATION_STYLE_BY_CONTEXT" in t:
            prm = prm[:1]  # its styles; the context is not followed
        for v in prm:
            for x in v if isinstance(v, list) else [v]:
                if isinstance(x, Ref) and self._is_style(x):
                    got = self._walk(x, depth + 1, alpha)
                    if got is not None:
                        return got
        return None

    def _transparency(self, r: Record) -> float | None:
        """The alpha (one less the transparency) a rendering's properties give, or None."""
        for p in _flat(r):
            for q in p if isinstance(p, list) else []:
                qr = self.p.get(q)
                if qr is not None and qr.has("SURFACE_STYLE_TRANSPARENT"):
                    tr = _unit_float((qr.params or [None])[0])
                    if tr is not None:
                        return 1.0 - tr
        return None

    def _is_style(self, ref: Ref) -> bool:
        t = self.p.type_of(int(ref)) or ()
        return any(("STYLE" in n or "COLOUR" in n) and n not in _NOT_FOLLOWED for n in t)


def _flat(r: Record) -> list:
    out: list = []
    for p in r.parts:
        out.extend(p)
    return out


__all__ = ["PREDEFINED", "Colours"]
