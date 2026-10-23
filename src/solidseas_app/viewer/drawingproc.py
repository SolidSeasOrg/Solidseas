"""The drawing library, in a process of its own (``docs/DRAWINGS.md`` 15.3 and 15.4).

Making a drawing reads a part, tessellates it, recognises its features, draws its
views and plans its dimensions: seconds of pure Python for a large part, hundreds of
megabytes, and a crafted part could ask for much more. Editing lays the sheet out
again from the model. None of that may run on the UI thread (15.4), and none of it
runs in the window's process at all: the New Drawing wizard and the drawing editor
run the library in a child process (:class:`DrawingWorker`), built as
:mod:`.meshproc` builds the mesh reader's:

* The child is started with ``meshproc._start`` the first time it is wanted and kept
  for the next request; one request runs at a time. The window asks from a worker
  thread and waits on a pipe there, without the interpreter lock; the UI never waits
  on the pipe.
* :meth:`DrawingWorker.cancel` ends the child at once; the next request starts a new
  one. Every request has a time limit, ``DrawingLimits.seconds_total`` and a margin
  (:data:`MARGIN_SECONDS`), past which the child is ended and the request reports
  ``timeout``. On Windows the child runs in a job object (``meshproc._Job``) at
  below-normal priority, held to :func:`memory_limit` (``child_memory_mb``, at most
  half the PC's memory) and ended with the viewer however it ends; running out of
  that memory reports ``too_large``. A request that did not finish raises
  :class:`ProcessStopped`, whose ``reason`` says which of these it was.
* The child keeps the runs of the drawings it made, regenerated or attached beside
  them, in ``drawing.edit``'s registry, so an edit of one lays out again without
  reading the part. A child started again has none: an edit then answers
  ``model_not_found`` (:class:`~solidseas.errors.ModelNotFoundError`), and the
  window calls :meth:`DrawingWorker.attach` with the model and asks again.

**What crosses the pipe** is never a pickle, either way. A request is one JSON frame
(a drawing travels in it as the text of its ``.ssdrw``). The child first says it is
ready in a short JSON frame; each answer is then one JSON header frame, read with a
length limit (:data:`MAX_HEADER_BYTES`), and the raw frames the header announces: a
drawing as the ``.ssdrw`` bytes ``drawing.document.dumps`` writes, a PDF or a DXF. A
``make`` that asks for progress first gets, before its header, a short frame as each
stage of the drawing pipeline starts (:func:`progress_in` checks each, at most
:data:`MAX_PROGRESS` of them).
Each frame is read with the size the header gives as its bound and checked against
that size and the SHA-256 the header gives before it is used, and the drawing is
read with ``document.loads``, which takes any ``.ssdrw`` as hostile input. A header
that does not hold together ends the child and raises :class:`ProcessStopped` with
reason ``bad_answer``. An error raised in the child crosses as ``{code, message,
detail}`` (with the exception's class name, and a refused release's reasons), and
the client raises the same class again: the class of ``solidseas.errors`` by that
name or code, ``ReleaseRefusedError`` with its reasons, ``FileNotFoundError`` and
``PermissionError`` for the system's, ``WorkerJobError`` for anything else.

Arguments that are not JSON have a small codec here, both ways, checked as strictly
as the library checks them: ``DrawingOptions`` and ``DrawingLimits`` by their
fields, Drawing Settings as their ``Drawing.json`` content (``settings.to_dict``, so
the wizard's unsaved choices reach the child), a feature control frame
(``types.FrameCell``) as the drawing file reads one, and Add Dimension's
``edit.Candidate``.

**Saving and writing files stay in the window's process.** This module only gives
back bytes: the ``.ssdrw`` of a drawing, and a PDF or DXF from the writers. Where
they go, and what may be replaced, is decided where the user sees the answer,
through ``drawing.document``'s ``save``, ``save_target``, ``export_target``,
``write_output`` and ``record_output``, so the rules of section 12.6 (a refused
folder asks for another, a file SolidSeas did not write is never replaced, a released
export is never replaced) are applied by the window. The child opens parts read-only
and writes nothing.

Nothing here imports Qt, and the window's process imports only the quick and pure
parts of the library from here (``document``, ``types``, ``edit`` for its
``Candidate``, ``merge`` for its report); everything geometric is imported in the
child.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import inspect
import json
import math
import multiprocessing.util
import os
import re
import threading
import time
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from solidseas.drawing.limits import DEFAULT_LIMITS, DrawingLimits
from solidseas.errors import InvalidArgumentError, SolidSeasError

from .meshproc import _start

MARGIN_SECONDS = 30.0  # past seconds_total: a stage is checked against its bound only when it ends
START_SECONDS = 120.0  # a new child's start-up and imports, before it says it is ready
POLL_SECONDS = 0.05
MAX_HEADER_BYTES = 16 << 20  # an answer's JSON: a drawing's summary, checks and candidates
MAX_READY_BYTES = 1024
# A request carries at most one drawing as JSON text, whose quotes and backslashes JSON
# doubles, and settings of at most 256 KiB.
MAX_REQUEST_BYTES = 2 * DEFAULT_LIMITS.drawing_bytes + (2 << 20)
MAX_TEXT = 4096  # characters of a message, a warning or a check's text
MAX_LIST = 100_000  # checks, warnings or candidates in one answer
MAX_PATH = 32_767  # characters of a path a request names
FRAME_KINDS = ("ssdrw", "pdf", "dxf")
EXPORT_KINDS = ("pdf", "dxf")
READY = {"ready": True}
# Progress (a ``make`` that asks for it): the child says each stage of the drawing pipeline
# as it starts, in a short frame before the answer's header, {"progress": {"stage", "step",
# "of"}}; the window takes at most this many such frames before the header.
MAX_PROGRESS = 16
MAX_PROGRESS_BYTES = 512
_PROGRESS_START = b'{"progress":'

# The operations of drawing.edit that :meth:`DrawingWorker.edit` runs by name: each takes
# the drawing first and returns (drawing, checks).
OPERATIONS = (
    "relayout",
    "move_balloon",
    "reset_balloon",
    "remove",
    "restore",
    "delete",
    "add",
    "link",
    "unlink",
    "set_origin",
    "set_scheme",
    "set_depth_reference",
    "set_tolerance",
    "set_precision",
    "set_prefix",
    "set_suffix",
    "reset_text",
    "override_value",
    "set_frame",
    "reset_frame",
    "set_datum",
    "move",
    "reset_position",
    "flip",
    "set_sheet",
    "set_scale",
    "set_units",
    "set_parts_list",
    "add_view",
    "remove_view",
    "edit_notes",
    "add_flag_note",
    "set_title",
    "set_tolerance_block",
    "use_settings",
    "confirm_thread",
    "clear_thread",
    "confirm_end",
    "sign",
    "release_drawing",
    "start_revision",
)
# The rest of drawing.edit's names: requests of their own (attach, candidates, checks,
# forget) or the child's own business.
NOT_OPERATIONS = ("MAX_LIVE", "Candidate", "Live", "adopt", "attach", "candidates", "checks", "forget")
NOT_OPERATIONS += ("live_for", "move_live", "boms")

# Why a request did not finish (:class:`ProcessStopped`), the error code each carries, and
# the words the window shows.
REASONS = {
    "cancelled": ("interrupted", "The drawing request was cancelled."),
    "timeout": ("timeout", "The drawing process did not finish in time and was ended."),
    "too_large": (
        "drawing_too_complex",
        "The drawing needed more memory than the viewer lets its drawing process use.",
    ),
    "stopped": ("worker_crashed", "The drawing process stopped before it finished."),
    "bad_answer": ("worker_crashed", "The drawing process sent an answer SolidSeas does not accept."),
}

_IDENT = re.compile(r"[a-z0-9-]{1,64}")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FRAME_LETTER = re.compile(r"[A-Z]{1,2}")  # as the drawing file reads a frame's datums
_CANDIDATE_KEY = re.compile(r"[a-z0-9_]+(?:/[a-z0-9_-]+)*")  # as the drawing file reads a key
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WORKERS: weakref.WeakSet[DrawingWorker] = weakref.WeakSet()


def _close_all() -> None:
    """Close every worker the window did not, when Python exits."""
    for worker in list(_WORKERS):
        worker.close()


# Run by multiprocessing's exit handler before it ends the children it still knows of
# (as in .meshproc).
multiprocessing.util.Finalize(None, _close_all, exitpriority=10)


# --------------------------------------------------------------------------- errors
class BadAnswer(Exception):
    """The drawing process's answer does not hold together: it is not used."""


class ProcessStopped(SolidSeasError):
    """A request the drawing process did not finish. ``reason`` is ``cancelled`` (the
    window asked), ``timeout`` (past the time limit), ``too_large`` (past the job
    object's memory limit), ``stopped`` (the child ended on its own) or ``bad_answer``
    (an answer that did not hold together); the child was ended in each case but a
    cancel that came before the request was sent. ``code`` follows the reason
    (``interrupted``, ``timeout``, ``drawing_too_complex``, ``worker_crashed``)."""

    def __init__(self, reason: str, message: str | None = None, *, detail: dict | None = None) -> None:
        if reason not in REASONS:
            raise ValueError(f"no such reason {reason!r}")
        code, words = REASONS[reason]
        super().__init__(message or words, detail=detail)
        self.reason = reason
        self.code = code


# --------------------------------------------------------------------------- what the window gets
@dataclass(frozen=True)
class Check:
    """One finding of the checklist (``drawing.checks.Check``'s fields), as the child
    found it: ``code``, ``level`` (``error``, ``warning`` or ``information``),
    ``message``, ``item`` and ``fixes``."""

    code: str
    level: str
    message: str
    item: str = ""
    fixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Body:
    """A body of the part as wizard page 1 lists it."""

    name: str
    type: str
    faces: int
    selected: bool
    hidden: bool = False


@dataclass(frozen=True)
class AssemblyProbe:
    """What wizard page 1 says of an assembly: the lines of its parts list, the part
    instances drawn, and each instance left out with the reason (``id: why``)."""

    items: int
    instances: int
    left_out: tuple[str, ...] = ()


