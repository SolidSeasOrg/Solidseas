"""Record a CadQuery model while it is built, as :mod:`.cqrecording` reads it.

Run the model's code in a :class:`Recorder`::

    import cadquery as cq
    from solidseas.nativewrite import cqrecorder, cqrecording, generate

    with cqrecorder.Recorder() as rec:
        plate = (
            cq.Workplane("XY").rect(40, 30, centered=False).extrude(10)
            .faces(">Z").workplane(centerOption="CenterOfMass").hole(8)
        )
    recording = rec.recording(plate, name="plate", properties={"PartNo": "SS-1001"})
    rec.save("plate.json", plate, name="plate")  # for solidseas sldprt plate.json
    part = generate.write_part(cqrecording.to_ir(recording))

While it is open, every call made on CadQuery's ``Workplane`` from outside CadQuery is
written down: its name, its arguments as data, the workplane it was called on and the one it
returned. Calls CadQuery makes inside its own methods are not, so each step is one line of
the model's code. Numbers, text, lists, ``Vector`` and ``Plane`` values are kept as they are,
a workplane as its number, and any other value by its type's name only.

This is the one module of SolidSeas that uses CadQuery, and only when a recorder opens
without a class given; CadQuery is an optional extra (``pip install solidseas[cad]``) and the
rest of the library never imports it. Record one model at a time: while a recorder is open
it changes ``Workplane`` for the whole process, and closing it puts everything back.
"""

from __future__ import annotations

import datetime
import functools
import inspect
import math
import numbers
import os
import sys
import threading
from pathlib import Path
from typing import Any

from . import cqrecording

# Recorded as calls too: the constructor, and CadQuery's operators (a - b is a cut, and so on).
OPERATORS = ("__init__", "__add__", "__sub__", "__and__", "__or__", "__mul__", "__truediv__", "__getitem__")

_lock = threading.Lock()
_active: Recorder | None = None
_local = threading.local()


def _workplane_class() -> type:
    import cadquery  # the optional extra; nothing else in SolidSeas imports it

    return cadquery.Workplane


def _version() -> str | None:
    module = sys.modules.get("cadquery")
    version = getattr(module, "__version__", None)
    return str(version)[:40] if version else None


def _wrap(name: str, fn: Any) -> Any:
    @functools.wraps(fn)
    def recorded(self, *args, **kwargs):
        rec = _active
        if rec is None or getattr(_local, "depth", 0):
            return fn(self, *args, **kwargs)  # not recording, or CadQuery calling itself
        _local.depth = 1
        try:
            result = fn(self, *args, **kwargs)
        finally:
            _local.depth = 0
        rec._note(name, self, args, kwargs, result)
        return result

    recorded.__solidseas_recorded__ = fn
    return recorded


