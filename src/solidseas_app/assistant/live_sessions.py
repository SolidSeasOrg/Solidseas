"""The assistant's live SOLIDWORKS: :class:`BridgeSessions` implements
:class:`.session.Sessions` over the bridge's live operations (the ``solidseas.swapi``
README, "Live mode"; ``docs/ASSISTANT.md``, "Attaching to a live session").

One bridge process serves a window. It starts on first use, on the worker thread that
needs it, and again if it was ended: a request past its limit ends the bridge, and with
it nothing of the person's, because a bridge in live mode starts no SOLIDWORKS. Every
call holds one lock, so the attach a call needs and the call itself go together.

* :meth:`~BridgeSessions.list`: the SOLIDWORKS processes in this Windows session, each
  with its documents open in a window, without those a SolidSeas bridge started for
  batch work.
* :meth:`~BridgeSessions.snapshot`: the part's structural snapshot, kept for the handles
  of the script that follows.
* :meth:`~BridgeSessions.begin_script`: a run folder, ``<data dir>\\runs\\<run id>``, the
  safety copy in it, and the one undo entry "SolidSeas script".
* :meth:`~BridgeSessions.call`: a script's queries go to the bridge's read-only queries.
  Its vocabulary operations are checked by the validator an Automatic plan's steps go
  through (:func:`solidseas.ai.prompts.parse_plan`, against the handles of the snapshot
  taken when the person picked the part), turned into SI units and persist references
  here, and carried out by the bridge on the active part.

:func:`default_sessions` is what the app offers: this, on Windows with the bridge built;
otherwise :class:`.session.NoSessions` with the reason.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import threading
from collections.abc import Callable
from typing import Any

from solidseas.ai.context import (
    Dimension,
    Edge,
    Face,
    Feature,
    PartSnapshot,
    RefAxis,
    RefPlane,
    build_model_summary,
)
from solidseas.ai.errors import AIError
from solidseas.ai.prompts import (
    OPERATIONS,
    VOCABULARY_VERSION,
    Angle,
    Choice,
    Count,
    Handles,
    Length,
    Profile,
    Step,
    Text,
    parse_plan,
)
from solidseas.swapi.live import QUERIES, LiveError

from .automatic import new_run_id, runs_dir
from .session import LiveDocument, LiveSession, NoSessions, SessionList

LIST_TIMEOUT_S = 60.0
SNAPSHOT_TIMEOUT_S = 300.0
QUERY_TIMEOUT_S = 120.0
CHECKPOINT_TIMEOUT_S = 300.0
OPERATION_TIMEOUT_S = 300.0
# The handles of a script come from the largest summary build_model_summary makes; that
# summary is never sent anywhere.
HANDLE_SUMMARY_CHARS = 200_000

# A script's query, and the bridge operation that answers it in live mode.
QUERY_OPERATIONS = {
    "document_info": "live_document_info",
    "list_features": "live_features",
    "list_dimensions": "live_dimensions",
    "list_properties": "live_properties",
    "mass_properties": "live_mass_properties",
}
assert set(QUERY_OPERATIONS) == set(QUERIES)

NONE_RUNNING = "No SOLIDWORKS is running in your Windows session. Start SOLIDWORKS, then press Refresh."
NOTES = {
    "administrator": (
        "started as administrator, so SolidSeas cannot reach it (SolidSeas never runs elevated "
        "to get around that); start SOLIDWORKS normally"
    ),
    "not_registered": (
        "still starting, or waiting on a dialog such as product activation; press Refresh later"
    ),
    "not_registered_or_administrator": "still starting, or started as administrator; press Refresh later",
    "busy": "busy; press Refresh in a moment",
    "disconnected": "has ended",
}


def version_name(revision: Any) -> str:
    """``ISldWorks::RevisionNumber`` as people say it: "32.1.0" is "2024 SP1.0"."""
    if not isinstance(revision, str) or not revision:
        return "?"
    parts = revision.split(".")
    try:
        major = int(parts[0])
    except ValueError:
        return revision
    service = ".".join(parts[1:3])
    return f"{1992 + major} SP{service}" if service else str(1992 + major)


def _number(x: Any) -> float | None:
    if type(x) in (int, float) and math.isfinite(x):
        return float(x)
    return None


def _vec(v: Any) -> tuple[float, float, float] | None:
    if not isinstance(v, list) or len(v) != 3:
        return None
    out = [_number(c) for c in v]
    if any(c is None for c in out):
        return None
    return (out[0], out[1], out[2])  # type: ignore[return-value]


def _text(x: Any) -> str:
    return x if isinstance(x, str) else ""


def _refs(items: Any) -> tuple[str, ...]:
    return tuple(r for r in items if isinstance(r, str)) if isinstance(items, list) else ()


def _strings(group: Any) -> dict[str, str]:
    if not isinstance(group, dict):
        return {}
    return {str(k): _text(v) for k, v in group.items()}


def snapshot_from(raw: dict) -> PartSnapshot:
    """The :class:`PartSnapshot` of the bridge's ``live_snapshot`` reply; anything malformed
    in it is left out, never guessed."""

    def entries(name: str) -> list[dict]:
        items = raw.get(name)
        return (
            [e for e in items if isinstance(e, dict) and isinstance(e.get("ref"), str)]
            if isinstance(items, list)
            else []
        )

    features = tuple(
        Feature(
            ref=f["ref"],
            name=_text(f.get("name")),
            type=_text(f.get("type")),
            suppressed=f.get("suppressed") is True,
            parents=_refs(f.get("parents")),
        )
        for f in entries("features")
    )
    dimensions = tuple(
        Dimension(
            ref=d["ref"],
            name=_text(d.get("name")),
            feature=_text(d.get("feature")),
            kind=_text(d.get("kind")) or "linear",
            value=_number(d.get("value")) if _number(d.get("value")) is not None else math.nan,
        )
        for d in entries("dimensions")
    )
    edges = tuple(
        Edge(
            ref=e["ref"],
            type=_text(e.get("type")) or "other",
            start=_vec(e.get("start")),
            end=_vec(e.get("end")),
            center=_vec(e.get("center")),
            radius=_number(e.get("radius")),
            length=_number(e.get("length")),
            faces=_refs(e.get("faces")),
        )
        for e in entries("edges")
    )
    faces = tuple(
        Face(
            ref=f["ref"],
            type=_text(f.get("type")) or "other",
            area=_number(f.get("area")),
            normal=_vec(f.get("normal")),
            point=_vec(f.get("point")),
            axis=_vec(f.get("axis")),
            radius=_number(f.get("radius")),
            sketch_x=_vec(f.get("sketch_x")),
        )
        for f in entries("faces")
    )
    planes = tuple(
        RefPlane(
            p["ref"],
            _text(p.get("name")),
            _vec(p.get("origin")),
            _vec(p.get("normal")),
            _vec(p.get("sketch_x")),
        )
        for p in entries("planes")
        if _vec(p.get("origin")) is not None and _vec(p.get("normal")) is not None
    )
    axes = tuple(
        RefAxis(a["ref"], _text(a.get("name")), _vec(a.get("origin")), _vec(a.get("direction")))
        for a in entries("axes")
        if _vec(a.get("origin")) is not None and _vec(a.get("direction")) is not None
    )
    configurations = raw.get("configurations")
    by_configuration = raw.get("configuration_properties")
    bodies = raw.get("solid_bodies")
    wrong = raw.get("whats_wrong")
    whats_wrong = tuple(
        (_text(w.get("feature")), w["code"], w.get("warning") is True)
        for w in (wrong if isinstance(wrong, list) else ())
        if isinstance(w, dict) and type(w.get("code")) is int
    )
    return PartSnapshot(
        length_unit=_text(raw.get("length_unit")) or "other",
        features=features,
        dimensions=dimensions,
        edges=edges,
        faces=faces,
        planes=planes,
        axes=axes,
        solid_bodies=bodies if type(bodies) is int and bodies >= 0 else 0,
        volume=_number(raw.get("volume")),
        box_min=_vec(raw.get("box_min")),
        box_max=_vec(raw.get("box_max")),
        path=_text(raw.get("path")) or None,
        title=_text(raw.get("title")) or None,
        configurations=tuple(c for c in configurations if isinstance(c, str))
        if isinstance(configurations, list)
        else (),
        active_configuration=_text(raw.get("active_configuration")) or None,
        custom_properties=_strings(raw.get("custom_properties")),
        configuration_properties={str(k): _strings(v) for k, v in by_configuration.items()}
        if isinstance(by_configuration, dict)
        else {},
        material=_text(raw.get("material")) or None,
        equations=tuple(e for e in raw.get("equations", ()) if isinstance(e, str))
        if isinstance(raw.get("equations"), list)
        else (),
        whats_wrong=whats_wrong,
    )


def bridge_arguments(step: Step) -> dict[str, Any]:
    """A validated step's arguments as the bridge's ``live_operation`` takes them: persist
    references for handles, metres for lengths, radians for angles, and the profile's
    segments in metres in the plane's frame."""
    spec = {a.name: a for a in OPERATIONS[step.op].args}
    out: dict[str, Any] = {}
    for name, value in step.args.items():
        if isinstance(value, Handles):
            refs = [t.ref for t in value.targets]
            arg = spec[name]
            out[name] = refs[0] if arg.min_items == arg.max_items == 1 else refs
        elif isinstance(value, Length):
            out[name] = value.metres
        elif isinstance(value, Angle):
            out[name] = math.radians(value.degrees)
        elif isinstance(value, Count):
            out[name] = value.value
        elif isinstance(value, (Text, Choice)):
            out[name] = value.value
        elif isinstance(value, Profile):
            segments = []
            for s in value.segments:
                if s.type == "line":
                    segments.append({"type": "line", "start": list(s.start), "end": list(s.end)})
                elif s.type == "arc":
                    segments.append(
                        {
                            "type": "arc",
                            "center": list(s.center),
                            "start": list(s.start),
                            "end": list(s.end),
                            "clockwise": s.clockwise,
                        }
                    )
                else:
                    segments.append({"type": "circle", "center": list(s.center), "radius": s.radius})
            out["segments"] = segments
    return out


