"""What a STEP file says about itself: header fields, the writing program, product names
and user-defined properties (provisional).

* The header (ISO 10303-21 clause 8): ``FILE_NAME``'s time stamp is
  ``fields.last_saved_utc`` (a time stamp without a zone stays as stored, naive), its
  authors ``fields.author`` and its originating system the ``application``; the
  stored file name, description, implementation level, organisations,
  preprocessor version, originating system and authorisation are properties.
* The root product's id, name and description are the properties
  ``product_id``, ``product_name`` and ``product_description``, and its name is
  ``fields.title``.
* User-defined properties, as the CAx Implementor Forum's recommended practice
  writes them: a ``PROPERTY_DEFINITION`` of the root product definition (or of its
  shape) with a ``PROPERTY_DEFINITION_REPRESENTATION`` whose representation holds
  ``DESCRIPTIVE_REPRESENTATION_ITEM``s (text), ``MEASURE_REPRESENTATION_ITEM``s or
  ``VALUE_REPRESENTATION_ITEM``s (numbers, text or logicals). A property is named
  by its item, or by its property definition when the item has no name.

Every value is cut to ``text_bytes`` (``text_truncated``) and there are at most
``properties`` of them.
"""

import datetime
import re
from typing import Any

from ...errors import ReaderWarning
from .._source import clip_text
from ..base import make_property
from ..solidworks.document import SummaryFields
from ..solidworks.metadata import Property
from .part21 import Enum, Header, Part21, Ref, Typed, as_bool

_STAMP = re.compile(
    r"\s*(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?"
    r"\s*(Z|[+-]\d{2}(?::?\d{2})?)?\s*\Z"
)


def time_stamp(text: str | None) -> datetime.datetime | None:
    """An ISO 8601 time stamp as a datetime, or None: aware UTC when it carries a zone,
    else naive, as stored (local time where it was written, zone unknown)."""
    if not text:
        return None
    m = _STAMP.match(text)
    if m is None:
        return None
    y, mo, d, h, mi, s, frac, zone = m.groups()
    try:
        micro = int((frac or "0")[:6].ljust(6, "0"))
        when = datetime.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0), micro)
    except ValueError:
        return None
    if not zone:
        return when
    offset = datetime.timedelta(0)
    if zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        try:
            offset = sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
        except ValueError:
            return None
    try:
        return (when - offset).replace(tzinfo=datetime.UTC)
    except OverflowError:
        return None


def _join(values: tuple[str, ...]) -> str | None:
    kept = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    return "; ".join(kept) or None


def _blank(v: str | None) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def head(header: Header, limits: Any, warnings: list) -> tuple[SummaryFields, list[Property], dict]:
    """``(fields, properties, application)`` from the header section."""
    clip = _clipper(limits, warnings)
    author = _join(header.author)
    fields = SummaryFields(
        author=clip(author) if author else None,
        last_saved_utc=time_stamp(header.time_stamp),
    )
    props: list[Property] = []

    def add(name: str, value: str | None) -> None:
        if value:
            props.append(make_property(name, clip(value)))

    add("file_name", _blank(header.name))
    add("time_stamp", _blank(header.time_stamp))
    add("description", _join(header.description))
    add("implementation_level", _blank(header.implementation_level))
    add("organization", _join(header.organization))
    add("preprocessor_version", _blank(header.preprocessor_version))
    add("originating_system", _blank(header.originating_system))
    add("authorization", _blank(header.authorization))
    add("schema", ", ".join(header.schemas) or None)
    system = _blank(header.originating_system)
    application = {"name": clip(system) if system else None, "version": None}
    return fields, props, application


def _clipper(limits: Any, warnings: list):
    def clip(text: str) -> str:
        got: list[ReaderWarning] = []
        out = clip_text(text, limits, got, "a header or property value")
        if got and not any(w.code == "text_truncated" for w in warnings):
            warnings.extend(got)
        return out

    return clip


def product(pd: Any, limits: Any, warnings: list) -> list[Property]:
    """The root product's id, name and description as properties."""
    clip = _clipper(limits, warnings)
    out = []
    for name, value in (
        ("product_id", pd.id_text),
        ("product_name", pd.name),
        ("product_description", pd.description),
    ):
        if isinstance(value, str) and value.strip():
            out.append(make_property(name, clip(value.strip())))
    return out


def _value(v: Any) -> Any:
    if isinstance(v, Typed):
        v = v.value
    if isinstance(v, Enum):
        b = as_bool(v)
        return b if b is not None else str(v)
    if isinstance(v, bool) or isinstance(v, (int, float, str)):
        return v
    return None


def user_defined(
    p21: Part21, owners: set[int], limits: Any, warnings: list, clock: Any = None
) -> list[Property]:
    """User-defined properties of the instances in ``owners`` (the root product definition
    and its shapes)."""
    clip = _clipper(limits, warnings)
    reps: dict[int, list[int]] = {}
    for i in p21.ids_of_type("PROPERTY_DEFINITION_REPRESENTATION"):
        if clock is not None:
            clock.tick()
        r = p21.record(i)
        prm = r.params
        if len(prm) >= 2 and isinstance(prm[0], Ref) and isinstance(prm[1], Ref):
            reps.setdefault(int(prm[0]), []).append(int(prm[1]))
    out: list[Property] = []
    for i in p21.ids_of_type("PROPERTY_DEFINITION"):
        r = p21.record(i)
        if r.complex:
            continue
        prm = r.params
        if len(prm) < 3 or not isinstance(prm[2], Ref) or int(prm[2]) not in owners:
            continue
        pname = _blank(prm[0] if isinstance(prm[0], str) else None)
        for rep in reps.get(i, []):
            rr = p21.get(Ref(rep))
            if rr is None or len(rr.params) < 2 or not isinstance(rr.params[1], list):
                continue
            for it in rr.params[1]:
                ir = p21.get(it)
                if ir is None or ir.complex:
                    continue
                ip = ir.params
                name = _blank(ip[0] if ip and isinstance(ip[0], str) else None) or pname
                if not name:
                    continue
                if ir.has("DESCRIPTIVE_REPRESENTATION_ITEM"):
                    value = ip[1] if len(ip) >= 2 and isinstance(ip[1], str) else None
                elif ir.has("MEASURE_REPRESENTATION_ITEM") or ir.has("VALUE_REPRESENTATION_ITEM"):
                    value = _value(ip[1]) if len(ip) >= 2 else None
                else:
                    continue
                if value is None:
                    continue
                if isinstance(value, str):
                    value = clip(value)
                out.append(make_property(clip(name), value))
                if len(out) > limits.properties:
                    raise limits.exceeded(
                        "properties", f"the file has more than {limits.properties:,} properties"
                    )
    return out


__all__ = ["head", "product", "time_stamp", "user_defined"]
