"""A small JSON Schema (2020-12) validator for the subset ``solidseas.model`` uses.

It exists so the tests can check every builder against its published schema
without a third-party dependency. It supports ``type``, ``properties``,
``required``, ``additionalProperties``, ``items``, ``enum``, ``const``,
``pattern``, ``minimum``, ``maximum``, ``anyOf`` and local ``$ref`` into
``$defs``, and refuses any other keyword so a schema can never pass because a
keyword was silently ignored.

``strict=True`` also treats a property an object schema does not declare as an
error. The published schemas leave objects open, as the stability policy says
consumers must ignore unknown fields; the tests validate strictly so a builder
cannot add a field that the schema (and ``docs/API.md``) does not know about.
"""

import re
from typing import Any

SUPPORTED = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "pattern",
        "minimum",
        "maximum",
        "anyOf",
    }
)


def _is_type(v: Any, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    raise ValueError(f"unknown JSON Schema type {t!r}")


def _same(a: Any, b: Any) -> bool:
    """JSON equality: ``True`` is not ``1``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/$defs/"):
        raise ValueError(f"only local #/$defs/ references are supported, not {ref!r}")
    name = ref[len("#/$defs/") :]
    try:
        return root["$defs"][name]
    except KeyError:
        raise ValueError(f"unresolved reference {ref!r}") from None


def _check(v: Any, s: dict, root: dict, path: str, strict: bool, errors: list[str]) -> None:
    unknown = set(s) - SUPPORTED
    if unknown:
        raise ValueError(f"{path}: unsupported schema keywords {sorted(unknown)}")
    if "$ref" in s:
        _check(v, _resolve(s["$ref"], root), root, path, strict, errors)
    if "anyOf" in s:
        if not any(not _errors(v, sub, root, path, strict) for sub in s["anyOf"]):
            errors.append(f"{path}: matches none of anyOf")
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is_type(v, t) for t in types):
            errors.append(f"{path}: {type(v).__name__} is not {'/'.join(types)}")
            return
    if "enum" in s and not any(_same(v, e) for e in s["enum"]):
        errors.append(f"{path}: {v!r} is not one of {s['enum']}")
    if "const" in s and not _same(v, s["const"]):
        errors.append(f"{path}: {v!r} is not {s['const']!r}")
    if isinstance(v, str) and "pattern" in s and not re.search(s["pattern"], v):
        errors.append(f"{path}: {v!r} does not match {s['pattern']!r}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errors.append(f"{path}: {v} is below {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errors.append(f"{path}: {v} is above {s['maximum']}")
    if isinstance(v, dict):
        props = s.get("properties", {})
        for key in s.get("required", []):
            if key not in v:
                errors.append(f"{path}: missing required {key!r}")
        extra = s.get("additionalProperties", None if strict and "properties" in s else True)
        for key, item in v.items():
            if key in props:
                _check(item, props[key], root, f"{path}.{key}", strict, errors)
            elif extra is None or extra is False:
                errors.append(f"{path}: undeclared property {key!r}")
            elif isinstance(extra, dict):
                _check(item, extra, root, f"{path}.{key}", strict, errors)
    if isinstance(v, list) and "items" in s:
        for i, item in enumerate(v):
            _check(item, s["items"], root, f"{path}[{i}]", strict, errors)


def _errors(v: Any, s: dict, root: dict, path: str, strict: bool) -> list[str]:
    out: list[str] = []
    _check(v, s, root, path, strict, out)
    return out


def validate(instance: Any, schema: dict, *, strict: bool = False) -> list[str]:
    """Every way ``instance`` breaks ``schema``; an empty list when it conforms."""
    return _errors(instance, schema, schema, "$", strict)
