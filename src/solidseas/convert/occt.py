"""The ``occt`` conversion backend: Open CASCADE through the OCCT backend extension's helper
(``docs/EXTENSIONS.md`` sections 6 and 9, ``docs/OCCT.md`` tier 1, provisional).

Nothing here imports OCP. Open CASCADE runs only in the helper, a program of its own
(:mod:`solidseas_app.extensions.occt_helper`), which this module starts the first time a
file needs it and keeps for later files, one per process, ending it when the process ends.
The helper is found in this order:

1. ``SOLIDSEAS_OCCT_HELPER_PYTHON``, for a source checkout or a test: a Python interpreter
   where OCP imports, which runs the helper module of this checkout in isolated mode
   (``-I``), with a cap on its memory.
2. The OCCT backend extension, when its package is added and it is switched on: started
   by :func:`solidseas_app.extensions.start_helper`, which checks again that every file of
   the package is the one its manifest names, and puts it in a Job Object with the
   manifest's memory cap and time limit.

Otherwise the backend is unavailable, and :meth:`OcctBackend.unavailable` says what to do
in words. The answer is kept for :data:`AVAILABILITY_SECONDS`, so a folder listing asks
once, and a switch turned on in the viewer counts a moment later.

Every file goes to the helper as a copy in a new folder of its own (``docs/OCCT.md``
section 3: never the person's file, never a network path), and the helper writes its
result into a second new folder, from which this module reads it, bounded, before both
folders are removed. A file that crashes Open CASCADE or runs past the time limit ends
the helper and fails alone; the next file starts a new one. Results are kept in memory
by the SHA-256 of what was converted (:data:`CACHE_BYTES`), so a process that reads a
file more than once (a viewer worker reading its details, then its preview) converts it
once.

In the viewer and the REST service, files of other formats are read in worker processes
whose Job Object lets no worker start a process; the viewer's model pool and the service's
pool let each start one, this helper (``WorkerPool(helpers_per_worker=1)``, decided by
:func:`helpers_per_worker` while this backend is there), which runs in its own Job Object
inside the pool's. The catalog's pools and ``solidseas list`` read only a model file's
head, never its geometry, so their workers still start nothing.
"""

from __future__ import annotations

import atexit
import collections
import hashlib
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterable
from typing import Any

from .. import policy
from ..errors import (
    FormatNotSupportedError,
    SldFormatError,
    SldLimitError,
    WorkerTimeoutError,
)
from . import Backend, Converted

EXTENSION = "occt"  # the extension's id (solidseas_app.extensions.CATALOG)
ENV_PYTHON = "SOLIDSEAS_OCCT_HELPER_PYTHON"
HELPER_MODULE = "solidseas_app.extensions.occt_helper"
PROTOCOL = 1
MEMORY_MB = 3072  # a helper run from a checkout; the package's manifest sets its own
SECONDS = 300.0  # one file, from a checkout (Open CASCADE took up to 75 s to transfer one)
AVAILABILITY_SECONDS = 2.0
MAX_OUTPUT_BYTES = 1 << 30
CACHE_BYTES = 256 << 20
CACHE_ENTRIES = 16
SOURCE_NAMES = {"iges": "model.igs", "occt_brep": "model.brep", "step": "model.step"}
OUTPUT_NAMES = {"iges": "model.igs", "occt_brep": "model.brep", "step": "model.step"}

WHAT = "IGES and BREP files open with the OCCT backend extension"
NOT_ADDED = f"{WHAT}. Add its package in Tools > Extensions and switch it on."
SWITCHED_OFF = f"{WHAT}, which is switched off. Switch it on in Tools > Extensions."
NOT_ALLOWED = f"{WHAT}, which your administrator has not allowed on this PC."
NO_APP = (
    f"{WHAT} of SolidSeas Desktop. From a source checkout, set {ENV_PYTHON} to a Python where OCP imports."
)


def _app():
    """``solidseas_app.extensions``, which keeps the switches and the packages, or None
    when this installation has no app part."""
    try:
        from solidseas_app import extensions
    except ImportError:
        return None
    return extensions


def helper_script() -> str | None:
    """The helper module's file in this installation, found without importing it."""
    import importlib.util

    try:
        spec = importlib.util.find_spec(HELPER_MODULE)
    except (ImportError, ValueError):
        return None
    return spec.origin if spec is not None and spec.origin and os.path.isfile(spec.origin) else None


