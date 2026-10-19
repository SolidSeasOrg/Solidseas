"""Automatic mode's run, once :func:`.automatic.start_run` has started it: the step loop,
the check after each step, the journal and revert (``docs/ASSISTANT.md``: "Executing a
step", "Verification", "Checkpoints, journal and revert", "Stop, limits and timeouts").

For each step, in order:

1. **Binding check.** Stop and the run's deadline; then the part: still the active
   document, nothing being edited in it, and its snapshot the same as the one taken after
   the step before (for step 1, the baseline), so that anything the person changed in the
   meantime stops the run. The step's persist references are mapped to the ones its
   entities have now: a step can give an entity a new reference while the old one still
   resolves to it, and the inverse and the check compare with the present snapshot.
2. **The inverse** goes into the journal, flushed and synced, before the step runs: delete
   what the step makes, the dimension's value, the features' suppression, or the
   property's value.
3. **The step**, through the bridge, in an undo entry of its own, "SolidSeas step k: op"
   (not ``set_property``, whose edits are not on the undo list: answer 2), with the part
   locked while it runs.
4. **Verification** (:func:`verify`): what the vocabulary lets the step change, and nothing
   else. A failure, a step past its soft limit, or an undo entry that recorded nothing
   applies the inverse at once and ends the run.
5. **The journal** records the result and what the step made.

:meth:`AutomaticRun.revert` works newest first: before each inverse the part must still be
as that step left it, or revert stops and points at the safety copy; after each inverse the
part is compared with its state before the step. :meth:`AutomaticRun.keep` forgets the
inverses. Either one gives the SOLIDWORKS session back to others.

One worker thread drives a run; :meth:`AutomaticRun.stop` may be called from any other and
takes effect between steps.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from solidseas.ai.context import PartSnapshot
from solidseas.ai.prompts import Angle, Handles, Plan, Profile, Step
from solidseas.swapi.bridge import BridgeRequestError

from .automatic import RunStart
from .live_sessions import bridge_arguments
from .session import LiveDocument, LiveSession

DEFAULT_DEADLINE_S = 15 * 60.0
STEP_SOFT_LIMIT_S = 60.0
LENGTH_TOL = 1e-6  # metres: lengths agree within a micrometre
RELATIVE_TOL = 1e-6  # volume and area within one part in a million
VALUE_TOL = 1e-9  # a dimension's value read back: metres or radians

# The operations that make features: how many, and the types GetTypeName2 gives them. A boss
# that makes a part's first body is "Extrusion" and later bosses and cuts "ICE" (answer 6).
MAKES: dict[str, tuple[int, tuple[frozenset[str], ...]]] = {
    "sketch_extrude_boss": (2, (frozenset({"ProfileFeature"}), frozenset({"Extrusion", "Boss", "ICE"}))),
    "sketch_extrude_cut": (2, (frozenset({"ProfileFeature"}), frozenset({"Cut", "ICE"}))),
    "fillet": (1, (frozenset({"Fillet"}),)),
    "chamfer": (1, (frozenset({"Chamfer"}),)),
}


# --------------------------------------------------------------------------- comparing states
def _same_number(a: Any, b: Any, *, absolute: float, relative: float = 0.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return math.isclose(a, b, rel_tol=relative, abs_tol=absolute)


def _same_point(a: Any, b: Any, tol: float = LENGTH_TOL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


def _volume_tol(snap: PartSnapshot) -> float:
    return max(abs(snap.volume or 0.0) * RELATIVE_TOL, 1e-15)


def _props(snap: PartSnapshot) -> tuple[dict, dict]:
    return dict(snap.custom_properties), {k: dict(v) for k, v in snap.configuration_properties.items()}


def differences(a: PartSnapshot, b: PartSnapshot) -> list[str]:
    """What differs between two snapshots of the part, in words; empty when they hold the
    same state (lengths within a micrometre, volume within one part in a million)."""
    out = []
    if [(f.ref, f.name, f.type, f.suppressed) for f in a.features] != [
        (f.ref, f.name, f.type, f.suppressed) for f in b.features
    ]:
        out.append("the feature tree")
    da, db = {d.ref: d.value for d in a.dimensions}, {d.ref: d.value for d in b.dimensions}
    if da.keys() != db.keys() or any(not _same_number(da[k], db[k], absolute=VALUE_TOL) for k in da):
        out.append("dimensions")
    if sorted((f.ref, f.type) for f in a.faces) != sorted((f.ref, f.type) for f in b.faces):
        out.append("faces")
    if sorted((e.ref, e.type) for e in a.edges) != sorted((e.ref, e.type) for e in b.edges):
        out.append("edges")
    if a.solid_bodies != b.solid_bodies:
        out.append("solid bodies")
    if not _same_number(a.volume, b.volume, absolute=1e-15, relative=RELATIVE_TOL):
        out.append("volume")
    if not (_same_point(a.box_min, b.box_min) and _same_point(a.box_max, b.box_max)):
        out.append("extents")
    if a.configurations != b.configurations or a.active_configuration != b.active_configuration:
        out.append("configurations")
    if _props(a) != _props(b):
        out.append("custom properties")
    if a.material != b.material:
        out.append("material")
    if a.equations != b.equations:
        out.append("equations")
    return out


# --------------------------------------------------------------------------- what a step may change
def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _frame(snap: PartSnapshot, ref: str) -> tuple[Any, Any, Any] | None:
    """The sketch frame the snapshot gave a plane or planar face: origin, x, normal."""
    for p in snap.planes:
        if p.ref == ref and p.sketch_x is not None:
            return p.origin, p.sketch_x, p.normal
    for f in snap.faces:
        if f.ref == ref and None not in (f.point, f.sketch_x, f.normal):
            return f.point, f.sketch_x, f.normal
    return None


def boss_box(step: Step, before: PartSnapshot) -> tuple[tuple, tuple] | None:
    """The box a boss step's profile, extruded by its depth, can fill, in the model's
    coordinates; None when the plane's frame is not in the snapshot."""
    frame = _frame(before, step.args["plane"].targets[0].ref)
    if frame is None:
        return None
    origin, x, normal = frame
    y = _cross(normal, x)
    us, vs = [], []
    profile: Profile = step.args["profile"]
    for s in profile.segments:
        if s.type == "line":
            pts = [s.start, s.end]
        else:  # an arc or a circle: the circle's square holds it
            r = s.radius if s.radius is not None else math.dist(s.center, s.start)
            pts = [(s.center[0] - r, s.center[1] - r), (s.center[0] + r, s.center[1] + r)]
        us += [p[0] for p in pts]
        vs += [p[1] for p in pts]
    depth = step.args["depth"].metres
    ws = (0.0, depth) if step.args["direction"].value == "normal" else (-depth, 0.0)
    corners = [
        tuple(origin[i] + u * x[i] + v * y[i] + w * normal[i] for i in range(3))
        for u in (min(us), max(us))
        for v in (min(vs), max(vs))
        for w in ws
    ]
    return tuple(min(c[i] for c in corners) for i in range(3)), tuple(
        max(c[i] for c in corners) for i in range(3)
    )


