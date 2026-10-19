"""Automatic mode's entry: :func:`start_run`, the only way an Automatic run starts.

It is one of the two places the machine policy is enforced (the other is the
provider factory, :mod:`solidseas.ai.factory`): it reads the policy fresh and
refuses under ``DisableAutomaticMode`` before anything else. Then it makes the
other checks ``docs/ASSISTANT.md`` ("Starting a run") lists, in that order, and
refuses with a :class:`RunRefused` on the first that fails:

1. the machine policy, read now, allows Automatic mode;
2. the one-writer mutex for the SOLIDWORKS session is free (it takes it);
3. the document is a part;
4. it is active, nothing is being edited in it, and it rebuilds without errors;
5. the plan is a validated plan of the current vocabulary, and it was
   confirmed if :func:`confirmation` says it waits;
6. every handle in the plan still resolves against a fresh snapshot;
7. checkpoint 0 was written and is there and not empty.

What only the bridge can answer (3, 4, 6 and writing checkpoint 0) comes from a
:class:`LiveTarget`. The run folder is
``%LOCALAPPDATA%\\SolidSeas\\runs\\<run id>``; SolidSeas names it and the safety
copy, ``checkpoint-<run id>.sldprt``, and nothing in either name comes from the
model, the goal or the document.

:mod:`.run` carries a started run out: the step loop, verification, the journal and
revert.
"""

from __future__ import annotations

import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from typing import Protocol

from solidseas import policy
from solidseas.ai.prompts import SAID, VOCABULARY_VERSION, Plan
from solidseas.ai.usage import data_dir

from .writer import WriterBusyError, WriterHold, take_writer

POLICY_MESSAGE = "Set by your administrator: Automatic mode is turned off on this PC."
CHANGED_MESSAGE = "The part changed since the plan was made."


class RunRefused(Exception):
    """The run did not start; nothing was changed. ``code`` says which check refused it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Gate:
    """Whether a plan waits for one press of Run, and why."""

    waits: bool
    reasons: tuple[str, ...] = ()


def confirmation(plan: Plan, *, always_confirm: bool = False) -> Gate:
    """The confirmation gate. A plan starts by itself when the only steps that change
    something the person already has are ``set_dimension`` steps whose value they said;
    adding and shaping steps start by themselves. Any ``suppress``, ``unsuppress`` or
    ``set_property`` step, any ``set_dimension`` whose value came from the model, and the
    setting "Always confirm the plan before a run" make it wait."""
    reasons: list[str] = []
    if always_confirm:
        reasons.append("Always confirm the plan before a run is on.")
    for step in plan.steps:
        if step.op in ("suppress", "unsuppress"):
            reasons.append(f"Step {step.index} changes which features are suppressed.")
        elif step.op == "set_property":
            reasons.append(f"Step {step.index} writes the custom property {step.args['name'].value}.")
        elif step.op == "set_dimension" and step.args["value"].source != SAID:
            handle = step.args["dimension"].show()
            reasons.append(
                f"Step {step.index} sets {handle} to {step.args['value'].show()}, a value you did not say."
            )
    return Gate(bool(reasons), tuple(reasons))


class LiveTarget(Protocol):
    """What :func:`start_run` asks the bridge about the bound document."""

    sw_pid: int

    def document_kind(self) -> str:
        """ "part", "assembly" or "drawing"."""
        ...

    def document_problem(self) -> str | None:
        """None when the document is active, nothing is being edited in it and it rebuilds
        without errors; otherwise what is wrong, for the person."""
        ...

    def unresolved(self, refs: list[str]) -> list[str]:
        """The persist references in ``refs`` that no longer resolve to exactly one entity."""
        ...

    def write_checkpoint(self, path: str) -> None:
        """Write the safety copy of the document, unsaved edits included, to ``path``."""
        ...


@dataclass
class RunStart:
    """A run that passed every check: its id, folder, safety copy, plan and the session it
    holds. :meth:`release` gives the session back when the run ends."""

    run_id: str
    folder: str
    checkpoint: str
    plan: Plan
    writer: WriterHold
    started_at: float = field(default_factory=time.time)

    def release(self) -> None:
        self.writer.release()


def runs_dir() -> str:
    return os.path.join(data_dir(), "runs")


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4)


def start_run(
    target: LiveTarget,
    plan: Plan,
    *,
    confirmed: bool = False,
    always_confirm: bool = False,
    runs_folder: str | None = None,
) -> RunStart:
    """Start an Automatic run of ``plan`` on ``target``'s document, or raise
    :class:`RunRefused` (see the module notes for the checks and their order)."""
    if policy.current().automatic_disabled:
        raise RunRefused("policy_refused", POLICY_MESSAGE)
    try:
        writer = take_writer(target.sw_pid)
    except WriterBusyError as exc:
        raise RunRefused("busy", str(exc)) from None
    try:
        if target.document_kind() != "part":
            raise RunRefused(
                "not_a_part",
                "Automatic mode works on one part; assemblies and drawings are refused in this version.",
            )
        problem = target.document_problem()
        if problem:
            raise RunRefused("document_state", problem)
        if not isinstance(plan, Plan) or plan.vocabulary != VOCABULARY_VERSION or not plan.steps:
            raise RunRefused("no_plan", "There is no valid plan to run.")
        gate = confirmation(plan, always_confirm=always_confirm)
        if gate.waits and not confirmed:
            raise RunRefused("unconfirmed", "The plan waits for you to press Run. " + " ".join(gate.reasons))
        if target.unresolved(plan.refs()):
            raise RunRefused("changed", CHANGED_MESSAGE)
        run_id = new_run_id()
        folder = os.path.join(runs_folder or runs_dir(), run_id)
        checkpoint = os.path.join(folder, f"checkpoint-{run_id}.sldprt")
        try:
            os.makedirs(folder, exist_ok=False)
            target.write_checkpoint(checkpoint)
            written = os.path.isfile(checkpoint) and os.path.getsize(checkpoint) > 0
        except Exception:
            written = False
        if not written:
            shutil.rmtree(folder, ignore_errors=True)  # the run folder made a moment ago, and nothing else
            raise RunRefused("checkpoint", "The safety copy could not be written, so the run did not start.")
        return RunStart(run_id, folder, checkpoint, plan, writer)
    except BaseException:
        writer.release()
        raise


__all__ = [
    "CHANGED_MESSAGE",
    "Gate",
    "LiveTarget",
    "RunRefused",
    "RunStart",
    "confirmation",
    "runs_dir",
    "start_run",
]