@dataclass(frozen=True)
class Probe:
    """What wizard page 1 needs before anything is made (15.3): the part's file name,
    the configuration read and every configuration, its bodies, the drawing unit, where
    it came from (``file``, ``guessed`` with ``evidence``, or ``user``) and the unit the
    part states, the overall size in metres of the bodies drawn from their topology
    (``size_m``, see :func:`_extent`; ``size_mm`` and ``size_in`` say it in both
    units), the counts a drawing is bounded by (bodies,
    faces, edges, and ``blends``, the rolling-sphere faces), and why the part is refused
    (``refused``, with its error ``refused_code`` and ``refused_rule``): not a part, or
    over the bounds. A refused part may have no bodies or size. An assembly's ``bodies``
    are its part instances, by id, and ``assembly`` says what it holds
    (:class:`AssemblyProbe`); a part's is None."""

    name: str
    configuration: str | None = None
    configurations: tuple[str, ...] = ()
    active_configuration: str | None = None
    bodies: tuple[Body, ...] = ()
    unit: str | None = None
    unit_origin: str | None = None
    stated_unit: str | None = None
    evidence: Any = None  # drawing.numbers.UnitGuess when the unit was guessed
    size_m: tuple[float, float, float] | None = None
    counts: Mapping[str, int] = dataclasses.field(default_factory=dict)
    refused: str | None = None
    refused_code: str | None = None
    refused_rule: str | None = None
    warnings: tuple[str, ...] = ()
    seconds: Mapping[str, float] = dataclasses.field(default_factory=dict)
    assembly: AssemblyProbe | None = None

    @property
    def size_mm(self) -> tuple[float, float, float] | None:
        return None if self.size_m is None else tuple(v * 1000.0 for v in self.size_m)  # type: ignore[return-value]

    @property
    def size_in(self) -> tuple[float, float, float] | None:
        return None if self.size_m is None else tuple(v / 0.0254 for v in self.size_m)  # type: ignore[return-value]


@dataclass(frozen=True)
class Answer:
    """A drawing the child made or changed: ``data``, its ``.ssdrw`` bytes (what the
    window saves through ``document.save``), and ``drawing``, those bytes read here with
    ``document.loads`` and given the child's ``checks``, ``coverage`` and ``warnings``;
    ``summary``, the drawing's summary as ``drawing_result`` carries it; the thread
    candidates; ``seconds`` per stage (``total`` the child's, ``wall`` the whole wait,
    ``start`` a new child's start-up); for a regeneration the ``merge`` report
    (``drawing.merge.MergeReport``); and ``turned``, why the part looks turned when it
    does (``drawing.types.TurnedProfile.reason``), which the wizard suggests the
    Turned type from."""

    data: bytes
    drawing: Any
    summary: Mapping[str, Any]
    checks: tuple[Check, ...]
    coverage: Any = None  # drawing.types.Coverage, when the request laid the drawing out
    thread_candidates: tuple[Mapping[str, Any], ...] = ()
    seconds: Mapping[str, float] = dataclasses.field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    merge: Any = None
    turned: str | None = None


@dataclass(frozen=True)
class Attached:
    """The model attached to a drawing in the child: whether it is the very file the
    drawing records (else only its geometry is the same), and the checks with the
    model."""

    same_file: bool
    checks: tuple[Check, ...]
    thread_candidates: tuple[Mapping[str, Any], ...] = ()
    seconds: Mapping[str, float] = dataclasses.field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exported:
    """A PDF or DXF of a drawing's sheet, as bytes: the window writes them through
    ``document.export_target`` and ``write_output``."""

    kind: str
    data: bytes
    seconds: Mapping[str, float] = dataclasses.field(default_factory=dict)
    warnings: tuple[str, ...] = ()


# --------------------------------------------------------------------------- codecs, both ways
def _limits_out(limits: DrawingLimits) -> dict[str, Any]:
    return dataclasses.asdict(limits)


def _limits_in(value: Any) -> DrawingLimits:
    if value is None:
        return DEFAULT_LIMITS
    names = {f.name for f in dataclasses.fields(DrawingLimits)}
    if not isinstance(value, dict) or not set(value) <= names:
        raise InvalidArgumentError("limits are DrawingLimits' fields", detail={"parameter": "limits"})
    return DrawingLimits(**value)  # every field checked against its ceiling


def options_to_json(options: Any) -> dict[str, Any]:
    """``DrawingOptions`` as a JSON object of its fields."""
    from solidseas.drawing.types import DrawingOptions

    if not isinstance(options, DrawingOptions):
        raise InvalidArgumentError("options must be DrawingOptions", detail={"parameter": "options"})
    out: dict[str, Any] = {}
    for f in dataclasses.fields(options):
        v = getattr(options, f.name)
        if f.name in ("arrangement", "balloons"):
            v = [list(e) for e in v]
        elif isinstance(v, tuple):
            v = list(v)
        out[f.name] = v
    return out


def options_from_json(value: Any) -> Any:
    """``DrawingOptions`` from :func:`options_to_json`'s object; every value is checked
    by ``DrawingOptions`` itself, and a member it does not have is refused."""
    from solidseas.drawing.types import DrawingOptions

    if value is None:
        return DrawingOptions()
    names = {f.name for f in dataclasses.fields(DrawingOptions)}
    if not isinstance(value, dict) or not set(value) <= names:
        raise InvalidArgumentError("options are DrawingOptions' fields", detail={"parameter": "options"})
    kw = dict(value)
    for key in ("views", "scale", "bodies"):
        if isinstance(kw.get(key), list):
            kw[key] = tuple(kw[key])
    if "arrangement" in kw:
        pairs = kw["arrangement"]
        if not isinstance(pairs, list) or not all(isinstance(p, list) and len(p) == 2 for p in pairs):
            raise InvalidArgumentError(
                "arrangement is pairs of view/axis and scheme", detail={"parameter": "arrangement"}
            )
        kw["arrangement"] = tuple((p[0], p[1]) for p in pairs)
    if "balloons" in kw:
        moved = kw["balloons"]
        if not isinstance(moved, list) or not all(isinstance(e, list) and len(e) == 3 for e in moved):
            raise InvalidArgumentError("balloons are [item, dx, dy]", detail={"parameter": "balloons"})
        kw["balloons"] = tuple((e[0], e[1], e[2]) for e in moved)
    return DrawingOptions(**kw)


def settings_to_json(settings: Any) -> dict[str, Any] | None:
    """Drawing Settings as their ``Drawing.json`` content (``settings.to_dict``); a
    mapping is taken as that content already; None stays None (the defaults)."""
    from solidseas.drawing import settings as settings_mod

    if settings is None:
        return None
    if isinstance(settings, settings_mod.DrawingSettings):
        return settings_mod.to_dict(settings)
    if isinstance(settings, Mapping):
        return _jsonable(dict(settings), "settings")
    raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})


def settings_from_json(value: Any) -> tuple[Any, list[str]]:
    """Drawing Settings from their ``Drawing.json`` content, as the library reads the
    file (``settings.from_dict``: a bad value falls back to its default, and says so)."""
    from solidseas.drawing import settings as settings_mod

    if value is None:
        return settings_mod.DrawingSettings(), []
    settings, problems = settings_mod.from_dict(value)
    return settings, list(problems)


def frame_to_json(frame: Any) -> dict[str, Any] | None:
    """A feature control frame (``types.FrameCell``) as the drawing file writes one."""
    from solidseas.drawing.types import FrameCell

    if frame is None:
        return None
    if not isinstance(frame, FrameCell):
        raise InvalidArgumentError("frame must be a FrameCell", detail={"parameter": "frame"})
    return {
        "characteristic": frame.characteristic,
        "value": frame.value,
        "diameter": frame.diameter,
        "modifier": frame.modifier,
        "datums": list(frame.datums),
    }


def frame_from_json(value: Any) -> Any:
    """A ``types.FrameCell`` from :func:`frame_to_json`'s object, checked as the drawing
    file reader checks a frame (a known characteristic, a zone from 0 to 1000, Ø true
    or false, MMC, LMC or none, up to three datum letters), with no other member."""
    from solidseas.drawing import standards
    from solidseas.drawing.types import FrameCell

    if value is None:
        return None

    def bad(why: str) -> InvalidArgumentError:
        return InvalidArgumentError(f"frame: {why}", detail={"parameter": "frame"})

    keys = ("characteristic", "value", "diameter", "modifier", "datums")
    if not isinstance(value, dict) or not set(value) <= set(keys) or "characteristic" not in value:
        raise bad("it is not a feature control frame")
    characteristic = value["characteristic"]
    if not isinstance(characteristic, str) or characteristic not in standards.CHARACTERISTICS:
        raise bad("it is not a characteristic SolidSeas knows")
    zone = value.get("value")
    if isinstance(zone, bool) or not isinstance(zone, (int, float)) or not math.isfinite(zone):
        raise bad("its zone is not a number")
    if not 0.0 <= zone <= 1e3:
        raise bad("its zone is not from 0 to 1000")
    diameter = value.get("diameter", False)
    if not isinstance(diameter, bool):
        raise bad("diameter is true or false")
    modifier = value.get("modifier")
    if modifier not in (None, "mmc", "lmc"):
        raise bad("the modifier is mmc, lmc or none")
    datums = value.get("datums", [])
    if not isinstance(datums, list) or len(datums) > 3:
        raise bad("its datums are up to three letters")
    for d in datums:
        if not isinstance(d, str) or not _FRAME_LETTER.fullmatch(d):
            raise bad("a datum is not a letter")
    return FrameCell(characteristic, float(zone), diameter, modifier, tuple(datums))


def candidate_to_json(candidate: Any) -> dict[str, Any]:
    """Add Dimension's ``edit.Candidate`` as a JSON object of its fields."""
    from solidseas.drawing.edit import Candidate

    if not isinstance(candidate, Candidate):
        raise InvalidArgumentError("candidate must be an edit.Candidate", detail={"parameter": "candidate"})
    return {
        "kind": candidate.kind,
        "key": candidate.key,
        "value": candidate.value,
        "words": candidate.words,
        "features": list(candidate.features),
        "axis": candidate.axis,
        "view": candidate.view,
        "dimension": candidate.dimension,
    }


def candidate_from_json(value: Any) -> Any:
    """An ``edit.Candidate`` from :func:`candidate_to_json`'s object: a ``restore`` or a
    ``distance``, a key as the drawing file reads one, a finite value, one or two
    feature ids, an axis x, y or z, ids for the view and the dimension, and no other
    member. ``edit.add`` then checks it against the drawing's plan."""
    from solidseas.drawing.edit import Candidate

    def bad(why: str) -> InvalidArgumentError:
        return InvalidArgumentError(f"candidate: {why}", detail={"parameter": "candidate"})

    keys = ("kind", "key", "value", "words", "features", "axis", "view", "dimension")
    if not isinstance(value, dict) or set(value) != set(keys):
        raise bad("it is not one of candidates()")
    if value["kind"] not in ("restore", "distance"):
        raise bad("its kind is restore or distance")
    key = value["key"]
    if not isinstance(key, str) or len(key) > 256 or not _CANDIDATE_KEY.fullmatch(key):
        raise bad("its key is not a dimension key")
    number = value["value"]
    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
        raise bad("its value is not a number")
    words = value["words"]
    if not isinstance(words, str) or len(words) > 256 or _CONTROL.search(words):
        raise bad("its words are not one line of text")
    features = value["features"]
    if not isinstance(features, list) or not 1 <= len(features) <= 2:
        raise bad("it names one or two features")
    for fid in features:
        if not isinstance(fid, str) or not _IDENT.fullmatch(fid):
            raise bad("a feature id is not an id")
    if value["axis"] not in (None, "x", "y", "z"):
        raise bad("its axis is x, y or z")
    for name in ("view", "dimension"):
        v = value[name]
        if v is not None and (not isinstance(v, str) or not _IDENT.fullmatch(v)):
            raise bad(f"its {name} is not an id")
    return Candidate(
        value["kind"],
        key,
        float(number),
        words,
        tuple(features),
        value["axis"],
        value["view"],
        value["dimension"],
    )