def _inside(snap: PartSnapshot, box: tuple[tuple, tuple] | None) -> bool:
    """Whether the part's extents lie within ``box`` (None: the part has no extents)."""
    if snap.box_min is None or snap.box_max is None:
        return True
    if box is None:
        return False
    return all(snap.box_min[i] >= box[0][i] - LENGTH_TOL for i in range(3)) and all(
        snap.box_max[i] <= box[1][i] + LENGTH_TOL for i in range(3)
    )


def _box_of(snap: PartSnapshot) -> tuple[tuple, tuple] | None:
    if snap.box_min is None or snap.box_max is None:
        return None
    return tuple(snap.box_min), tuple(snap.box_max)


def _union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return tuple(map(min, a[0], b[0])), tuple(map(max, a[1], b[1]))


def _wanted_value(step: Step) -> float:
    value = step.args["value"]
    return math.radians(value.degrees) if isinstance(value, Angle) else value.metres


def _property_groups(snap: PartSnapshot, scope: str) -> tuple[Mapping, str | None]:
    if scope == "file":
        return snap.custom_properties, None
    configuration = snap.active_configuration or ""
    return snap.configuration_properties.get(configuration, {}), configuration


def verify(step: Step, before: PartSnapshot, after: PartSnapshot, result: Mapping[str, Any]) -> list[str]:
    """What is wrong with ``after`` as the result of ``step`` on ``before`` (the bridge's
    reply in ``result``): empty when the step changed only what the vocabulary allows."""
    op = step.op
    problems: list[str] = []
    for what, x, y in (
        ("the configurations", before.configurations, after.configurations),
        ("the active configuration", before.active_configuration, after.active_configuration),
        ("the material", before.material, after.material),
        ("the equations", before.equations, after.equations),
    ):
        if x != y:
            problems.append(f"{what} changed")

    # custom properties: only set_property's one property, to its value
    if op == "set_property":
        name, value, scope = (step.args[k].value for k in ("name", "value", "scope"))
        group_before, configuration = _property_groups(before, scope)
        group_after, _ = _property_groups(after, scope)
        changed = {
            k for k in set(group_before) | set(group_after) if group_before.get(k) != group_after.get(k)
        }
        if changed - {name}:
            problems.append("custom properties other than the one named changed")
        if group_after.get(name) != value:
            problems.append(f"the property {name} does not hold the value set")
        rest_before, rest_after = _props(before), _props(after)
        if scope == "file":
            if rest_before[1] != rest_after[1]:
                problems.append("configuration properties changed")
        elif rest_before[0] != rest_after[0] or {
            k: v for k, v in rest_before[1].items() if k != configuration
        } != {k: v for k, v in rest_after[1].items() if k != configuration}:
            problems.append("custom properties outside the active configuration changed")
    elif _props(before) != _props(after):
        problems.append("custom properties changed")

    if after.solid_bodies != before.solid_bodies and not (
        op == "sketch_extrude_boss" and before.solid_bodies == 0 and after.solid_bodies == 1
    ):
        problems.append(f"the part has {after.solid_bodies} solid bodies where it had {before.solid_bodies}")

    old_errors = {(r, c) for r, c, warning in before.whats_wrong if not warning}
    new_errors = [(r, c) for r, c, warning in after.whats_wrong if not warning and (r, c) not in old_errors]
    if new_errors:
        problems.append(f"What's Wrong has {len(new_errors)} new rebuild error(s)")

    # the feature tree
    tree_before = [(f.ref, f.name, f.type) for f in before.features]
    tree_after = [(f.ref, f.name, f.type) for f in after.features]
    if op in MAKES:
        count, kinds = MAKES[op]
        added = after.features[len(before.features) :]
        if tree_after[: len(tree_before)] != tree_before or len(added) != count:
            problems.append(f"the feature tree did not gain exactly {count} new feature(s) at its end")
        elif any(f.type not in kind for f, kind in zip(added, kinds, strict=True)):
            problems.append(
                "the new features are not of the kind the step makes: " + ", ".join(f.type for f in added)
            )
        elif result.get("feature") != added[-1].ref:
            problems.append("the feature the step reported making is not the new one")
    elif [(r, t) for r, _, t in tree_after] != [(r, t) for r, _, t in tree_before]:
        problems.append("the feature tree changed")

    # suppression of the features there before
    was = {f.ref: f.suppressed for f in before.features}
    now = {f.ref: f.suppressed for f in after.features}
    if op in ("suppress", "unsuppress"):
        wanted = op == "suppress"
        for t in step.args["features"].targets:
            if now.get(t.ref) is not wanted:
                problems.append(f"{t.handle} is not {'suppressed' if wanted else 'unsuppressed'}")
    elif any(r in now and now[r] != s for r, s in was.items()):
        problems.append("the suppression of features there before changed")

    # dimensions: the one set_dimension names, in the active configuration; no other
    values_before = {d.ref: d.value for d in before.dimensions}
    values_after = {d.ref: d.value for d in after.dimensions}
    named = step.args["dimension"].targets[0].ref if op == "set_dimension" else None
    if named is not None and not _same_number(
        values_after.get(named), _wanted_value(step), absolute=VALUE_TOL
    ):
        problems.append("the dimension does not hold the value set")
    if op not in ("suppress", "unsuppress"):
        gone = [r for r in values_before if r not in values_after]
        moved = [
            r
            for r, v in values_before.items()
            if r != named and r in values_after and not _same_number(v, values_after[r], absolute=VALUE_TOL)
        ]
        if gone or moved:
            problems.append(f"{len(gone) + len(moved)} other dimension(s) changed")

    # geometry
    grew = after.volume is not None and before.volume is not None
    delta = (after.volume - before.volume) if grew else 0.0
    tol = _volume_tol(before)
    if op == "sketch_extrude_boss":
        if delta < -tol:
            problems.append("the volume decreased")
        elif grew and delta <= tol:
            # a boss inside material already there, or on a sketch that made no region
            problems.append("the volume did not grow: the boss added no material")
        if not _inside(after, _union(_box_of(before), boss_box(step, before))):
            problems.append("the extents grew beyond the profile extruded by its depth")
    elif op == "sketch_extrude_cut":
        if delta > tol:
            problems.append("the volume increased")
        elif grew and delta >= -tol:
            # a cut whose profile misses the part, or that runs the wrong way out of it
            problems.append("the volume did not shrink: the cut removed no material")
        if not _inside(after, _box_of(before)):
            problems.append("the extents grew")
    elif op in ("fillet", "chamfer"):
        size = (step.args["radius"] if op == "fillet" else step.args["distance"]).metres
        planned = {t.ref for t in step.args["edges"].targets}
        length = sum(e.length or 0.0 for e in before.edges if e.ref in planned)
        if abs(delta) > size * size * length + tol:
            problems.append("the volume changed by more than the size squared times the edges' length")
        if not _inside(after, _box_of(before)):
            problems.append("the extents grew")
        left = planned & {e.ref for e in after.edges}
        if left:
            problems.append(
                f"{len(left)} of the planned edges are still there: the feature was built on others"
            )
    elif op == "set_property":
        if [d for d in differences(before, after) if d != "custom properties"]:
            problems.append("the part's geometry or tree changed")

    if op != "set_property" and result.get("undo_recorded") is not True:
        problems.append("the step's undo entry recorded nothing")
    return problems


