"""Strict parsing of a request's query string, one allowlist per route.

Following the ``request-schema-allowlist`` and ``falsy-zero-defaults``
skills: a parameter a route does not name is refused by name
(``unknown_parameter``), never dropped; a repeated one is refused
(``duplicate_parameter``); an empty value is refused, never read as absence;
and every value is checked against its type:

* integers: ASCII digits only, no sign, no leading zero, within the route's range;
* booleans: ``0``, ``1``, ``true`` or ``false``;
* enumerations: exact and case-sensitive;
* ``include``: a comma-separated subset of the route's allowlist, no repeats;
* ``configuration`` and ``nested``: bounded text with no control characters;
* ``root``: an id as roots are named (``[a-z0-9_-]{1,32}``);
* ``client``: a token's name, the same syntax; ``nonce``: 32 to 128 URL-safe
  characters (``/v1/identity``);
* ``path``: checked as text by :mod:`.paths`, never joined to anything here.

The query is decoded once, as strict UTF-8 (``%C0%AE`` and other invalid
sequences are refused), and an unpaired ``%`` is refused rather than kept as
text. A token in the query (``token=``, ``access_token=``) is just an unknown
parameter: credentials travel only in the ``Authorization`` header.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

from ..errors import InvalidArgumentError, SolidSeasError
from ..roots import ROOT_ID
from .tokens import NONCE_TEXT, TOKEN_NAME

MAX_FIELDS = 12
MAX_TEXT = 256
MAX_NESTED = 512
MAX_CURSOR = 4096
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DIGITS = re.compile(r"[1-9][0-9]{0,8}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ServiceError(SolidSeasError):
    """A request the service refuses before any document is read. ``code`` is set per
    instance (``unknown_parameter``, ``forbidden_host``, ``busy``...)."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message, detail=detail)
        self.code = code


@dataclass(frozen=True)
class Param:
    """One query parameter a route accepts."""

    kind: str  # root, path, text, nested, enum, bool, int, include, cursor, client, nonce
    required: bool = False
    choices: tuple[str, ...] = ()
    low: int = 1
    high: int = 1
    default: Any = None
    max_len: int = MAX_TEXT
    extra: dict[str, Any] = field(default_factory=dict)


def _bad(name: str, why: str) -> InvalidArgumentError:
    return InvalidArgumentError(f"parameter {name}: {why}", detail={"parameter": name})


def _convert(name: str, spec: Param, value: str) -> Any:
    kind = spec.kind
    if kind == "root":
        if not ROOT_ID.match(value):
            raise _bad(name, "a root id matches [a-z0-9_-]{1,32}")
        return value
    if kind == "client":
        if not TOKEN_NAME.match(value):
            raise _bad(name, "a token's name matches [a-z0-9_-]{1,32}")
        return value
    if kind == "nonce":
        if not NONCE_TEXT.match(value):
            raise _bad(name, "32 to 128 characters from A-Z, a-z, 0-9, _ and -")
        return value
    if kind in ("path", "text", "nested", "cursor"):
        limit = {"path": 4096, "nested": MAX_NESTED, "cursor": MAX_CURSOR}.get(kind, spec.max_len)
        if len(value) > limit:
            raise _bad(name, f"longer than {limit} characters")
        if kind != "path" and _CONTROL.search(value):
            raise _bad(name, "control characters are not accepted")
        return value
    if kind == "enum":
        if value not in spec.choices:
            raise _bad(name, f"one of {', '.join(spec.choices)}")
        return value
    if kind == "bool":
        if value in ("1", "true"):
            return True
        if value in ("0", "false"):
            return False
        raise _bad(name, "0, 1, true or false")
    if kind == "int":
        if not value.isascii() or not _DIGITS.match(value):
            raise _bad(name, "a whole number written with digits only")
        n = int(value)
        if not spec.low <= n <= spec.high:
            raise _bad(name, f"from {spec.low} to {spec.high}")
        return n
    if kind == "include":
        members = value.split(",")
        if any(m not in spec.choices for m in members):
            raise _bad(name, f"a comma-separated list of {', '.join(spec.choices)}")
        if len(set(members)) != len(members):
            raise _bad(name, "a member appears twice")
        return tuple(members)
    raise ValueError(f"unknown parameter kind {kind!r}")  # a bug in the route table


def parse_query(raw: str, allowed: Mapping[str, Param]) -> tuple[dict[str, Any], tuple[tuple[str, str], ...]]:
    """The route's parameters from the raw query string, converted, with defaults for the
    absent ones; and the canonical form (sorted name and raw value pairs) for ETags
    and cursors. Raises :class:`ServiceError` (``unknown_parameter``,
    ``duplicate_parameter``) or :class:`~solidseas.errors.InvalidArgumentError`."""
    if _BAD_ESCAPE.search(raw) or "#" in raw:
        raise _bad("query", "a % must start a two-digit escape")
    try:
        pairs = parse_qsl(
            raw,
            keep_blank_values=True,
            strict_parsing=bool(raw),
            max_num_fields=MAX_FIELDS,
            encoding="utf-8",
            errors="strict",
        )
    except ValueError:  # a malformed field, too many fields, or bytes that are not UTF-8
        raise _bad("query", "not a valid query string") from None
    given: dict[str, str] = {}
    for name, value in pairs:
        if name not in allowed:
            raise ServiceError(
                "unknown_parameter",
                "the route does not accept a parameter by that name",
                detail={"parameter": name[:64]},
            )
        if name in given:
            raise ServiceError("duplicate_parameter", "a parameter appears twice", detail={"parameter": name})
        if value == "":
            raise _bad(name, "an empty value is not accepted; leave the parameter out instead")
        given[name] = value
    out: dict[str, Any] = {}
    for name, spec in allowed.items():
        if name in given:
            out[name] = _convert(name, spec, given[name])
        elif spec.required:
            raise _bad(name, "required")
        else:
            out[name] = spec.default
    return out, tuple(sorted(given.items()))


def requested_location(raw: str, *, nested: bool = False) -> dict[str, Any] | None:
    """``{"root", "path"}`` (and ``nested``) as a request names them, for the ``source`` of an
    error raised before its query passed :func:`parse_query`: each value given once, as
    UTF-8, within its parameter's limits, else null; ``nested`` only for a route that takes
    it. None when neither root nor path is readable."""
    try:
        pairs = parse_qsl(
            raw, keep_blank_values=True, max_num_fields=MAX_FIELDS, encoding="utf-8", errors="strict"
        )
    except ValueError:
        return None
    seen: dict[str, list[str]] = {}
    for name, value in pairs:
        seen.setdefault(name, []).append(value)

    def once(name: str, ok) -> str | None:
        values = seen.get(name)
        return values[0] if values and len(values) == 1 and values[0] and ok(values[0]) else None

    root = once("root", lambda v: ROOT_ID.match(v) is not None)
    path = once("path", lambda v: len(v) <= 4096)
    nested_value = None
    if nested:
        nested_value = once("nested", lambda v: len(v) <= MAX_NESTED and not _CONTROL.search(v))
    if root is None and path is None:
        return None
    out: dict[str, Any] = {"root": root, "path": path}
    if nested_value is not None:
        out["nested"] = nested_value
    return out


__all__ = ["MAX_FIELDS", "Param", "ServiceError", "parse_query", "requested_location"]