def _jsonable(value: Any, parameter: str, depth: int = 0) -> Any:
    """``value`` as plain JSON for a request: the codecs' types as their objects, tuples
    as lists, a date as ``YYYY-MM-DD``; a number must be finite."""
    from solidseas.drawing import settings as settings_mod
    from solidseas.drawing.edit import Candidate
    from solidseas.drawing.types import FrameCell

    if depth > 32:
        raise InvalidArgumentError(f"{parameter} is nested too deeply", detail={"parameter": parameter})
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidArgumentError(
                f"{parameter} holds a number that is not finite", detail={"parameter": parameter}
            )
        return value
    if isinstance(value, FrameCell):
        return frame_to_json(value)
    if isinstance(value, Candidate):
        return candidate_to_json(value)
    if isinstance(value, settings_mod.DrawingSettings):
        return settings_mod.to_dict(value)
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, parameter, depth + 1) for v in value]
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise InvalidArgumentError(
                    f"{parameter} has a key that is not text", detail={"parameter": parameter}
                )
            out[k] = _jsonable(v, parameter, depth + 1)
        return out
    raise InvalidArgumentError(
        f"{parameter} holds a {type(value).__name__}, which does not cross to the drawing process",
        detail={"parameter": parameter},
    )


# Arguments of drawing.edit's operations that are not JSON, decoded by their parameter's name.
_DECODERS = {
    "frame": frame_from_json,
    "candidate": candidate_from_json,
    "settings": lambda v: settings_from_json(v)[0],
}


# --------------------------------------------------------------------------- errors, both ways
def _error_frame(exc: BaseException) -> dict[str, Any]:
    """The child's error object for ``exc``: ``code``, ``message`` (the exception's own
    text), the safe ``detail``, the class name, and a refused release's ``reasons``. An
    edit without the model (``invalid_argument`` with rule ``model_not_found``) is
    answered with the code ``model_not_found``, whose class is still an
    ``InvalidArgumentError``."""
    from solidseas import model

    info = model.error_info(exc)
    code, name = info["code"], info["exception"]
    detail = dict(info["detail"] or {})
    if code == "invalid_argument" and detail.get("rule") == "model_not_found":
        code, name = "model_not_found", "ModelNotFoundError"
    message = model.clean_text(str(exc))[:MAX_TEXT] or info["message"]
    out: dict[str, Any] = {"code": code, "message": message, "detail": detail, "exception": name}
    reasons = getattr(exc, "reasons", None)
    if detail.get("rule") == "release_refused" and isinstance(reasons, (list, tuple)):
        out["reasons"] = [model.clean_text(str(r))[:MAX_TEXT] for r in reasons][:1000]
    return out


_CLASSES: dict[str, dict[str, type]] = {}


def _error_classes() -> dict[str, dict[str, type]]:
    """The classes of ``solidseas.errors`` by name and by code (the most general class of
    each code), and the drawing file's own ``DrawingFileError`` by name."""
    if not _CLASSES:
        from solidseas import errors
        from solidseas.drawing.document import DrawingFileError

        found = [
            obj
            for obj in vars(errors).values()
            if isinstance(obj, type)
            and issubclass(obj, errors.SolidSeasError)
            and obj not in (errors.SolidSeasError, errors.WorkerJobError)
            and not obj.__name__.startswith("_")
            and obj.code != errors.SolidSeasError.code
        ]
        by_code: dict[str, type] = {}
        for cls in sorted(found, key=lambda c: (len(c.__mro__), c.__name__)):
            by_code.setdefault(cls.code, cls)
        by_name = {cls.__name__: cls for cls in found}
        by_name[DrawingFileError.__name__] = DrawingFileError
        _CLASSES.update(by_code=by_code, by_name=by_name)
    return _CLASSES


def _detail_in(value: Any) -> dict[str, Any]:
    from solidseas import model

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BadAnswer("an error's detail is not an object")
    out: dict[str, Any] = {}
    for key, v in value.items():
        if key not in model.DETAIL_KEYS:
            raise BadAnswer("an error's detail holds a member it may not")
        if isinstance(v, str):
            if len(v) > MAX_TEXT:
                raise BadAnswer("an error's detail holds text too long")
        elif not isinstance(v, (int, bool)):
            raise BadAnswer("an error's detail holds a value it may not")
        out[key] = v
    return out


def _raise_error(frame: Any) -> None:
    """Raise again in this process the error the child answered (see the module notes)."""
    from solidseas import model
    from solidseas.errors import WorkerJobError

    if not isinstance(frame, dict):
        raise BadAnswer("an error is not an object")
    code, message, name = frame.get("code"), frame.get("message"), frame.get("exception")
    if not isinstance(code, str) or code not in model.ERROR_CODES:
        raise BadAnswer("an error's code is not one SolidSeas has")
    if not isinstance(message, str) or len(message) > MAX_TEXT:
        raise BadAnswer("an error's message is not text")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise BadAnswer("an error's class is not a name")
    detail = _detail_in(frame.get("detail"))
    reasons = frame.get("reasons")
    if reasons is not None:
        if not isinstance(reasons, list) or len(reasons) > 1000:
            raise BadAnswer("a refused release's reasons are not a list")
        if not all(isinstance(r, str) and len(r) <= MAX_TEXT for r in reasons):
            raise BadAnswer("a refused release's reason is not text")
    if code == "invalid_argument" and detail.get("rule") == "release_refused" and reasons is not None:
        from solidseas.drawing.release import ReleaseRefusedError

        raise ReleaseRefusedError(reasons)
    classes = _error_classes()
    cls = classes["by_name"].get(name)
    if cls is None or cls.code != code:
        cls = classes["by_code"].get(code)
    if cls is not None:
        raise cls(message, detail=detail or None)
    if code == "not_found":
        raise FileNotFoundError(message)
    if code == "permission_denied":
        raise PermissionError(message)
    raise WorkerJobError(
        {"code": code, "message": message, "exception": name, "detail": detail, "reader_message": message}
    )