def step_refs(step: Step) -> list[str]:
    """The persist references a step names."""
    return [t.ref for v in step.args.values() if isinstance(v, Handles) for t in v.targets]


def with_refs(step: Step, present: Mapping[str, str]) -> Step:
    """``step`` naming each entity by the reference it has now."""
    args = {}
    for name, value in step.args.items():
        if isinstance(value, Handles):
            value = dataclasses.replace(
                value, targets=tuple(dataclasses.replace(t, ref=present[t.ref]) for t in value.targets)
            )
        args[name] = value
    return dataclasses.replace(step, args=args)


def plan_text(plan: Plan) -> str:
    """A plan as the person reads it, in the Plan panel and in a confirmation: each step
    with every argument and where its value came from, then the model's notes."""
    lines = []
    for step in plan.steps:
        args = "; ".join(f"{name} {value.show()} ({value.source})" for name, value in step.args.items())
        lines.append(f"{step.index}. {step.op}: {args}")
        if step.note:
            lines.append(f"   expected: {step.note}")
    if plan.notes:
        lines += ["", f"Notes: {plan.notes}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- inverses
class InverseError(RuntimeError):
    """The inverse of a step cannot be recorded, so the step does not run."""


def inverse_of(step: Step, before: PartSnapshot) -> dict[str, Any]:
    """The inverse of ``step`` on ``before``, recorded before the step runs."""
    op = step.op
    if op in MAKES:
        return {"kind": "delete_made"}
    if op == "set_dimension":
        ref = step.args["dimension"].targets[0].ref
        old = {d.ref: d.value for d in before.dimensions}.get(ref)
        if old is None or not math.isfinite(old):
            raise InverseError("the dimension's present value cannot be read")
        return {"kind": "set_dimension", "dimension": ref, "value": old}
    if op in ("suppress", "unsuppress"):
        states = {f.ref: f.suppressed for f in before.features}
        targets = step.args["features"].targets
        if any(t.ref not in states for t in targets):
            raise InverseError("a feature's suppression cannot be read")
        return {"kind": "suppression", "features": [[t.ref, states[t.ref]] for t in targets]}
    if op == "set_property":
        name, scope = step.args["name"].value, step.args["scope"].value
        group, _ = _property_groups(before, scope)
        return {"kind": "property", "name": name, "scope": scope, "value": group.get(name)}
    raise InverseError(f"{op} has no inverse")


# --------------------------------------------------------------------------- the journal
class Journal:
    """``journal.jsonl`` in the run folder: one line per event, flushed and synced before
    the run goes on."""

    def __init__(self, folder: str) -> None:
        self.path = os.path.join(folder, "journal.jsonl")
        self._lock = threading.Lock()

    def write(self, event: str, **data: Any) -> None:
        line = json.dumps(
            {"time": round(time.time(), 3), "event": event, **data}, ensure_ascii=False, allow_nan=False
        )
        with self._lock, open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


def _shown(step: Step) -> dict[str, Any]:
    out = {}
    for name, value in step.args.items():
        out[name] = {"value": value.show(), "source": value.source}
    return out


# --------------------------------------------------------------------------- starting
class SessionTarget:
    """What :func:`.automatic.start_run` asks about the picked part (its ``LiveTarget``),
    answered through the session object. :attr:`snapshot` keeps the fresh snapshot the
    handles were checked against: the run's baseline."""

    def __init__(self, live: Any, session: LiveSession, document: LiveDocument) -> None:
        self.live = live
        self.session = session
        self.document = document
        self.sw_pid = session.pid
        self.snapshot: PartSnapshot | None = None

    def document_kind(self) -> str:
        kind = self.live.document_info(self.session, self.document).get("type")
        return kind if isinstance(kind, str) else self.document.kind

    def document_problem(self) -> str | None:
        info = self.live.document_info(self.session, self.document)
        if not info.get("active"):
            return f"{self.document.title} is not the active document in SOLIDWORKS: bring it to the front."
        if info.get("editing_sketch"):
            return "A sketch is open for editing in the part: close it first."
        snap = self.live.snapshot(self.session, self.document)
        errors = [w for w in snap.whats_wrong if not w[2]]
        if errors:
            return f"The part has {len(errors)} rebuild error(s) in What's Wrong: fix them first."
        self.snapshot = snap
        return None

    def unresolved(self, refs: list[str]) -> list[str]:
        snap = self.live.snapshot(self.session, self.document)
        self.snapshot = snap
        seen: dict[str, int] = {}
        for group in (snap.features, snap.dimensions, snap.faces, snap.edges, snap.planes, snap.axes):
            for entity in group:
                seen[entity.ref] = seen.get(entity.ref, 0) + 1
        return [r for r in refs if seen.get(r) != 1]

    def write_checkpoint(self, path: str) -> None:
        self.live.write_checkpoint(self.session, self.document, path)


# --------------------------------------------------------------------------- the run
@dataclass
class StepRecord:
    step: Step
    before: PartSnapshot
    inverse: dict[str, Any]
    after: PartSnapshot | None = None
    made: list[str] = field(default_factory=list)
    status: str = "running"  # running, done, failed, reverted
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunOutcome:
    """How a run ended: ``status`` is done, failed, stopped, changed, limit or interrupted."""

    status: str
    message: str
    steps_done: int


class AutomaticRun:
    """Carries out ``start``'s plan on the part (see the module notes). ``live`` is the
    session object (:class:`.live_sessions.BridgeSessions`); ``baseline`` the snapshot
    the plan's handles were checked against; ``on_event(kind, data)`` hears each step."""

    def __init__(
        self,
        live: Any,
        session: LiveSession,
        document: LiveDocument,
        start: RunStart,
        *,
        baseline: PartSnapshot,
        deadline_s: float = DEFAULT_DEADLINE_S,
        step_soft_limit_s: float = STEP_SOFT_LIMIT_S,
        on_event: Callable[[str, dict], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.live = live
        self.session = session
        self.document = document
        self.start = start
        self.baseline = baseline
        self.step_soft_limit_s = step_soft_limit_s
        self.on_event = on_event
        self.clock = clock
        self.deadline = clock() + deadline_s
        self.journal = Journal(start.folder)
        self.records: list[StepRecord] = []
        self.outcome: RunOutcome | None = None
        self.ended = False
        self._stop = threading.Event()
        self.journal.write(
            "run_started", run_id=start.run_id, checkpoint=start.checkpoint, steps=len(start.plan.steps)
        )
        self.journal.write(
            "plan",
            vocabulary=start.plan.vocabulary,
            notes=start.plan.notes,
            steps=[
                {"index": s.index, "op": s.op, "args": _shown(s), "note": s.note} for s in start.plan.steps
            ],
        )

    # ----------------------------------------------------------------- driving it
    def stop(self) -> None:
        """Stop between steps: the current step finishes and is checked, and no other starts."""
        if not self._stop.is_set():
            self._stop.set()
            self.journal.write("stop_requested")

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def _emit(self, kind: str, **data: Any) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, data)
            except Exception:  # a listener's fault never stops a run
                pass

    def _snapshot(self) -> PartSnapshot:
        return self.live.snapshot(self.session, self.document)

    def _end(self, status: str, message: str) -> RunOutcome:
        done = sum(1 for r in self.records if r.status == "done")
        self.outcome = RunOutcome(status, message, done)
        self.journal.write("run_ended", status=status, message=message, steps_done=done)
        self._emit("ended", status=status, message=message, steps_done=done)
        return self.outcome

    def run(self) -> RunOutcome:
        expected = self.baseline
        steps = self.start.plan.steps
        try:
            for step in steps:
                label = f"step {step.index} ({step.op})"
                if self._stop.is_set():
                    return self._end("stopped", f"Stopped before {label}.")
                if self.clock() > self.deadline:
                    return self._end("limit", f"The run reached its time limit before {label}.")
                info = self.live.document_info(self.session, self.document)
                if not info.get("active"):
                    return self._end(
                        "changed",
                        f"{self.document.title} is no longer the active document; nothing more was done.",
                    )
                if info.get("editing_sketch"):
                    return self._end(
                        "changed", "A sketch is open for editing in the part; nothing more was done."
                    )
                before = self._snapshot()
                changed = differences(expected, before)
                if changed:
                    self.journal.write("changed_outside", before_step=step.index, what=changed)
                    return self._end(
                        "changed",
                        f"The part changed outside the run before {label} ({', '.join(changed)}); "
                        "nothing more was done.",
                    )
                refs = step_refs(step)
                if refs:
                    present = self.live.current_refs(self.session, self.document, refs)
                    gone = [r for r in refs if not present.get(r)]
                    if gone:
                        return self._end(
                            "changed",
                            f"{len(gone)} of the entities {label} names are no longer in the part; "
                            "nothing more was done.",
                        )
                    step = with_refs(step, present)
                try:
                    inverse = inverse_of(step, before)
                except InverseError as exc:
                    return self._end("failed", f"{label.capitalize()} did not run: {exc}.")
                record = StepRecord(step, before, inverse)
                self.records.append(record)
                self.journal.write("step_started", index=step.index, op=step.op, inverse=inverse)
                self._emit("step_started", index=step.index, op=step.op, count=len(steps))
                outcome = self._carry_out(record)
                if outcome is not None:
                    return outcome
                expected = record.after
            return self._end("done", f"All {len(steps)} steps were carried out and checked.")
        except Exception as exc:  # the bridge ended or SOLIDWORKS went away: the state is not known
            self.journal.write("interrupted", error=f"{type(exc).__name__}: {exc}")
            return self._end(
                "interrupted",
                f"The run was interrupted: {exc}. The part may be partly changed; the safety copy is "
                f"{self.start.checkpoint}.",
            )

    def _carry_out(self, record: StepRecord) -> RunOutcome | None:
        step = record.step
        label = f"Step {step.index} ({step.op})"
        undo_name = None if step.op == "set_property" else f"SolidSeas step {step.index}: {step.op}"
        t0 = self.clock()
        try:
            result = self.live.operation(
                self.session, self.document, step.op, bridge_arguments(step), undo_name=undo_name, lock=True
            )
        except BridgeRequestError as exc:
            # SOLIDWORKS or the bridge refused or failed the step: whatever it left is taken off
            # again. A bridge that ended mid-step raises something else, and the run is interrupted.
            record.status = "failed"
            record.problems = [str(exc)]
            after = self._snapshot()
            if step.op in MAKES:
                record.made = [f.ref for f in after.features[len(record.before.features) :]][-1:]
            record.after = after
            self._take_back(record)
            self.journal.write("step_failed", index=step.index, problems=record.problems)
            self._emit("step_failed", index=step.index, problems=record.problems)
            return self._end("failed", f"{label} failed: {exc}")
        elapsed = self.clock() - t0
        after = self._snapshot()
        record.after = after
        if step.op in MAKES and isinstance(result.get("feature"), str):
            record.made = [result["feature"]]
        problems = verify(step, record.before, after, result)
        if elapsed > self.step_soft_limit_s:
            problems.append(
                f"the step took {elapsed:.0f} s, past its limit of {self.step_soft_limit_s:.0f} s"
            )
        if problems:
            record.status = "failed"
            record.problems = problems
            self._take_back(record)
            self.journal.write("step_failed", index=step.index, problems=problems)
            self._emit("step_failed", index=step.index, problems=problems)
            return self._end("failed", f"{label} was taken back: {'; '.join(problems)}.")
        record.status = "done"
        self.journal.write(
            "step_done",
            index=step.index,
            made=record.made,
            undo_recorded=result.get("undo_recorded"),
            volume=after.volume,
        )
        self._emit("step_done", index=step.index, op=step.op)
        return None

    def _take_back(self, record: StepRecord) -> None:
        """Apply a failed step's inverse at once; say whether the part is as it was."""
        try:
            self._apply(record)
            again = self._snapshot()
            left = differences(record.before, again)
            self.journal.write("step_taken_back", index=record.step.index, differs=left)
            if left:
                record.problems.append(
                    "after taking the step back the part still differs in " + ", ".join(left)
                )
        except Exception as exc:
            record.problems.append(f"taking the step back failed: {exc}")
            self.journal.write("take_back_failed", index=record.step.index, error=str(exc))

    def _apply(self, record: StepRecord) -> None:
        inverse = record.inverse
        kind = inverse["kind"]
        name = f"SolidSeas revert of step {record.step.index}"
        if kind == "delete_made":
            for ref in reversed(record.made):
                self.live.delete_feature(self.session, self.document, ref)
        elif kind == "set_dimension":
            self.live.operation(
                self.session,
                self.document,
                "set_dimension",
                {"dimension": inverse["dimension"], "value": inverse["value"]},
                undo_name=name,
                lock=True,
            )
        elif kind == "suppression":
            for ref, was in reversed(inverse["features"]):
                self.live.operation(
                    self.session,
                    self.document,
                    "suppress" if was else "unsuppress",
                    {"features": [ref]},
                    undo_name=name,
                    lock=True,
                )
        elif kind == "property":
            self.live.restore_property(
                self.session, self.document, inverse["name"], inverse["scope"], inverse["value"]
            )

    # ----------------------------------------------------------------- after the run
    def revert(self) -> list[str]:
        """Take every step that was carried out off again, newest first; what went wrong,
        in words (empty when the part is back as it was before the run)."""
        messages: list[str] = []
        try:
            for record in reversed([r for r in self.records if r.status == "done"]):
                now = self._snapshot()
                changed = differences(record.after, now)
                if changed:
                    messages.append(
                        f"The part changed after step {record.step.index} ({', '.join(changed)}), so revert "
                        f"stopped there. The safety copy is {self.start.checkpoint}."
                    )
                    self.journal.write("revert_stopped", at_step=record.step.index, what=changed)
                    break
                self._apply(record)
                again = self._snapshot()
                left = differences(record.before, again)
                record.status = "reverted"
                self.journal.write("step_reverted", index=record.step.index, differs=left)
                self._emit("step_reverted", index=record.step.index)
                if left:
                    messages.append(
                        f"After reverting step {record.step.index} the part differs in {', '.join(left)}."
                    )
        except Exception as exc:
            messages.append(f"Revert was interrupted: {exc}. The safety copy is {self.start.checkpoint}.")
            self.journal.write("revert_interrupted", error=str(exc))
        self._finish("reverted")
        return messages

    def keep(self) -> None:
        """Keep the part as the run left it: the inverses are forgotten."""
        self._finish("kept")

    def _finish(self, how: str) -> None:
        if self.ended:
            return
        self.ended = True
        self.journal.write(how)
        self.start.release()


__all__ = [
    "DEFAULT_DEADLINE_S",
    "MAKES",
    "STEP_SOFT_LIMIT_S",
    "AutomaticRun",
    "InverseError",
    "Journal",
    "RunOutcome",
    "SessionTarget",
    "StepRecord",
    "boss_box",
    "differences",
    "inverse_of",
    "plan_text",
    "step_refs",
    "verify",
    "with_refs",
]
