"""Recordings of CadQuery models written without CadQuery, for the tests of
``solidseas.nativewrite.cqrecording``.

A :class:`Chain` writes the steps the recorder would write for calls made in CadQuery's own
chained style: ``c = Chain(); m = c.wp("XY").rect(40, 30).extrude(10)`` and
``c.recording(m)`` is the recording's JSON form. ``end`` returns the workplane it goes back
to and ``tag`` its own, as CadQuery's do; every other call returns a new workplane, unless it
is named in ``queries`` (then it returns something else, as ``val`` does).
"""

from __future__ import annotations

import copy
from typing import Any

FORMAT = "solidseas-cadquery-recording/1"


class Chain:
    def __init__(self, queries: tuple[str, ...] = ("val", "vals", "size", "largestDimension")) -> None:
        self.steps: list[dict] = []
        self.parents: dict[int, int | None] = {}
        self.count = 0
        self.queries = queries

    def _new(self, parent: int | None) -> int:
        n = self.count
        self.count += 1
        self.parents[n] = parent
        return n

    def _note(self, name: str, on: int | None, args: tuple, kwargs: dict, result: int | None) -> None:
        self.steps.append(
            {"call": name, "on": on, "args": _data(list(args)), "kwargs": _data(kwargs), "result": result}
        )

    def wp(self, *args: Any, **kwargs: Any) -> Link:
        n = self._new(None)
        self._note("Workplane", None, args, kwargs, n)
        return Link(self, n)

    def call(self, on: int, name: str, args: tuple, kwargs: dict) -> Any:
        if name in self.queries:
            result = None
        elif name == "tag":
            result = on
        elif name == "end":
            result = on
            for _ in range(args[0] if args else kwargs.get("n", 1)):
                result = self.parents[result]
        else:
            result = self._new(on)
        self._note(name, on, args, kwargs, result)
        return None if result is None else Link(self, result)

    def recording(self, model: Link, *, name: str = "part", units: str = "mm", **extra: Any) -> dict:
        """The recording's JSON form, a copy a test may change."""
        steps = copy.deepcopy(self.steps)
        return {"format": FORMAT, "name": name, "units": units, "model": model.n, "steps": steps, **extra}


class Link:
    """A workplane of a :class:`Chain`: any attribute is a CadQuery call on it."""

    def __init__(self, chain: Chain, n: int) -> None:
        self.chain, self.n = chain, n

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self.chain.call(self.n, name, args, kwargs)

    def __sub__(self, other: Link) -> Link:
        return self.chain.call(self.n, "__sub__", (other,), {})


def _data(v: Any) -> Any:
    if isinstance(v, Link):
        return {"workplane": v.n}
    if isinstance(v, (list, tuple)):
        return [_data(x) for x in v]
    if isinstance(v, dict):
        return {k: _data(x) for k, x in v.items()}
    return v