# --------------------------------------------------------------------------- checking an answer
def _text(value: Any, what: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise BadAnswer(f"{what} is not text")
    return value


def _opt_text(value: Any, what: str, limit: int = MAX_TEXT) -> str | None:
    return None if value is None else _text(value, what, limit)


def _count(value: Any, what: str, most: int = 1 << 40) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= most:
        raise BadAnswer(f"{what} is not a whole number in range")
    return value


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadAnswer(f"{what} is not a finite number")
    return float(value)


def _list(value: Any, what: str, most: int = MAX_LIST) -> list:
    if not isinstance(value, list) or len(value) > most:
        raise BadAnswer(f"{what} is not a list")
    return value


def _texts(value: Any, what: str) -> tuple[str, ...]:
    return tuple(_text(v, what) for v in _list(value, what))


def _seconds(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or len(value) > 64:
        raise BadAnswer("the seconds are not an object")
    out = {}
    for k, v in value.items():
        t = _number(v, "a time")
        if t < 0:
            raise BadAnswer("a time is negative")
        out[_text(k, "a stage's name", 64)] = t
    return out


def _checks_in(value: Any) -> tuple[Check, ...]:
    out = []
    for c in _list(value, "the checks"):
        if not isinstance(c, dict) or set(c) != {"code", "level", "item", "message", "fixes"}:
            raise BadAnswer("a check is not one")
        if c["level"] not in ("error", "warning", "information"):
            raise BadAnswer("a check's level is not one")
        fixes = _list(c["fixes"], "a check's fixes", 64)
        out.append(
            Check(
                _text(c["code"], "a check's code", 64),
                c["level"],
                _text(c["message"], "a check's message"),
                _text(c["item"], "a check's item", 256),
                tuple(_text(f, "a fix") for f in fixes),
            )
        )
    return tuple(out)


def _coverage_in(value: Any) -> Any:
    from solidseas.drawing.types import Coverage

    if value is None:
        return None
    names = ("features", "features_unclaimed", "faces", "faces_claimed", "area", "area_claimed")
    if not isinstance(value, dict) or set(value) != set(names):
        raise BadAnswer("the coverage is not one")
    counts = {k: _count(value[k], "a coverage count") for k in names[:4]}
    areas = {k: _number(value[k], "a coverage area") for k in names[4:]}
    if any(a < 0 for a in areas.values()):
        raise BadAnswer("a coverage area is negative")
    return Coverage(**counts, **areas)


def _coverage_out(coverage: Any) -> dict[str, Any] | None:
    if coverage is None:
        return None
    return {
        "features": int(coverage.features),
        "features_unclaimed": int(coverage.features_unclaimed),
        "faces": int(coverage.faces),
        "faces_claimed": int(coverage.faces_claimed),
        "area": float(coverage.area),
        "area_claimed": float(coverage.area_claimed),
    }


def _objects(value: Any, what: str) -> tuple[dict, ...]:
    items = _list(value, what)
    if not all(isinstance(v, dict) for v in items):
        raise BadAnswer(f"{what} are not objects")
    return tuple(items)


def _merge_in(value: Any) -> Any:
    """The merge report (``merge.MergeReport``) from its ``to_dict`` object."""
    from solidseas.drawing.merge import MergeReport

    if not isinstance(value, dict):
        raise BadAnswer("the merge report is not an object")
    features = value.get("features")
    if not isinstance(features, dict):
        raise BadAnswer("the merge report's features are not an object")
    for flag in ("model_unchanged", "geometry_unchanged"):
        if not isinstance(value.get(flag), bool):
            raise BadAnswer("the merge report's flags are not true or false")
    return MergeReport(
        unchanged=_count(value.get("unchanged"), "a merge count"),
        changed=_count(value.get("changed"), "a merge count"),
        new=_count(value.get("new"), "a merge count"),
        dropped=_count(value.get("dropped"), "a merge count"),
        attention=_count(value.get("needs_attention"), "a merge count"),
        forgotten=_count(value.get("forgotten"), "a merge count"),
        model_unchanged=value["model_unchanged"],
        geometry_unchanged=value["geometry_unchanged"],
        features_matched=_count(features.get("matched"), "a merge count"),
        features_resized=_texts(features.get("resized"), "a feature id"),
        features_gone=_texts(features.get("gone"), "a feature id"),
        features_new=_texts(features.get("new"), "a feature id"),
        items=_texts(value.get("items"), "a merge line"),
    )


def progress_in(raw: bytes) -> dict[str, Any] | None:
    """A progress frame's ``{"stage", "step", "of"}``: the name of a stage of the drawing
    pipeline and its place among them; None for a frame that is not one (the answer's
    header). A frame that starts as one but does not hold together raises
    :class:`BadAnswer`."""
    from solidseas import model
    from solidseas.drawing import pipeline

    if not raw.startswith(_PROGRESS_START):
        return None
    if len(raw) > MAX_PROGRESS_BYTES:
        raise BadAnswer("a progress frame is longer than one may be")
    try:
        frame = model.loads(raw, parameter="progress")
    except InvalidArgumentError:
        raise BadAnswer("a progress frame is not strict JSON") from None
    info = frame.get("progress") if isinstance(frame, dict) and set(frame) == {"progress"} else None
    names = [name for name, _path in pipeline.STAGES]
    if (
        not isinstance(info, dict)
        or set(info) != {"stage", "step", "of"}
        or info["stage"] not in names
        or info["of"] != len(names)
        or info["step"] != names.index(info["stage"]) + 1
    ):
        raise BadAnswer("a progress frame is not one")
    return {"stage": info["stage"], "step": info["step"], "of": info["of"]}


def _header(raw: bytes) -> dict[str, Any]:
    """An answer's header, strict JSON and an object with ``ok``."""
    from solidseas import model

    try:
        header = model.loads(raw, parameter="answer")
    except InvalidArgumentError:
        raise BadAnswer("the answer is not strict JSON") from None
    if not isinstance(header, dict) or not isinstance(header.get("ok"), bool):
        raise BadAnswer("the answer is not an object that says whether it is ok")
    return header


def _frame_specs(header: dict, accept: Sequence[str], limits: DrawingLimits) -> list[tuple[str, int, str]]:
    """The frames an ok answer announces: (kind, size, SHA-256), each a kind the request
    may get, once, no larger than a drawing file or an export may be."""
    specs = _list(header.get("frames"), "the frames", len(FRAME_KINDS))
    out, seen = [], set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != {"kind", "bytes", "sha256"}:
            raise BadAnswer("a frame's announcement is not one")
        kind = spec["kind"]
        if kind not in accept or kind in seen:
            raise BadAnswer("a frame is not one this request gets")
        seen.add(kind)
        most = limits.drawing_bytes if kind == "ssdrw" else limits.output_bytes
        size = spec["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= most:
            raise BadAnswer("a frame's size is out of range")
        if not isinstance(spec["sha256"], str) or not _HEX64.fullmatch(spec["sha256"]):
            raise BadAnswer("a frame's hash is not a SHA-256")
        out.append((kind, size, spec["sha256"]))
    return out


# --------------------------------------------------------------------------- the child
def _serve(conn) -> None:
    """The child: say it is ready, then answer each request (one JSON frame) with a
    header and the frames it announces, until the pipe closes. A request that asks for
    progress gets its progress frames before the header (:data:`MAX_PROGRESS`)."""
    global _PROGRESS
    try:
        from solidseas.drawing import pipeline

        pipeline.available()  # the stages imported now, before the first request
        from solidseas import model  # noqa: F401
        from solidseas.drawing import checks, document, edit, merge  # noqa: F401

        conn.send_bytes(json.dumps(READY).encode("utf-8"))
    except (EOFError, OSError):
        return
    while True:
        try:
            raw = conn.recv_bytes(MAX_REQUEST_BYTES)
        except (EOFError, OSError):
            return

        def sink(info: dict, conn=conn) -> None:
            conn.send_bytes(json.dumps({"progress": info}, allow_nan=False).encode("utf-8"))

        _PROGRESS = sink
        try:
            header, frames = _answer(raw)
        finally:
            _PROGRESS = None
        try:
            conn.send_bytes(header)
            for data in frames:
                conn.send_bytes(data)
        except (EOFError, OSError, ValueError, MemoryError):  # the window sees the pipe close
            return
        header = frames = None  # type: ignore[assignment]


def _answer(raw: bytes) -> tuple[bytes, list[bytes]]:
    """One request's answer: the header's bytes and the frames after it."""
    try:
        from solidseas import model

        request = model.loads(raw, parameter="request")
        if not isinstance(request, dict) or request.get("op") not in _HANDLERS:
            raise InvalidArgumentError("the request names no operation", detail={"parameter": "op"})
        t0 = time.perf_counter()
        from solidseas.drawing.assembly import searching

        folder = _path(request, "folder", optional=True)
        # An assembly's parts are looked for in the folder the viewer has open, as 3D Print does.
        with searching([folder] if folder else []):
            result, frames = _HANDLERS[request["op"]](request)
        seconds = result.setdefault("seconds", {})
        seconds["total"] = time.perf_counter() - t0
        specs = [{"kind": k, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for k, b in frames]
        header = {"ok": True, "result": result, "frames": specs}
        data = json.dumps(header, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return data, [b for _k, b in frames]
    except MemoryError:  # past the job object's limit
        return json.dumps({"ok": False, "too_large": True}).encode("utf-8"), []
    except Exception as exc:  # the library's refusal or failure, said as an error object
        try:
            return json.dumps({"ok": False, "error": _error_frame(exc)}, allow_nan=False).encode("utf-8"), []
        except MemoryError:
            return json.dumps({"ok": False, "too_large": True}).encode("utf-8"), []


def _path(request: dict, key: str, *, optional: bool = False) -> str | None:
    value = request.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_PATH or "\x00" in value:
        raise InvalidArgumentError(f"{key} must be a path", detail={"parameter": key})
    return value


def _words_in(request: dict, key: str) -> str | None:
    """An optional line of text a request carries (a revision's description, a name, a
    date), checked as the library checks it when it is used."""
    value = request.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 1000 or "\x00" in value:
        raise InvalidArgumentError(f"{key} must be text", detail={"parameter": key})
    return value


def _drawing(request: dict, limits: DrawingLimits) -> tuple[Any, list[str]]:
    """The drawing a request carries, read as any ``.ssdrw`` is (17.2)."""
    from solidseas.drawing import document

    text = request.get("drawing")
    if not isinstance(text, str):
        raise InvalidArgumentError("the request carries no drawing", detail={"parameter": "drawing"})
    drawing, problems = document.loads(text.encode("utf-8", "surrogatepass"), limits=limits)
    return drawing, list(problems)


def _live_features(drawing: Any) -> Any:
    from solidseas.drawing import edit

    live = edit.live_for(drawing)
    return None if live is None else live.features


def _drawing_answer(
    drawing: Any, checks: Any, coverage: Any, features: Any, warnings: Sequence[Any], limits: DrawingLimits
) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    from solidseas import model
    from solidseas.drawing import document

    data = document.dumps(drawing, limits=limits)
    turned = getattr(features, "turned", None)
    result = {
        "summary": model.drawing_summary_data(drawing),
        "checks": [model.drawing_check_data(c) for c in checks],
        "coverage": _coverage_out(coverage),
        "thread_candidates": model.drawing_thread_candidates(drawing, features),
        "warnings": [model.clean_text(str(w))[:MAX_TEXT] for w in warnings][:MAX_LIST],
        "turned": None if turned is None else model.clean_text(turned.reason)[:MAX_TEXT],
    }
    return result, [("ssdrw", data)]


def _do_probe(request: dict) -> tuple[dict, list]:
    from solidseas import model
    from solidseas.drawing import facegraph
    from solidseas.drawing.source import SOLIDWORKS_ASSEMBLIES, SOLIDWORKS_PARTS, open_source
    from solidseas.errors import ConfigurationNotFoundError, UnsupportedOperationError
    from solidseas.formats.solidworks import open_document

    limits = _limits_in(request.get("limits"))
    part = _path(request, "part")
    configuration = request.get("configuration")
    if configuration is not None and (not isinstance(configuration, str) or len(configuration) > 1024):
        raise InvalidArgumentError("configuration must be a name", detail={"parameter": "configuration"})
    out: dict[str, Any] = {"name": model.clean_text(os.path.basename(part)), "refused": None}
    try:
        if os.path.splitext(part)[1].lower() not in (*SOLIDWORKS_PARTS, *SOLIDWORKS_ASSEMBLIES):
            # a part of another format (STEP, Parasolid, Alibre), which has no
            # configurations; any other file is refused by its extension, opening nothing
            src = open_source(part, configuration=configuration, limits=limits)
            out["configurations"] = []
            out["active_configuration"] = None
        else:
            doc = open_document(part)
            try:
                names = [c.name for c in doc.configurations if isinstance(c.name, str)]
                if configuration is not None and configuration not in names:
                    raise ConfigurationNotFoundError(
                        "the part has no configuration by that name", detail={"parameter": "configuration"}
                    )
                out["configurations"] = names
                out["active_configuration"] = doc.active_configuration
                src = open_source(doc, configuration=configuration, limits=limits)
            finally:
                doc.close()
    except UnsupportedOperationError as exc:  # a drawing, another format, an assembly with nothing to draw
        detail = exc.detail or {}
        out.update(refused=str(exc), refused_code=exc.code, refused_rule=detail.get("rule"))
        return out, []
    out["configuration"] = src.configuration
    asm = src.assembly
    if asm is None:
        out["bodies"] = [
            {"name": b.name, "type": b.type, "faces": b.faces, "selected": b.selected, "hidden": b.hidden}
            for b in src.bodies
        ]
    else:  # its part instances, each with the faces of its bodies
        faces = {b.name: b.faces for b in src.bodies}
        out["bodies"] = [
            {
                "name": i.id,
                "type": "part",
                "faces": sum(faces.get(asm.bodies[k].name, 0) for k in i.bodies),
                "selected": True,
                "hidden": False,
            }
            for i in asm.instances
        ]
        out["assembly"] = {
            "items": len(asm.bom),
            "instances": len(asm.instances),
            "left_out": [model.clean_text(f"{i}: {why}")[:MAX_TEXT] for i, why in asm.left_out][:MAX_LIST],
        }
    u = src.units
    out["units"] = {
        "unit": u.unit,
        "origin": u.origin,
        "stated": u.stated,
        "evidence": None if u.evidence is None else u.evidence.to_dict(),
    }
    warnings = [str(w) for w in src.warnings]
    transmits = [b.transmit for b in src.selected_bodies()]
    counts = dict(facegraph.topology_counts(transmits, ("solid", "sheet")))
    if asm is None:
        box, blends = _extent(transmits)
    else:  # a part's bodies count once, its faces and edges for every instance
        unique = list({id(t): t for t in transmits}.values())
        counts["bodies"] = facegraph.topology_counts(unique, ("solid", "sheet"))["bodies"]
        box = facegraph.placed_box(src.selected_bodies(), lambda t: _extent([t])[0])
        blends = 0  # an assembly's drawing recognises no features
    counts["blends"] = blends
    out["counts"] = counts
    out["size_m"] = None if box is None else [hi - lo for lo, hi in zip(box[0], box[1], strict=True)]
    why = limits.refuse(bodies=counts["bodies"], faces=counts["faces"], edges=counts["edges"])
    if why is not None:
        over = next(n for n in ("bodies", "faces", "edges") if counts[n] > getattr(limits, n))
        out.update(refused=why, refused_code="drawing_too_complex", refused_rule=over)
    elif not transmits and asm is not None:
        out.update(
            refused="the assembly has no part instance to draw",
            refused_code="invalid_argument",
            refused_rule="bodies",
        )
    elif not transmits:
        out.update(
            refused="the part has no solid body to draw",
            refused_code="invalid_argument",
            refused_rule="bodies",
        )
    if blends:
        warnings.append(
            f"{blends} rolling-sphere blend face{'s are' if blends != 1 else ' is'} not recognised as "
            "blends yet: they stay unclaimed, and the model defines them"
        )
    if counts["faces"] > 3000:
        warnings.append(f"a part of {counts['faces']:,} faces can take more than 20 seconds to draw")
    out["warnings"] = [model.clean_text(w)[:MAX_TEXT] for w in warnings][:MAX_LIST]
    return out, []


_PROGRESS: Any = None  # in the child, while a request runs: sends a progress frame


def _reporting_stages(report: Any) -> dict[str, Any]:
    """The drawing pipeline's stages, each saying it starts (``report({"stage", "step",
    "of"})``) before it runs. The last, which the pipeline must run as its own to keep the
    run beside the drawing, is said when the one before it ends."""
    from solidseas.drawing import pipeline

    names = [name for name, _path in pipeline.STAGES]
    out: dict[str, Any] = {}
    for i, (name, path) in enumerate(pipeline.STAGES[:-1]):
        real = pipeline.resolve(name, path)

        def stage(*args: Any, _real: Any = real, _step: int = i + 1, _name: str = name, **kwargs: Any) -> Any:
            report({"stage": _name, "step": _step, "of": len(names)})
            got = _real(*args, **kwargs)
            if _step == len(names) - 1:
                report({"stage": names[-1], "step": len(names), "of": len(names)})
            return got

        out[name] = stage
    return out


def _do_make(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import pipeline

    limits = _limits_in(request.get("limits"))
    part = _path(request, "part")
    options = options_from_json(request.get("options"))
    settings, problems = settings_from_json(request.get("settings"))
    fields = request.get("fields") or {}
    stages = _reporting_stages(_PROGRESS) if request.get("progress") is True and _PROGRESS else None
    run = pipeline.run(part, options=options, fields=fields, settings=settings, limits=limits, stages=stages)
    drawing = run.drawing
    warnings: list[str] = [f"settings: {p}" for p in problems]
    units = getattr(run.source, "units", None)
    unit_follows_part = options.units == "part" and settings.standard.units not in ("in", "mm")
    if unit_follows_part and getattr(units, "origin", None) == "guessed":
        warnings.append(f"the part states no unit of length; {units.unit} was guessed from its sizes")
    warnings += list(drawing.warnings)
    result, frames = _drawing_answer(
        drawing, drawing.checks, drawing.coverage, run.features, warnings, limits
    )
    result["seconds"] = {name: took for name, took in run.seconds}
    return result, frames


def _bind(fn: Any, op: str, args: Any, limits: DrawingLimits) -> tuple[list, dict]:
    """``args`` (a list of positional arguments or an object of keyword arguments) bound
    to ``fn`` after its drawing, the arguments that are not JSON decoded by their name."""
    sig = inspect.signature(fn)
    if args is None:
        args = []
    if isinstance(args, dict) and "limits" in args:
        raise InvalidArgumentError("limits are the worker's", detail={"parameter": "args"})
    try:
        bound = sig.bind(None, *args) if isinstance(args, list) else sig.bind(None, **args)
    except TypeError as exc:
        raise InvalidArgumentError(f"{op}: {exc}", detail={"parameter": "args"}) from None
    except AttributeError:
        raise InvalidArgumentError(
            f"{op}: args are a list or an object", detail={"parameter": "args"}
        ) from None
    for name, value in list(bound.arguments.items())[1:]:
        if name in _DECODERS:
            bound.arguments[name] = _DECODERS[name](value)
    if "limits" in sig.parameters and "limits" not in bound.arguments:
        bound.arguments["limits"] = limits
    return list(bound.args[1:]), dict(bound.kwargs)


def _do_edit(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import edit

    limits = _limits_in(request.get("limits"))
    op = request.get("edit")
    if op not in OPERATIONS:
        raise InvalidArgumentError(f"there is no edit {str(op)[:40]!r}", detail={"parameter": "op"})
    drawing, problems = _drawing(request, limits)
    fn = getattr(edit, op)
    args, kwargs = _bind(fn, op, request.get("args"), limits)
    new, checks = fn(drawing, *args, **kwargs)
    return _drawing_answer(new, checks, new.coverage, _live_features(new), problems, limits)


def _do_candidates(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import edit

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    features = request.get("features")
    if not isinstance(features, list):
        raise InvalidArgumentError("features is a list of feature ids", detail={"parameter": "features"})
    found = edit.candidates(drawing, features)
    return {"candidates": [candidate_to_json(c) for c in found], "warnings": problems}, []


def _do_boms(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import edit

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    return {"boms": edit.boms(drawing), "warnings": problems}, []


def _do_attach(request: dict) -> tuple[dict, list]:
    from solidseas import model
    from solidseas.drawing import edit
    from solidseas.drawing.assembly import same_file

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    part = _path(request, "part", optional=True)
    where = _path(request, "drawing_path", optional=True)
    live = edit.attach(drawing, part, drawing_path=where, limits=limits)
    checks = edit.checks(drawing)
    return {
        "same_file": same_file(drawing.model or {}, live.source),
        "checks": [model.drawing_check_data(c) for c in checks],
        "thread_candidates": model.drawing_thread_candidates(drawing, _live_features(drawing)),
        "warnings": problems,
    }, []


def _do_regenerate(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import edit, merge

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    part = _path(request, "part", optional=True)
    where = _path(request, "drawing_path", optional=True)
    revision = _words_in(request, "revision")
    zones = request.get("zones") or []
    if not isinstance(zones, list) or len(zones) > 200 or not all(isinstance(z, str) for z in zones):
        raise InvalidArgumentError("zones are a list of zone names", detail={"parameter": "zones"})
    merged, report = merge.regenerate(
        drawing,
        part,
        drawing_path=where,
        limits=limits,
        revision=revision,
        revision_zones=tuple(zones),
        drawn_by=_words_in(request, "drawn_by"),
        today=_words_in(request, "today"),
    )
    kept = report.model_unchanged or report.geometry_unchanged
    checks = merged.checks or edit.checks(merged)
    coverage = None if kept else merged.coverage
    result, frames = _drawing_answer(merged, checks, coverage, _live_features(merged), problems, limits)
    result["merge"] = report.to_dict()
    return result, frames


def _do_checks(request: dict) -> tuple[dict, list]:
    from solidseas import model
    from solidseas.drawing import edit

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    at_release = request.get("at_release", False)
    if not isinstance(at_release, bool):
        raise InvalidArgumentError("at_release is true or false", detail={"parameter": "at_release"})
    found = edit.checks(drawing, at_release=at_release)
    return {"checks": [model.drawing_check_data(c) for c in found], "warnings": problems}, []


def _do_release(request: dict) -> tuple[dict, list]:
    from solidseas.drawing import edit

    limits = _limits_in(request.get("limits"))
    drawing, problems = _drawing(request, limits)
    released, checks = edit.release_drawing(drawing, request.get("today"), request.get("accepted"))
    return _drawing_answer(released, checks, released.coverage, _live_features(released), problems, limits)


def _do_export(request: dict) -> tuple[dict, list]:
    import io

    from solidseas import drawing as dwg
    from solidseas.errors import DrawingInvalidError

    limits = _limits_in(request.get("limits"))
    kind = request.get("kind")
    if kind not in EXPORT_KINDS:
        raise InvalidArgumentError("kind is pdf or dxf", detail={"parameter": "kind"})
    drawing, problems = _drawing(request, limits)
    if drawing.sheet is None:
        raise DrawingInvalidError(
            "the drawing's sheet is not one this SolidSeas reads, so it cannot be exported",
            detail={"parameter": "drawing", "rule": "drawing_invalid", "value": "sheet"},
        )
    buf = io.BytesIO()
    if kind == "pdf":
        dwg.write_pdf(drawing, buf, limits=limits, problems=problems)
    else:
        dwg.write_dxf(drawing, buf, limits=limits)
    return {"warnings": problems}, [(kind, buf.getvalue())]


def _do_forget(request: dict) -> tuple[dict, list]:
    from types import SimpleNamespace

    from solidseas.drawing import edit

    ident = request.get("id")
    if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
        raise InvalidArgumentError("id is a drawing's id", detail={"parameter": "id"})
    edit.forget(SimpleNamespace(id=ident))
    return {}, []


_HANDLERS = {
    "probe": _do_probe,
    "make": _do_make,
    "edit": _do_edit,
    "candidates": _do_candidates,
    "boms": _do_boms,
    "attach": _do_attach,
    "regenerate": _do_regenerate,
    "checks": _do_checks,
    "release": _do_release,
    "export": _do_export,
    "forget": _do_forget,
}


def _extent(transmits: Sequence[Any]) -> tuple[Any, int]:
    """The box of the solid and sheet bodies of ``transmits`` from their topology alone
    (no tessellation), and how many of their faces are rolling-sphere blends
    (``BLENDED_EDGE``). The box holds every vertex, the points of circular and
    elliptical edges that lie furthest along each axis, the box of a ring edge and of a
    face without edges (a whole sphere or torus). It is exact for parts bounded by
    planes, cylinders, cones and their edges; a free-form edge, or a sphere, torus or
    free-form face that bulges past its edges (a dome), can leave the box a little
    short there, which is good enough for the size wizard page 1 shows. None when
    there is no point."""
    from solidseas.formats.solidworks.parasolid import BODY_TYPES
    from solidseas.tessellate.surfaces import Geometry
    from solidseas.tessellate.topology import BLENDED_EDGE, EDGE, SURFACE_TYPES, FaceFailed, Topology

    lo, hi = [math.inf] * 3, [-math.inf] * 3

    def take(p: Any) -> None:
        if p is None or len(p) != 3 or not all(math.isfinite(v) for v in p):
            return
        for i in range(3):
            lo[i], hi[i] = min(lo[i], p[i]), max(hi[i], p[i])

    blends = 0
    topos: dict[int, Any] = {}
    for xt in transmits:
        if id(xt) in topos:
            continue
        topo = topos[id(xt)] = Topology(xt)
        geom = Geometry(topo, 1e-4)
        edges_done: set[int] = set()
        for body in topo.bodies():
            code = topo.get(body, "body_type", 0)
            if (BODY_TYPES.get(code) if isinstance(code, int) else None) not in ("solid", "sheet"):
                continue
            try:
                faces = topo.faces(body)
            except FaceFailed:
                continue
            for face in faces:
                try:
                    snode = topo.ref(face, "surface", SURFACE_TYPES)
                    if snode is not None and snode.type == BLENDED_EDGE:
                        blends += 1
                    loops = topo.loops(face)
                    if not loops and snode is not None:
                        ext = getattr(geom.surface(snode), "extent", None)
                        for p in ext() if ext is not None else ():
                            take(p)
                    for lp in loops:
                        for fin in topo.fins(lp):
                            vx = topo.ref(fin, "vertex")
                            take(topo.point_of(vx) if vx is not None else None)
                            edge = topo.ref(fin, "edge", (EDGE,))
                            if edge is not None and edge.index not in edges_done:
                                edges_done.add(edge.index)
                                for p in _edge_extremes(topo, geom, edge):
                                    take(p)
                except (FaceFailed, ArithmeticError, TypeError, ValueError):
                    continue
    if lo[0] == math.inf:
        return None, blends
    return (tuple(lo), tuple(hi)), blends


def _edge_extremes(topo: Any, geom: Any, edge: Any) -> list:
    """The points of a conic edge that lie furthest along each axis (its ends are the
    vertices, taken with the fins), or a ring's box; nothing for other curves."""
    from solidseas.tessellate.curves import Conic, Trimmed
    from solidseas.tessellate.topology import CURVE_TYPES, FaceFailed

    sv, ev = topo.edge_ends(edge)
    node = topo.ref(edge, "curve", CURVE_TYPES)
    reverse = False
    if node is None:  # the curve is on the fins, as the tessellator's edge sampler finds it
        for fin in topo.edge_fins(edge):
            c = topo.ref(fin, "curve", CURVE_TYPES)
            if c is not None:
                node, reverse = c, topo.sense(fin) < 0
                break
    if node is None:
        return []
    try:
        curve = geom.curve(node)
    except FaceFailed:
        return []
    pa = topo.point_of(sv) if sv is not None else None
    pb = topo.point_of(ev) if ev is not None else None
    if reverse:
        pa, pb = pb, pa
    if isinstance(curve, Trimmed) and isinstance(curve.basis, Conic):
        t0, t1 = (curve.t1, curve.t2) if curve.sense > 0 else (curve.t2, curve.t1)
        return [*_conic_extremes(curve.basis, min(t0, t1), abs(t1 - t0)), curve.p1, curve.p2]
    if isinstance(curve, Conic):
        if pa is None or pb is None:
            return list(curve.extent())  # a ring: the whole circle or ellipse
        two_pi = 2.0 * math.pi
        d = curve.sense
        ta, tb = curve.param(pa), curve.param(pb)
        sweep = ((tb - ta) * d) % two_pi
        if pa == pb or sweep <= 1e-12:
            sweep = two_pi
        return _conic_extremes(curve, ta if d > 0 else ta - sweep, sweep)
    return []


def _conic_extremes(c: Any, start: float, sweep: float) -> list:
    """The points of the conic ``c`` between parameters ``start`` and ``start + sweep``
    where a coordinate is largest or smallest."""
    out = []
    two_pi = 2.0 * math.pi
    for i in range(3):
        base = math.atan2(c.b * c.Y[i], c.a * c.X[i])
        for t in (base, base + math.pi):
            if sweep >= two_pi or (t - start) % two_pi <= sweep + 1e-12:
                out.append(c.point(t))
    return out


# --------------------------------------------------------------------------- the window's side
def _physical_memory() -> int | None:
    """The PC's physical memory in bytes, or None when it cannot be read."""
    try:
        if os.name == "nt":  # pragma: no cover - Windows
            import ctypes
            from ctypes import wintypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.ullTotalPhys) or None
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return total if total > 0 else None
    except (OSError, ValueError, AttributeError):
        return None


def memory_limit(limits: DrawingLimits = DEFAULT_LIMITS) -> int:
    """The most memory the drawing process may use (17.1): ``child_memory_mb``, and at
    most half the PC's memory where that is known."""
    limit = int(limits.child_memory_mb) << 20
    total = _physical_memory()
    if total:
        limit = min(limit, total // 2)
    return limit


def time_limit(limits: DrawingLimits = DEFAULT_LIMITS, margin: float = MARGIN_SECONDS) -> float:
    """A request's time limit: a whole drawing's seconds and ``margin``."""
    return float(limits.seconds_total) + float(margin)


def _drawing_text(drawing: Any, limits: DrawingLimits) -> str:
    """The ``.ssdrw`` text a request carries: of the bytes given, of an :class:`Answer`, or
    of a drawing (``document.dumps``)."""
    from solidseas.drawing import document, types
    from solidseas.errors import DrawingInvalidError

    if isinstance(drawing, Answer):
        drawing = drawing.data
    if isinstance(drawing, types.Drawing):
        drawing = document.dumps(drawing, limits=limits)
    if not isinstance(drawing, (bytes, bytearray, memoryview)):
        raise InvalidArgumentError(
            "drawing must be .ssdrw bytes or a Drawing", detail={"parameter": "drawing"}
        )
    data = bytes(drawing)
    if len(data) > limits.drawing_bytes:
        raise limits.exceeded("drawing_bytes", "the drawing is larger than a drawing file holds")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise DrawingInvalidError(
            "the drawing file is not valid UTF-8",
            detail={"parameter": "drawing", "rule": "drawing_invalid", "value": "not_utf8"},
        ) from None


def _part_path(part: Any, parameter: str) -> str:
    try:
        path = os.fspath(part)
    except TypeError:
        raise InvalidArgumentError(f"{parameter} must be a path", detail={"parameter": parameter}) from None
    if not isinstance(path, str) or not path:
        raise InvalidArgumentError(f"{parameter} must be a path", detail={"parameter": parameter})
    return os.path.abspath(path)


def _drawing_id(drawing: Any) -> str:
    from solidseas.drawing import document, types

    if isinstance(drawing, Answer):
        drawing = drawing.drawing
    if isinstance(drawing, (bytes, bytearray, memoryview)):
        drawing, _problems = document.loads(bytes(drawing))
    ident = drawing.id if isinstance(drawing, types.Drawing) else drawing
    if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
        raise InvalidArgumentError("drawing must be a drawing or its id", detail={"parameter": "drawing"})
    return ident


class DrawingWorker:
    """Runs the drawing library in a child process, one request at a time (see the
    module notes).

    Every request method runs in a worker thread and blocks until the answer arrives:
    it returns what the child answered, raises the error the child raised, or raises
    :class:`ProcessStopped`. :meth:`cancel` and :meth:`close` come from the UI thread.
    ``limits`` bound every drawing the child makes and give the time limit (with
    ``margin``) and the memory limit; ``serve`` is the child's function, which tests
    stand in for (a function the child can import)."""

    def __init__(
        self, limits: DrawingLimits = DEFAULT_LIMITS, *, margin: float = MARGIN_SECONDS, serve: Any = None
    ) -> None:
        if not isinstance(limits, DrawingLimits):
            raise InvalidArgumentError("limits must be DrawingLimits", detail={"parameter": "limits"})
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin <= 3600:
            raise InvalidArgumentError("margin is from 0 to 3600 seconds", detail={"parameter": "margin"})
        self.limits = limits
        self.margin = float(margin)
        self.time_limit = time_limit(limits, margin)
        self.memory = memory_limit(limits)
        self._serve = serve or _serve
        self._lock = threading.Lock()  # the state below
        self._one = threading.Lock()  # one request at a time
        self._proc: Any = None
        self._conn: Any = None
        self._job: Any = None
        self._token: object | None = None  # the request in progress
        self._kill_busy = False  # the request in progress was cancelled
        self._expired = False  # the request in progress ran out of time
        self._closed = False
        self.started = 0  # children started
        self.contained = False  # whether the last child is in a job object
        # The folder the viewer has open, where an assembly's parts are looked for too: a
        # path, or a function giving the one open at each request.
        self.folder: str | Callable[[], str | None] | None = None
        _WORKERS.add(self)

    # -- the UI thread -----------------------------------------------------------------
    def cancel(self) -> bool:
        """End the request in progress at once, by ending the child; whether one was in
        progress. The request raises :class:`ProcessStopped` with reason ``cancelled``,
        and the next request starts a new child."""
        with self._lock:
            if self._token is None:
                return False
            self._kill_locked()
            return True

    def close(self) -> None:
        """End the child and wait for it to go; no request starts after this."""
        with self._lock:
            self._closed = True
            if self._token is not None:
                self._kill_locked()  # the requesting thread closes the pipe
                try:
                    if self._proc is not None:
                        self._proc.join(2)
                except (OSError, ValueError, AssertionError):
                    pass
            else:
                self._drop_locked()

    @property
    def running(self) -> bool:
        """Whether a child is running."""
        with self._lock:
            return self._proc is not None and self._proc.is_alive()

    @property
    def busy(self) -> bool:
        """Whether a request is in progress."""
        with self._lock:
            return self._token is not None

    def peak_memory(self) -> int | None:
        """The most memory the current child has used, where a job object measures it."""
        with self._lock:
            return self._job.peak() if self._job is not None else None

    # -- the worker thread: requests ----------------------------------------------------
    def warm(self) -> None:
        """Start the child now, before the first request, so its start-up (its imports
        take a second or so) overlaps something else. A failure is left for the first
        request to report."""
        with self._one:
            with self._lock:
                if self._closed or (self._proc is not None and self._proc.is_alive()):
                    return
                self._drop_locked()
                self._token, self._kill_busy, self._expired = object(), False, False
            try:
                self._launch()
            except (ProcessStopped, EOFError, OSError, BadAnswer):
                with self._lock:
                    self._drop_locked()
            finally:
                with self._lock:
                    self._token = None

    def probe(self, part: Any, configuration: str | None = None) -> Probe:
        """What wizard page 1 needs of ``part`` before anything is made (:class:`Probe`):
        read from the part's file and the topology of its bodies, without tessellating."""
        request = {"op": "probe", "part": _part_path(part, "part"), "configuration": configuration}
        result, _frames, extra = self._request(request, ())
        return _probe_in(result, extra)

    def make(
        self,
        part: Any,
        options: Any = None,
        fields: Any = None,
        settings: Any = None,
        *,
        progress: Callable[[dict], None] | None = None,
    ) -> Answer:
        """``make_drawing`` of ``part`` with ``options`` (``DrawingOptions``; None: the
        defaults), the title ``fields`` (with ``drawn_by``) and Drawing ``settings``
        (``DrawingSettings`` or their ``Drawing.json`` content; None: the defaults): the
        PRELIMINARY drawing, its checks, coverage, thread candidates and seconds per
        stage. The child keeps the run beside the drawing for editing. ``progress``, when
        given, is called in this thread with ``{"stage", "step", "of"}`` as each stage of
        the drawing pipeline starts (:func:`progress_in`)."""
        from solidseas.drawing.types import DrawingOptions

        request = {
            "op": "make",
            "part": _part_path(part, "part"),
            "options": options_to_json(options if options is not None else DrawingOptions()),
            "fields": _jsonable(dict(fields or {}), "fields"),
            "settings": settings_to_json(settings),
        }
        if progress is not None:
            request["progress"] = True
        return self._drawing_request(request, progress=progress)

    def edit(self, drawing: Any, op: str, args: Any = ()) -> Answer:
        """One operation of ``drawing.edit`` by name (:data:`OPERATIONS`) on ``drawing``
        (its ``.ssdrw`` bytes, a ``Drawing`` or an :class:`Answer`), with ``args`` after
        the drawing: a list of positional arguments, or a mapping of keyword arguments.
        Returns the new drawing and its checks. A child that does not have the drawing's
        model (it was started again) raises ``ModelNotFoundError``: :meth:`attach` the
        model, then ask again."""
        if op not in OPERATIONS:
            raise InvalidArgumentError(f"there is no edit {str(op)[:40]!r}", detail={"parameter": "op"})
        if isinstance(args, Mapping):
            encoded: Any = _jsonable(dict(args), "args")
        elif isinstance(args, (list, tuple)):
            encoded = _jsonable(list(args), "args")
        else:
            raise InvalidArgumentError("args are a list or a mapping", detail={"parameter": "args"})
        request = {"op": "edit", "edit": op, "drawing": _drawing_text(drawing, self.limits), "args": encoded}
        return self._drawing_request(request)

    def candidates(self, drawing: Any, features: Sequence[str]) -> tuple[Any, ...]:
        """Add Dimension's candidates for one or two picked features
        (``edit.candidates``), as ``edit.Candidate`` objects :meth:`edit` takes back with
        ``add``."""
        if isinstance(features, str) or not isinstance(features, Sequence):
            raise InvalidArgumentError("features is a list of feature ids", detail={"parameter": "features"})
        request = {
            "op": "candidates",
            "drawing": _drawing_text(drawing, self.limits),
            "features": _jsonable(list(features), "features"),
        }
        result, _frames, _extra = self._request(request, ())

        def decode() -> tuple[Any, ...]:
            out = []
            for item in _list(result.get("candidates"), "the candidates", 10_000):
                try:
                    out.append(candidate_from_json(item))
                except InvalidArgumentError as exc:
                    raise BadAnswer(str(exc)) from None
            return tuple(out)

        return self._checked(decode)

    def boms(self, drawing: Any) -> dict[str, Any]:
        """The bills of materials of an assembly drawing's model, one per type, as ``bom``
        JSON (``edit.boms``): what the BOM editor shows for its parts list."""
        request = {"op": "boms", "drawing": _drawing_text(drawing, self.limits)}
        result, _frames, _extra = self._request(request, ())

        def decode() -> dict[str, Any]:
            got = result.get("boms")
            if not isinstance(got, dict) or not all(isinstance(v, dict) for v in got.values()):
                raise BadAnswer("the bills of materials are not objects")
            return got

        return self._checked(decode)

    def attach(self, drawing: Any, part: Any = None, drawing_path: Any = None) -> Attached:
        """Open the model of ``drawing`` in the child for editing (``edit.attach``):
        ``part``, else the model found from ``drawing_path`` (13.6). A model whose file
        and geometry both differ is refused (rule ``model_changed``): Update from Model
        takes it."""
        request = {
            "op": "attach",
            "drawing": _drawing_text(drawing, self.limits),
            "part": None if part is None else _part_path(part, "part"),
            "drawing_path": None if drawing_path is None else _part_path(drawing_path, "drawing_path"),
        }
        result, _frames, extra = self._request(request, ())

        def decode() -> Attached:
            if not isinstance(result.get("same_file"), bool):
                raise BadAnswer("same_file is not true or false")
            return Attached(
                result["same_file"],
                _checks_in(result.get("checks")),
                _objects(result.get("thread_candidates"), "the thread candidates"),
                {**_seconds(result.get("seconds", {})), **extra},
                _texts(result.get("warnings", []), "a warning"),
            )

        return self._checked(decode)

    def regenerate(
        self,
        drawing: Any,
        part: Any = None,
        drawing_path: Any = None,
        *,
        revision: str | None = None,
        zones: Any = (),
        drawn_by: str | None = None,
        today: Any = None,
    ) -> Answer:
        """Update from Model (``drawing.regenerate``, 13.5): the merged drawing, its
        checks and the merge report (``Answer.merge``). The model is ``part``, else the
        one found from ``drawing_path``. With ``revision`` a RELEASED drawing's next
        revision is started first (its description, ``zones``, ``drawn_by`` and
        ``today``), so a released drawing whose model changed is revised in one step."""
        request = {
            "op": "regenerate",
            "drawing": _drawing_text(drawing, self.limits),
            "part": None if part is None else _part_path(part, "part"),
            "drawing_path": None if drawing_path is None else _part_path(drawing_path, "drawing_path"),
            "revision": revision,
            "zones": list(zones),
            "drawn_by": drawn_by,
            "today": None if today is None else str(today),
        }
        return self._drawing_request(request, merge=True)

    def checks(self, drawing: Any, at_release: bool = False) -> tuple[Check, ...]:
        """The checks of ``drawing`` as it is (``edit.checks``): with its model when the
        child has it, else those the file answers; ``at_release`` the release-time
        levels."""
        request = {
            "op": "checks",
            "drawing": _drawing_text(drawing, self.limits),
            "at_release": bool(at_release),
        }
        result, _frames, _extra = self._request(request, ())
        return self._checked(lambda: _checks_in(result.get("checks")))

    def release(self, drawing: Any, accepted: Mapping[str, str] | None = None, today: Any = None) -> Answer:
        """Release (``edit.release_drawing``, 13.2) with the items ``accepted`` with typed
        reasons: the RELEASED drawing, or ``ReleaseRefusedError`` listing every reason.
        The window then writes the released PDF and DXF (:meth:`export`)."""
        request = {
            "op": "release",
            "drawing": _drawing_text(drawing, self.limits),
            "accepted": _jsonable(None if accepted is None else dict(accepted), "accepted"),
            "today": _jsonable(today, "today"),
        }
        return self._drawing_request(request)

    def export(self, drawing: Any, kind: str) -> Exported:
        """The PDF or DXF (``kind``) of the drawing's sheet, as bytes from the writers."""
        if kind not in EXPORT_KINDS:
            raise InvalidArgumentError("kind is pdf or dxf", detail={"parameter": "kind"})
        request = {"op": "export", "drawing": _drawing_text(drawing, self.limits), "kind": kind}
        result, frames, extra = self._request(request, (kind,))

        def decode() -> Exported:
            data = frames.get(kind)
            if data is None:
                raise BadAnswer("the export did not come")
            if kind == "pdf" and not data.startswith(b"%PDF-"):
                raise BadAnswer("the PDF is not one")
            if kind == "dxf" and not data.startswith(b"999"):
                raise BadAnswer("the DXF does not say SolidSeas wrote it")
            return Exported(
                kind,
                data,
                {**_seconds(result.get("seconds", {})), **extra},
                _texts(result.get("warnings", []), "a warning"),
            )

        return self._checked(decode)

    def forget(self, drawing: Any) -> None:
        """Let the child drop the run kept beside ``drawing`` (a drawing, its bytes or
        its id), as the editor does on closing it."""
        self._request({"op": "forget", "id": _drawing_id(drawing)}, ())

    # -- the worker thread: the exchange -------------------------------------------------
    def _drawing_request(
        self, request: dict, *, merge: bool = False, progress: Callable[[dict], None] | None = None
    ) -> Answer:
        result, frames, extra = self._request(request, ("ssdrw",), progress)
        return self._checked(lambda: _answer_in(result, frames, extra, self.limits, merge=merge))

    def _checked(self, decode: Any) -> Any:
        """``decode()``, an answer that does not hold together ending the child."""
        try:
            return decode()
        except BadAnswer as exc:
            with self._lock:
                self._drop_locked()
            raise ProcessStopped("bad_answer", f"{REASONS['bad_answer'][1]} ({exc})") from None

    def _request(
        self, request: dict, accept: Sequence[str], progress: Callable[[dict], None] | None = None
    ) -> tuple[dict, dict[str, bytes], dict[str, float]]:
        """Send ``request`` and wait for its answer: the result, the frames by kind, and
        the window's own seconds (``wall``, and ``start`` when a child was started)."""
        request = {**request, "limits": _limits_out(self.limits)}
        folder = self.folder() if callable(self.folder) else self.folder
        if folder:
            request["folder"] = folder
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8", "surrogatepass")
        if len(payload) > MAX_REQUEST_BYTES:
            raise self.limits.exceeded(
                "drawing_bytes", "the request is larger than the drawing process takes"
            )
        t = time.perf_counter()
        with self._one:
            token = object()
            with self._lock:
                if self._closed:
                    raise ProcessStopped("cancelled")
                self._token, self._kill_busy, self._expired = token, False, False
            try:
                result, frames, extra = self._exchange(payload, accept, token, progress)
            finally:
                with self._lock:
                    self._token = None
        extra["wall"] = time.perf_counter() - t
        return result, frames, extra

    def _exchange(
        self,
        payload: bytes,
        accept: Sequence[str],
        token: object,
        progress: Callable[[dict], None] | None = None,
    ) -> tuple[dict, dict, dict]:
        extra: dict[str, float] = {}
        with self._lock:
            alive = self._proc is not None and self._proc.is_alive()
            if not alive:
                self._drop_locked()
        if not alive:
            t = time.perf_counter()
            try:
                self._launch()
            except BadAnswer as exc:
                with self._lock:
                    self._drop_locked()
                raise ProcessStopped("bad_answer", f"{REASONS['bad_answer'][1]} ({exc})") from None
            except (EOFError, OSError) as exc:
                self._stopped(exc)
            extra["start"] = time.perf_counter() - t
        with self._lock:
            if self._kill_busy or self._closed:  # asked to stop before anything was sent
                raise ProcessStopped("cancelled")
            proc, conn = self._proc, self._conn
        timer = threading.Timer(self.time_limit, self._expire, args=(token,))
        timer.daemon = True
        timer.start()
        try:
            conn.send_bytes(payload)
            raw = self._recv(conn, proc, MAX_HEADER_BYTES)
            for _said in range(MAX_PROGRESS):  # a stage's start, said before the answer
                info = progress_in(raw)
                if info is None:
                    break
                if progress is not None:
                    progress(info)
                raw = self._recv(conn, proc, MAX_HEADER_BYTES)
            header = _header(raw)
            frames: dict[str, bytes] = {}
            if header["ok"]:
                if not isinstance(header.get("result"), dict):
                    raise BadAnswer("the answer holds no result")
                for kind, size, sha in _frame_specs(header, accept, self.limits):
                    data = self._recv(conn, proc, size)
                    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
                        raise BadAnswer(f"the {kind} frame is not the one announced")
                    frames[kind] = data
        except BadAnswer as exc:
            with self._lock:
                self._drop_locked()
            raise ProcessStopped("bad_answer", f"{REASONS['bad_answer'][1]} ({exc})") from None
        except (EOFError, OSError) as exc:
            self._stopped(exc)
        finally:
            timer.cancel()
        if not header["ok"]:  # raised here, so an error that is an OSError is not taken for a broken pipe
            if header.get("too_large") is True:
                with self._lock:
                    self._drop_locked()
                raise ProcessStopped("too_large", detail=self._memory_detail())
            self._checked(lambda: _raise_error(header.get("error")))
        return header["result"], frames, extra

    def _stopped(self, exc: BaseException) -> None:
        """Raise :class:`ProcessStopped` for a child that ended or a pipe that broke,
        with the reason: the window's cancel, the time limit, the job object's memory
        limit, or the child's own end."""
        with self._lock:
            peak = self._job.peak() if self._job is not None else None
            if self._expired:
                reason = "timeout"
            elif self._kill_busy or self._closed:
                reason = "cancelled"
            elif peak is not None and peak >= self.memory - (16 << 20):
                reason = "too_large"
            else:
                reason = "stopped"
            self._drop_locked()
        if reason == "timeout":
            raise ProcessStopped(
                "timeout",
                f"The drawing process did not finish within {self.time_limit:g} seconds and was ended.",
                detail={"limit": "seconds_total", "value": int(math.ceil(self.time_limit))},
            ) from None
        if reason == "too_large":
            raise ProcessStopped("too_large", detail=self._memory_detail()) from None
        raise ProcessStopped(reason) from None

    def _memory_detail(self) -> dict[str, Any]:
        return {"limit": "child_memory_mb", "value": self.memory >> 20}

    def _launch(self) -> None:
        """Start a child and wait until it says it is ready (it has taken its end of the
        pipe and imported the library). Raises EOFError when it ends or is ended first."""
        proc, conn, job = _start(self.memory, target=self._serve, name="SolidSeas drawing")
        with self._lock:
            self._proc, self._conn, self._job = proc, conn, job
            self.started += 1
            self.contained = job is not None
            if self._closed:
                self._kill_locked()
                self._drop_locked()
                raise EOFError
        end = time.monotonic() + START_SECONDS
        while not conn.poll(POLL_SECONDS):
            if self._kill_busy or self._closed or not proc.is_alive() or time.monotonic() > end:
                raise EOFError
        try:
            ready = json.loads(conn.recv_bytes(MAX_READY_BYTES))
        except ValueError:
            raise BadAnswer("the drawing process did not say it was ready") from None
        if ready != READY:
            raise BadAnswer("the drawing process did not say it was ready")

    def _recv(self, conn: Any, proc: Any, limit: int) -> bytes:
        """The child's next frame, at most ``limit`` bytes. Raises EOFError once the child
        has ended or the request was ended (cancelled, out of time), and
        :class:`BadAnswer` for a frame longer than ``limit``."""
        while not conn.poll(POLL_SECONDS):
            if self._kill_busy or self._expired or not proc.is_alive():
                raise EOFError
        try:
            return conn.recv_bytes(limit)
        except OSError:
            if proc.is_alive() and not (self._kill_busy or self._expired):
                raise BadAnswer("a frame is longer than it may be") from None
            raise EOFError from None

    def _expire(self, token: object) -> None:
        """The time limit of request ``token`` passed: end the child if it is still at it."""
        with self._lock:
            if self._token is token:
                self._expired = True
                if self._proc is not None:
                    try:
                        self._proc.kill()
                    except (OSError, ValueError):
                        pass

    # -- with the lock held --------------------------------------------------------------
    def _kill_locked(self) -> None:
        self._kill_busy = True
        if self._proc is not None:
            try:
                self._proc.kill()
            except (OSError, ValueError):
                pass

    def _drop_locked(self) -> None:
        """Forget the child: close the pipe, reap it and let go of its job object."""
        proc, conn, job = self._proc, self._conn, self._job
        self._proc = self._conn = self._job = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.kill()
                proc.join(2)
            except (OSError, ValueError, AssertionError):
                pass
        if job is not None:
            job.close()  # ends the child, if anything is left of it


# --------------------------------------------------------------------------- reading results
def _answer_in(
    result: dict, frames: dict[str, bytes], extra: dict[str, float], limits: DrawingLimits, *, merge: bool
) -> Answer:
    """An :class:`Answer` from a drawing request's result and its ``.ssdrw`` frame, the
    drawing read here as any ``.ssdrw`` is (``document.loads``)."""
    from dataclasses import replace

    from solidseas.drawing import document
    from solidseas.drawing.types import Coverage

    data = frames.get("ssdrw")
    if data is None:
        raise BadAnswer("the drawing did not come")
    summary = result.get("summary")
    if not isinstance(summary, dict):
        raise BadAnswer("the drawing's summary is not an object")
    checks = _checks_in(result.get("checks"))
    coverage = _coverage_in(result.get("coverage"))
    candidates = _objects(result.get("thread_candidates"), "the thread candidates")
    warnings = _texts(result.get("warnings", []), "a warning")
    seconds = {**_seconds(result.get("seconds", {})), **extra}
    report = _merge_in(result.get("merge")) if merge else None
    turned = _opt_text(result.get("turned"), "why the part looks turned")
    drawing, problems = document.loads(data, limits=limits)
    drawing = replace(
        drawing,
        checks=checks,
        coverage=coverage if coverage is not None else Coverage(),
        seconds=tuple(seconds.items()),
        warnings=(*problems, *warnings),
    )
    return Answer(data, drawing, summary, checks, coverage, candidates, seconds, warnings, report, turned)


def _probe_in(result: dict, extra: dict[str, float]) -> Probe:
    from solidseas.drawing.numbers import UnitGuess

    name = _text(result.get("name"), "the part's name", 1024)
    seconds = {**_seconds(result.get("seconds", {})), **extra}
    refused = _opt_text(result.get("refused"), "the refusal")
    configurations = _texts(result.get("configurations", []), "a configuration")
    if result.get("units") is None:  # refused before the part was read
        if refused is None:
            raise BadAnswer("a part was neither read nor refused")
        return Probe(
            name,
            configurations=configurations,
            refused=refused,
            refused_code=_opt_text(result.get("refused_code"), "the refusal's code", 64),
            refused_rule=_opt_text(result.get("refused_rule"), "the refusal's rule", 64),
            seconds=seconds,
        )
    bodies = []
    for b in _list(result.get("bodies"), "the bodies", 100_000):
        if not isinstance(b, dict) or set(b) != {"name", "type", "faces", "selected", "hidden"}:
            raise BadAnswer("a body is not one")
        if not isinstance(b["selected"], bool) or not isinstance(b["hidden"], bool):
            raise BadAnswer("a body's flags are not true or false")
        bodies.append(
            Body(
                _text(b["name"], "a body's name", 1024),
                _text(b["type"], "a body's type", 64),
                _count(b["faces"], "a body's faces"),
                b["selected"],
                b["hidden"],
            )
        )
    units = result["units"]
    if not isinstance(units, dict) or set(units) != {"unit", "origin", "stated", "evidence"}:
        raise BadAnswer("the units are not an object")
    if units["unit"] not in ("in", "mm") or units["origin"] not in ("file", "guessed", "user"):
        raise BadAnswer("the unit is not one")
    if units["stated"] not in (None, "in", "mm"):
        raise BadAnswer("the stated unit is not one")
    evidence = None
    if units["evidence"] is not None:
        e = units["evidence"]
        keys = ("unit", "inch", "mm", "inch_only", "mm_only", "sizes", "decided")
        if not isinstance(e, dict) or set(e) != set(keys) or e["unit"] not in ("in", "mm"):
            raise BadAnswer("the unit's evidence is not one")
        if not isinstance(e["decided"], bool):
            raise BadAnswer("the unit's evidence is not one")
        evidence = UnitGuess(e["unit"], *(_count(e[k], "a size count") for k in keys[1:6]), e["decided"])
    size = result.get("size_m")
    if size is not None:
        size = tuple(_number(v, "a size") for v in _list(size, "the size", 3))
        if len(size) != 3 or any(v < 0 for v in size):
            raise BadAnswer("the size is not three lengths")
    counts = result.get("counts")
    if not isinstance(counts, dict) or set(counts) != {"bodies", "faces", "edges", "blends"}:
        raise BadAnswer("the counts are not an object")
    assembly = result.get("assembly")
    if assembly is not None:
        if not isinstance(assembly, dict) or set(assembly) != {"items", "instances", "left_out"}:
            raise BadAnswer("the assembly is not an object")
        assembly = AssemblyProbe(
            _count(assembly["items"], "an assembly's items"),
            _count(assembly["instances"], "an assembly's instances"),
            _texts(assembly["left_out"], "an instance left out"),
        )
    return Probe(
        name,
        configuration=_opt_text(result.get("configuration"), "the configuration", 1024),
        configurations=configurations,
        active_configuration=_opt_text(result.get("active_configuration"), "the active configuration", 1024),
        bodies=tuple(bodies),
        unit=units["unit"],
        unit_origin=units["origin"],
        stated_unit=units["stated"],
        evidence=evidence,
        size_m=size,  # type: ignore[arg-type]
        counts={k: _count(v, "a count") for k, v in counts.items()},
        refused=refused,
        refused_code=_opt_text(result.get("refused_code"), "the refusal's code", 64),
        refused_rule=_opt_text(result.get("refused_rule"), "the refusal's rule", 64),
        warnings=_texts(result.get("warnings", []), "a warning"),
        seconds=seconds,
        assembly=assembly,
    )


__all__ = [
    "EXPORT_KINDS",
    "MARGIN_SECONDS",
    "OPERATIONS",
    "REASONS",
    "Answer",
    "AssemblyProbe",
    "Attached",
    "BadAnswer",
    "Body",
    "Check",
    "DrawingWorker",
    "Exported",
    "Probe",
    "ProcessStopped",
    "candidate_from_json",
    "candidate_to_json",
    "frame_from_json",
    "frame_to_json",
    "memory_limit",
    "options_from_json",
    "options_to_json",
    "settings_from_json",
    "settings_to_json",
    "time_limit",
]