class OcctBackend(Backend):
    """See the module notes."""

    name = "occt"
    title = "the OCCT backend"
    reads = frozenset({"iges", "occt_brep", "step"})
    writes = frozenset({"iges", "occt_brep", "step"})

    def __init__(self) -> None:
        self._lock = threading.Lock()  # one file at a time through the one helper
        self._helper = None
        self._helper_source: tuple | None = None
        self._checked: tuple[float, str | None] | None = None
        self._cache: collections.OrderedDict[tuple, Converted] = collections.OrderedDict()
        self._cache_bytes = 0
        atexit.register(self.close)

    # ----------------------------------------------------------------------- where it is
    def unavailable(self) -> str | None:
        now = time.monotonic()
        hit = self._checked
        if hit is not None and now - hit[0] < AVAILABILITY_SECONDS:
            return hit[1]
        reason = self._why_not()
        self._checked = (now, reason)
        return reason

    def _why_not(self) -> str | None:
        python = os.environ.get(ENV_PYTHON, "").strip()
        if python:
            if not os.path.isfile(python):
                return f"{ENV_PYTHON} names no file: {python}"
            if helper_script() is None:
                return f"{ENV_PYTHON} is set, but this installation has no {HELPER_MODULE}"
            return None
        app = _app()
        if app is None:
            return NO_APP
        pol = policy.current()
        if not policy.extension_allowed(pol, EXTENSION):
            return NOT_ALLOWED
        if app.added_manifest(EXTENSION) is None:
            return NOT_ADDED
        if not app.is_on(EXTENSION, app.read_state(), pol=pol):
            return SWITCHED_OFF
        return None

    @staticmethod
    def _source() -> tuple:
        """Where the helper comes from now: a checkout's interpreter and helper module, or
        the extension's package."""
        python = os.environ.get(ENV_PYTHON, "").strip()
        return ("checkout", python, helper_script()) if python else ("extension",)

    def _start(self, source: tuple):
        from ..helpers import Helper

        if source[0] == "checkout":
            _, python, script = source
            command = [python, "-I", script or "", "--memory-mb", str(MEMORY_MB)]
            return Helper(
                command,
                label="the OCCT helper",
                protocol=PROTOCOL,
                memory_mb=MEMORY_MB,
                hard_limit=SECONDS,
                thread_name="ext-occt",
            )
        app = _app()
        if app is None:
            raise FormatNotSupportedError(NO_APP, detail={"rule": "needs_extension"})
        return app.start_helper(EXTENSION, app.read_state())

    def _running(self):
        """The helper, started now when there is none, the last one ended, or it came from
        somewhere else than the helper would now."""
        from ..helpers import HelperError

        source = self._source()
        if self._helper is not None and self._helper.alive and self._helper_source == source:
            return self._helper
        self.close()
        try:
            self._helper = self._start(source)
        except FormatNotSupportedError:
            raise
        except (HelperError, ValueError, OSError) as exc:  # HelperRefused is a ValueError
            self._checked = None
            raise FormatNotSupportedError(
                f"The OCCT backend could not start: {exc}", detail={"rule": "needs_extension"}
            ) from None
        self._helper_source = source
        return self._helper

    def close(self) -> None:
        """End the helper, if one runs."""
        helper, self._helper = self._helper, None
        if helper is not None:
            try:
                helper.close(timeout=10.0)
            except Exception:  # pragma: no cover - best effort at exit
                pass

    def forget(self) -> None:
        """End the helper and forget what was asked and converted (for tests, and after a
        switch changes)."""
        with self._lock:
            self.close()
            self._checked = None
            self._cache.clear()
            self._cache_bytes = 0

    # ----------------------------------------------------------------------- converting
    def convert_bytes(
        self, data: bytes, format_id: str, target: str, *, name: str | None = None
    ) -> Converted:
        if format_id not in self.reads or target not in self.writes:
            raise FormatNotSupportedError(
                f"the OCCT backend does not convert {format_id} to {target}",
                detail={"rule": "no_reader", "value": format_id},
            )
        reason = self.unavailable()
        if reason is not None:
            raise FormatNotSupportedError(reason, detail={"rule": "needs_extension", "value": format_id})
        key = (format_id, target, name, hashlib.sha256(data).hexdigest())
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
            made = self._convert(data, format_id, target, name)
            self._keep(key, made)
            return made

    def _keep(self, key: tuple, made: Converted) -> None:
        if len(made.data) > CACHE_BYTES // 4:
            return
        self._cache[key] = made
        self._cache_bytes += len(made.data)
        while self._cache and (len(self._cache) > CACHE_ENTRIES or self._cache_bytes > CACHE_BYTES):
            _, old = self._cache.popitem(last=False)
            self._cache_bytes -= len(old.data)

    def _convert(self, data: bytes, format_id: str, target: str, name: str | None) -> Converted:
        from ..helpers import HelperExitedError, HelperRequestError, HelperTimeoutError

        stage = tempfile.mkdtemp(prefix="solidseas-occt-")
        try:
            src_dir, out_dir = os.path.join(stage, "in"), os.path.join(stage, "out")
            os.mkdir(src_dir)
            os.mkdir(out_dir)
            src = os.path.join(src_dir, SOURCE_NAMES[format_id])
            with open(src, "xb") as fh:
                fh.write(data)
            helper = self._running()
            args = {"path": src, "from": format_id, "to": target, "out_dir": out_dir}
            if name:
                args["name"] = name
            try:
                result = helper.request("convert", args)
            except HelperTimeoutError:
                raise WorkerTimeoutError(
                    "Open CASCADE did not finish the file in time; the OCCT helper was ended"
                ) from None
            except HelperExitedError:
                raise SldFormatError(
                    "Open CASCADE stopped while it read the file, which may be damaged"
                ) from None
            except HelperRequestError as exc:
                if exc.code == "out_of_memory":
                    raise SldLimitError(
                        "Open CASCADE ran out of memory on the file", detail={"limit": "memory"}
                    ) from None
                text = str(exc).removeprefix("convert: ")
                raise SldFormatError(f"Open CASCADE could not convert the file: {text}") from None
            return Converted(target, self._result(result, out_dir, target), _report(result.get("report")))
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _result(result: dict, out_dir: str, target: str) -> bytes:
        """The file the helper wrote, read only from where it was told to write it."""
        want = os.path.join(out_dir, OUTPUT_NAMES[target])
        given = result.get("path")
        if not isinstance(given, str) or os.path.normcase(os.path.abspath(given)) != os.path.normcase(want):
            raise SldFormatError("the OCCT helper wrote somewhere it was not given")
        if os.path.islink(want) or not os.path.isfile(want):
            raise SldFormatError("the OCCT helper wrote no file")
        size = os.path.getsize(want)
        if size > MAX_OUTPUT_BYTES:
            raise SldLimitError(
                f"the converted file would be larger than {MAX_OUTPUT_BYTES:,} bytes",
                detail={"limit": "max_bytes"},
            )
        with open(want, "rb") as fh:
            return fh.read(MAX_OUTPUT_BYTES + 1)