class Recorder:
    """Records the calls made on ``workplane`` (CadQuery's ``Workplane`` when not given)
    while it is open (module notes)."""

    def __init__(self, workplane: type | None = None) -> None:
        self._class = workplane
        self._saved: dict[str, tuple[bool, Any]] = {}
        self._seen: dict[int, tuple[int, Any]] = {}  # id of a workplane: its number, and itself
        self._roots: dict[int, int] = {}  # a workplane's number: the number of its chain's first
        self._steps: list[dict] = []

    # ---------------------------------------------------------------- open and close
    def __enter__(self) -> Recorder:
        global _active
        cls = self._class if self._class is not None else _workplane_class()
        with _lock:
            if _active is not None:
                raise RuntimeError("another recorder is open: record one model at a time")
            self._class = cls
            names = [n for n in dir(cls) if not n.startswith("_")] + [n for n in OPERATORS if hasattr(cls, n)]
            try:
                for name in names:
                    attr = inspect.getattr_static(cls, name)
                    if not inspect.isfunction(attr) or hasattr(attr, "__solidseas_recorded__"):
                        continue  # a property, a class method, or one already wrapped
                    self._saved[name] = (name in cls.__dict__, cls.__dict__.get(name))
                    setattr(cls, name, _wrap(name, attr))
            except BaseException:
                self._restore()
                raise
            _active = self
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Put ``Workplane`` back as it was. Calls made after this are not recorded."""
        global _active
        with _lock:
            self._restore()
            if _active is self:
                _active = None

    def _restore(self) -> None:
        for name, (own, original) in self._saved.items():
            if own:
                setattr(self._class, name, original)
            else:
                delattr(self._class, name)
        self._saved.clear()

    # ---------------------------------------------------------------- what is noted
    def _known(self, wp: Any) -> int | None:
        known = self._seen.get(id(wp))
        return known[0] if known is not None and known[1] is wp else None

    def _number(self, wp: Any, root: int | None = None) -> int:
        """The workplane's number, given the first time it is seen. One the recorder did not
        see being made (a Sketch returns one) belongs to its parent's chain."""
        n = self._known(wp)
        if n is not None:
            return n
        if root is None:
            parent = self._known(getattr(wp, "parent", None))
            root = None if parent is None else self._roots[parent]
        n = len(self._seen)
        self._seen[id(wp)] = (n, wp)  # keeps it alive, so no other object takes its id
        self._roots[n] = n if root is None else root
        return n

    def _data(self, value: Any, budget: list[int], depth: int = 0) -> Any:
        budget[0] -= 1
        if budget[0] < 0 or depth > cqrecording.MAX_DEPTH:
            return {"object": type(value).__name__}
        if value is None or isinstance(value, (bool, str)):
            if isinstance(value, str) and len(value) > cqrecording.MAX_TEXT:
                return {"object": "str"}
            return value
        if isinstance(value, numbers.Integral) and abs(int(value)) <= 1 << 53:
            return int(value)
        if isinstance(value, numbers.Real):
            v = float(value)
            return v if math.isfinite(v) else {"object": type(value).__name__}
        if isinstance(value, (list, tuple)):
            return [self._data(v, budget, depth + 1) for v in value]
        if isinstance(value, self._class):
            return {"workplane": self._number(value)}
        kind = type(value)
        if kind.__module__.startswith("cadquery"):
            if kind.__name__ == "Vector":
                return {"vector": [float(value.x), float(value.y), float(value.z)]}
            if kind.__name__ == "Plane":
                return {
                    "plane": {
                        "origin": [float(c) for c in value.origin.toTuple()],
                        "x_dir": [float(c) for c in value.xDir.toTuple()],
                        "normal": [float(c) for c in value.zDir.toTuple()],
                    }
                }
        return {"object": kind.__name__}

    def _note(self, name: str, wp: Any, args: tuple, kwargs: dict, result: Any) -> None:
        if len(self._steps) >= cqrecording.MAX_STEPS:
            return
        budget = [cqrecording.MAX_VALUES]
        step = {
            "call": "Workplane" if name == "__init__" else name,
            "on": None,
            "args": [self._data(a, budget) for a in args],
            "kwargs": {str(k): self._data(v, budget) for k, v in kwargs.items()},
            "result": None,
        }
        if name == "__init__":
            step["result"] = self._number(wp)
        else:
            step["on"] = on = self._number(wp)
            if isinstance(result, self._class):
                step["result"] = self._number(result, self._roots[on])
        self._steps.append(step)

    # ---------------------------------------------------------------- the recording
    def recording(
        self,
        model: Any,
        *,
        name: str = "model",
        units: str = "mm",
        properties: dict[str, Any] | None = None,
    ) -> cqrecording.Recording:
        """The recording of ``model``, the workplane that holds the finished part: every step
        of its chain, the ``units`` its numbers are in, and the file ``properties`` the part
        gets (text, numbers, ``True`` or ``False``, and dates)."""
        index = self._known(model)
        if index is None:
            raise ValueError("the model is not a workplane this recorder saw being made")
        held = list(getattr(model, "objects", ()))
        if not held or any(_shape_type(v) not in ("Solid", "Compound", "CompSolid") for v in held):
            raise ValueError("the model holds no solid: pass the workplane that holds the finished part")
        root = self._roots[index]
        steps = [s for s in self._steps if self._roots[s["result"] if s["on"] is None else s["on"]] == root]
        data = {
            "format": cqrecording.FORMAT,
            "name": name,
            "units": units,
            "cadquery": _version(),
            "model": index,
            "steps": steps,
            "properties": [_property(k, v) for k, v in (properties or {}).items()],
        }
        if data["cadquery"] is None:
            del data["cadquery"]
        if len(self._steps) >= cqrecording.MAX_STEPS:
            raise ValueError(f"the model took more than {cqrecording.MAX_STEPS:,} calls to build")
        return cqrecording.from_data(data)

    def save(self, path: str | os.PathLike, model: Any, **options: Any) -> Path:
        """Write :meth:`recording` to ``path``, a new ``.json`` file (never over one)."""
        out = Path(path)
        if out.suffix.lower() != ".json":
            raise ValueError(f"a recording is saved as a .json file: {out.name}")
        text = cqrecording.to_json(self.recording(model, **options))
        with open(out, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return out


def _shape_type(value: Any) -> str | None:
    try:
        return str(value.ShapeType())
    except Exception:  # not a CadQuery shape
        return None


def _property(name: str, value: Any) -> dict:
    if isinstance(value, bool):
        return {"name": name, "value": value, "type": "yesno"}
    if isinstance(value, (int, float)):
        return {"name": name, "value": value, "type": "number"}
    if isinstance(value, datetime.date):
        return {"name": name, "value": value.isoformat()[:10], "type": "date"}
    return {"name": name, "value": str(value), "type": "text"}


__all__ = ["OPERATORS", "Recorder"]