def _start_bridge() -> Any:
    from solidseas.swapi.bridge import Bridge

    from .. import extensions

    path, why = extensions.solidworks_bridge()
    if path is None:
        raise RuntimeError(why)
    return Bridge(path)


class BridgeSessions:
    """:class:`.session.Sessions` over the bridge (see the module notes). ``bridge_factory``
    makes a started bridge (tests give a stand-in); ``include_solidseas`` also lists the
    SOLIDWORKS a SolidSeas bridge started for batch work, which tests attach to in place of
    a person's; ``runs_folder`` replaces ``<data dir>\\runs``, though the bridge writes a
    safety copy only there."""

    def __init__(
        self,
        bridge_factory: Callable[[], Any] | None = None,
        *,
        include_solidseas: bool = False,
        pids: tuple[int, ...] | None = None,
        runs_folder: str | None = None,
    ) -> None:
        self._factory = bridge_factory or _start_bridge
        self.include_solidseas = include_solidseas
        self.pids = pids  # only these processes are listed: tests reach no other SOLIDWORKS
        self.runs_folder = runs_folder
        self._lock = threading.RLock()
        self._bridge: Any = None
        self._attached: int | None = None
        self._snapshots: dict[tuple[int, str], PartSnapshot] = {}

    # ----------------------------------------------------------------- the bridge
    def _request(self, op: str, args: dict | None = None, *, timeout: float, pid: int | None = None) -> dict:
        """Send one request, on a bridge attached to ``pid`` first when it is given: a
        bridge started again after the last one was ended attaches before it is asked."""
        with self._lock:
            bridge = self._bridge
            if bridge is None or not getattr(bridge, "alive", True):
                self._bridge = bridge = self._factory()
                self._attached = None
            try:
                if pid is not None and self._attached != pid:
                    bridge.request("live_attach", {"pid": pid}, timeout=LIST_TIMEOUT_S)
                    self._attached = pid
                return bridge.request(op, args or {}, timeout=timeout)
            except Exception:
                if not getattr(bridge, "alive", True):
                    self._attached = None
                raise

    def close(self) -> None:
        """Let go of the session and end the bridge; SOLIDWORKS is left as it is."""
        with self._lock:
            bridge, self._bridge, self._attached = self._bridge, None, None
        if bridge is not None:
            try:
                bridge.close()
            except Exception:  # an ended bridge has nothing more to say
                pass

    # ----------------------------------------------------------------- Sessions
    def list(self) -> SessionList:
        asked = {} if self.pids is None else {"pids": list(self.pids)}
        found = self._request("list_sessions", asked, timeout=LIST_TIMEOUT_S)
        sessions = []
        for s in found.get("sessions", ()):
            if not isinstance(s, dict) or type(s.get("pid")) is not int:
                continue
            if s.get("solidseas") and not self.include_solidseas:
                continue
            documents = tuple(
                LiveDocument(
                    _text(d.get("key")),
                    _text(d.get("title")),
                    _text(d.get("type")),
                    _text(d.get("path")),
                    d.get("active") is True,
                )
                for d in s.get("documents", ())
                if isinstance(d, dict) and d.get("visible") is True and _text(d.get("key"))
            )
            note = ""
            if not s.get("reachable"):
                why = _text(s.get("note"))
                note = NOTES.get(why, f"cannot be reached ({why or 'unknown'})")
            sessions.append(LiveSession(s["pid"], version_name(s.get("revision")), documents, note))
        return SessionList(tuple(sessions), "" if sessions else NONE_RUNNING)

    def snapshot(self, session: LiveSession, document: LiveDocument) -> PartSnapshot:
        raw = self._request(
            "live_snapshot", {"document": document.key}, timeout=SNAPSHOT_TIMEOUT_S, pid=session.pid
        )
        if raw.get("truncated"):
            raise LiveError(
                "it has more faces and edges than the assistant describes to a model", "too_large"
            )
        snap = snapshot_from(raw)
        with self._lock:
            self._snapshots[(session.pid, document.key)] = snap
        return snap

    def begin_script(self, session: LiveSession, document: LiveDocument) -> str:
        if document.kind != "part":
            raise LiveError(
                "a script changes a part; pick a part to run one against SOLIDWORKS", "not_a_part"
            )
        run_id = new_run_id()
        folder = os.path.join(self.runs_folder or runs_dir(), run_id)
        checkpoint = os.path.join(folder, f"checkpoint-{run_id}.sldprt")
        os.makedirs(folder, exist_ok=False)
        try:
            with self._lock:
                self._request(
                    "live_checkpoint",
                    {"document": document.key, "path": checkpoint},
                    timeout=CHECKPOINT_TIMEOUT_S,
                    pid=session.pid,
                )
                self._request(
                    "live_begin_undo", {"document": document.key}, timeout=LIST_TIMEOUT_S, pid=session.pid
                )
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)  # the folder made a moment ago; nothing ran
            raise
        return checkpoint

    def end_script(self, session: LiveSession, document: LiveDocument) -> None:
        self._request("live_end_undo", {"document": document.key}, timeout=LIST_TIMEOUT_S, pid=session.pid)

    def call(self, session: LiveSession, document: LiveDocument, op: str, args: dict) -> Any:
        if op in QUERY_OPERATIONS:
            allowed = set(QUERIES[op])
            unknown = sorted(set(args) - allowed)
            if unknown:
                raise LiveError(f"{op} takes no argument {unknown[0]!r}", "refused")
            request = {"document": document.key}
            request.update({k: v for k, v in args.items() if v is not None})
            return self._request(QUERY_OPERATIONS[op], request, timeout=QUERY_TIMEOUT_S, pid=session.pid)
        if op in OPERATIONS:
            step = self._validated(session, document, op, args)
            request = {"document": document.key, "op": op, **bridge_arguments(step)}
            return self._request("live_operation", request, timeout=OPERATION_TIMEOUT_S, pid=session.pid)
        raise LiveError(f"{str(op)[:64]!r} is not an operation a script may use", "unknown_operation")

    # ----------------------------------------------------------------- what an Automatic run uses
    def document_info(self, session: LiveSession, document: LiveDocument) -> dict:
        return self._request(
            "live_document_info", {"document": document.key}, timeout=QUERY_TIMEOUT_S, pid=session.pid
        )

    def write_checkpoint(self, session: LiveSession, document: LiveDocument, path: str) -> dict:
        return self._request(
            "live_checkpoint",
            {"document": document.key, "path": path},
            timeout=CHECKPOINT_TIMEOUT_S,
            pid=session.pid,
        )

    def operation(
        self,
        session: LiveSession,
        document: LiveDocument,
        op: str,
        args: dict,
        *,
        undo_name: str | None = None,
        lock: bool = False,
    ) -> dict:
        """One operation with bridge arguments (:func:`bridge_arguments`), in its own named
        undo entry when ``undo_name`` is given, with the part locked when ``lock``."""
        request = {"document": document.key, "op": op, **args}
        if undo_name is not None:
            request["undo_name"] = undo_name
        if lock:
            request["lock"] = True
        return self._request("live_operation", request, timeout=OPERATION_TIMEOUT_S, pid=session.pid)

    def current_refs(self, session: LiveSession, document: LiveDocument, refs: list[str]) -> dict[str, Any]:
        """Each persist reference's present one (None when it names nothing now)."""
        reply = self._request(
            "live_current_refs",
            {"document": document.key, "refs": list(refs)},
            timeout=QUERY_TIMEOUT_S,
            pid=session.pid,
        )
        found = reply.get("refs")
        return {r: (found.get(r) if isinstance(found, dict) else None) for r in refs}

    def delete_feature(self, session: LiveSession, document: LiveDocument, feature: str) -> dict:
        return self._request(
            "live_delete_feature",
            {"document": document.key, "feature": feature},
            timeout=OPERATION_TIMEOUT_S,
            pid=session.pid,
        )

    def restore_property(
        self, session: LiveSession, document: LiveDocument, name: str, scope: str, value: str | None
    ) -> dict:
        args = {"document": document.key, "name": name, "scope": scope}
        if value is not None:
            args["value"] = value
        return self._request("live_restore_property", args, timeout=OPERATION_TIMEOUT_S, pid=session.pid)

    def _validated(self, session: LiveSession, document: LiveDocument, op: str, args: dict) -> Step:
        with self._lock:
            snap = self._snapshots.get((session.pid, document.key))
        if snap is None:
            raise LiveError(
                "the part has not been read yet, so its handles name nothing; pick it again", "no_snapshot"
            )
        try:
            summary = build_model_summary(snap, max_chars=HANDLE_SUMMARY_CHARS)
            text = json.dumps({"vocabulary": VOCABULARY_VERSION, "steps": [{"op": op, "args": args}]})
            plan = parse_plan(text, summary, goal="")
        except AIError as exc:
            raise LiveError(str(exc), "refused") from None
        except (TypeError, ValueError) as exc:
            raise LiveError(f"the arguments of {op} are not plain values: {exc}", "refused") from None
        return plan.steps[0]


def default_sessions() -> Any:
    """What the app offers: :class:`BridgeSessions` on Windows with the bridge built, else
    :class:`.session.NoSessions` saying why."""
    if sys.platform != "win32":
        return NoSessions("Attaching to SOLIDWORKS works on Windows, where SOLIDWORKS runs.")
    from .. import extensions

    path, why = extensions.solidworks_bridge()
    if path is None:
        return NoSessions(why)
    return BridgeSessions()


__all__ = [
    "BridgeSessions",
    "NONE_RUNNING",
    "QUERY_OPERATIONS",
    "bridge_arguments",
    "default_sessions",
    "snapshot_from",
    "version_name",
]