_COUNTS = (
    "roots",
    "shapes",
    "solids_read",
    "loose_faces_read",
    "solids_sewn",
    "open_shells",
    "free_faces",
    "solids",
    "shells",
    "faces",
)
_UNITS = ("in", "mm", "ft", "mi", "m", "km", "mil", "micron", "cm", "uin")


def _short(value: Any, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    value = "".join(c for c in value if c.isprintable()).strip()
    return value[:limit] or None


def _report(raw: Any) -> dict[str, Any]:
    """The helper's report, kept only as the numbers and short texts it should hold: a
    reply is data, never trusted further than that."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in _COUNTS:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1 << 40:
            out[key] = value
    valid = raw.get("valid")
    out["valid"] = valid if isinstance(valid, bool) else None
    unit = raw.get("unit")
    out["unit"] = unit if unit in _UNITS else None
    app = raw.get("application") if isinstance(raw.get("application"), dict) else {}
    out["application"] = {"name": _short(app.get("name")), "version": _short(app.get("version"))}
    variant = raw.get("variant")
    out["variant"] = variant if variant in ("text", "binary") else None
    return out


BACKEND = OcctBackend()


def forget() -> None:
    """:meth:`OcctBackend.forget` of the one backend."""
    BACKEND.forget()


def helpers_per_worker(formats: Iterable[str] | None = None) -> int:
    """How many processes each worker of a :class:`~solidseas.workers.WorkerPool` may start
    to read the geometry of ``formats`` (registry ids; None for every format): one, this
    backend's helper, while the backend is available here and ``formats`` holds a format
    only it reads (IGES, BREP); else none, so the pool's workers start no process at all.
    A pool decides it when it starts: the viewer's model pool is started again when the
    switch changes, the REST service's when the service is."""
    from ..formats import registry

    wanted = registry.FORMATS if formats is None else formats
    if not any(getattr(registry.FORMATS.get(f), "backend", None) == BACKEND.name for f in wanted):
        return 0
    try:
        return 1 if BACKEND.unavailable() is None else 0
    except Exception:  # a switch or a policy that cannot be read: the workers start nothing
        return 0


__all__ = [
    "AVAILABILITY_SECONDS",
    "BACKEND",
    "ENV_PYTHON",
    "EXTENSION",
    "NOT_ADDED",
    "SWITCHED_OFF",
    "OcctBackend",
    "forget",
    "helper_script",
    "helpers_per_worker",
]
