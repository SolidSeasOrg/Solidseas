"""Automatic runs whose process ended before Keep or Revert (``docs/ASSISTANT.md``,
"Crashes and recovery"): finding them, saying what each was, and the person's choice.

:func:`find_unfinished` looks in the runs folder the way :func:`.automatic.clean_old_runs`
does (only folders directly in it, named like a run id, plain folders whose real path lies
in it) and takes each one whose journal has no ``kept`` or ``reverted`` line. It takes
hold of the folder first with :meth:`.automatic.RunHold.claim`: a folder a run still holds,
in this process or another, is left alone, and so is one with no ``run.lock`` to lock
(a Review mode script's, or a run's from before runs took a lock). The hold lasts until the
person chooses, or until :meth:`UnfinishedRun.release`, so no other window offers the same
run and nothing removes its folder meanwhile. Taking hold writes nothing, so the folder is
still removed :data:`.automatic.KEEP_DAYS` days after its last change.

Nothing is done to a run without the person's choice:

* **Revert** (:meth:`UnfinishedRun.revert`) takes the run's steps off the part in
  SOLIDWORKS, newest first, with the inverses its journal recorded, through
  :meth:`.run.AutomaticRun.revert`, the same path as Revert after a run. First the part
  must be open in SOLIDWORKS (the same process and document key, or the same file in
  another SOLIDWORKS) and exactly as the run's last step left it, by the state the journal
  holds; otherwise nothing is done and the run stays open, with the reason. The safety copy
  is never copied over the part and never loaded into it.
* **Keep** (:meth:`UnfinishedRun.keep`) writes ``kept`` to the journal and changes
  nothing else.
* **Later** (:meth:`UnfinishedRun.release`) lets go of the folder and writes nothing: the
  run is offered again on the next start, until its folder is removed.

The MCP server neither looks for these runs nor reports them: a chat cannot see the part
or the person, so the choice is left to the window.
"""

from __future__ import annotations

import json
import math
import ntpath
import os
import stat
import time
from dataclasses import dataclass, field
from typing import Any

from solidseas.ai.prompts import VOCABULARY_VERSION, Plan, Step

from .automatic import KEEP_DAYS, KEEP_SECONDS, LOCK_NAME, RUN_ID, RunHold, _is_link, reopened, runs_dir
from .run import AutomaticRun, Journal, RunOutcome, StepRecord, differences, snapshot_of_state
from .session import LiveDocument, LiveSession
from .writer import WriterBusyError, take_writer

JOURNAL_NAME = "journal.jsonl"
MAX_JOURNAL_BYTES = 64 << 20  # a journal larger than this is not read, and its run not offered
MAX_ENTRIES = 10_000  # entries of the runs folder looked at, at most
MAX_TEXT = 2_000  # characters of one goal, note or message shown
NO_BRIDGE = "Reverting needs SolidSeas' bridge to reach SOLIDWORKS, and there is none here."
ENDS = ("kept", "reverted")  # the journal lines that close a run


@dataclass
class StepSeen:
    """One step of the plan as the journal tells it."""

    index: int
    op: str
    text: str  # as the Plan panel shows it
    status: str = "not run"  # not run, running, done, failed, reverted
    inverse: Any = None
    made: list[str] = field(default_factory=list)
    state: Any = None  # the part after the step, from step_done


@dataclass(frozen=True)
class RevertResult:
    """What Revert did: ``refused`` says why nothing was done (the run stays open);
    otherwise the run is closed as reverted and ``messages`` says what went wrong on the way
    (empty when the part is as it was before the run)."""

    refused: str | None = None
    messages: tuple[str, ...] = ()

    @property
    def done(self) -> bool:
        return self.refused is None


def _clip(text: Any) -> str:
    text = text if isinstance(text, str) else ""
    text = "".join(c for c in text if c.isprintable() or c in "\n\t").strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "..."


def _when(t: float | None) -> str:
    if t is None:
        return "at a time the journal does not say"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _step_line(raw: dict) -> str:
    args = raw.get("args")
    shown = []
    if isinstance(args, dict):
        for name, value in args.items():
            if isinstance(value, dict):
                shown.append(f"{name} {_clip(value.get('value'))} ({_clip(value.get('source'))})")
    return f"{raw.get('index')}. {_clip(raw.get('op'))}: " + "; ".join(shown)


def _inverse_ok(inverse: Any) -> bool:
    """Whether a journaled inverse is one :meth:`.run.AutomaticRun.revert` can apply."""
    if not isinstance(inverse, dict):
        return False
    kind = inverse.get("kind")
    if kind == "delete_made":
        return True
    if kind == "set_dimension":
        value = inverse.get("value")
        return (
            isinstance(inverse.get("dimension"), str) and type(value) in (int, float) and math.isfinite(value)
        )
    if kind == "suppression":
        features = inverse.get("features")
        return isinstance(features, list) and all(
            isinstance(f, list) and len(f) == 2 and isinstance(f[0], str) and isinstance(f[1], bool)
            for f in features
        )
    if kind == "property":
        value = inverse.get("value")
        return (
            isinstance(inverse.get("name"), str)
            and inverse.get("scope") in ("file", "configuration")
            and (value is None or isinstance(value, str))
        )
    return False


@dataclass
class UnfinishedRun:
    """A run whose process ended before Keep or Revert, held by this process until the
    person chooses (see the module notes)."""

    run_id: str
    folder: str
    hold: RunHold | None
    checkpoint: str | None  # the safety copy, when it is still there
    started: float | None
    goal: str
    notes: str
    document: dict
    steps: list[StepSeen]
    baseline: Any  # the part's state before the run, from run_started
    ending: dict | None  # the run_ended line, when the run got that far
    last_change: float
    closed: bool = False

    # ----------------------------------------------------------------- what it was
    @property
    def title(self) -> str:
        return _clip(self.document.get("title")) or "the part"

    @property
    def removed_on(self) -> float:
        """When :func:`.automatic.clean_old_runs` may remove the folder."""
        return self.last_change + KEEP_SECONDS

    @property
    def done(self) -> list[StepSeen]:
        return [s for s in self.steps if s.status == "done"]

    @property
    def running(self) -> StepSeen | None:
        """The step that was running when the process ended, if one was."""
        return next((s for s in self.steps if s.status == "running"), None)

    def describe(self) -> str:
        """The run as the person reads it in the offer, as plain text."""
        lines = [
            "SolidSeas closed before you chose Keep or Revert for this Automatic run, so it is still open.",
            "",
            f"Part: {self.title}",
        ]
        path = _clip(self.document.get("path"))
        if path:
            lines.append(f"File: {path}")
        lines.append(f"Started: {_when(self.started)}")
        if self.goal:
            lines.append(f"Goal: {self.goal}")
        if self.notes:
            lines.append(f"Plan notes: {self.notes}")
        lines.append("")
        lines.append("Plan:" if self.steps else "Plan: the journal does not list its steps.")
        words = {
            "done": "done and checked",
            "failed": "failed and taken back",
            "reverted": "reverted",
            "running": "running when SolidSeas closed",
            "not run": "not run",
        }
        for s in self.steps:
            lines.append(f"  {s.text}  [{words.get(s.status, s.status)}]")
        lines.append("")
        lines.append(self._how_far())
        if self.checkpoint:
            lines.append(f"Safety copy, the part as it was before the run: {self.checkpoint}")
        lines += ["", self._choices()]
        return "\n".join(lines)

    def _how_far(self) -> str:
        done = len(self.done)
        count = f"{done} of {len(self.steps)} step{'s' if len(self.steps) != 1 else ''}"
        text = f"How far it got: {count} done and checked."
        running = self.running
        if running is not None:
            text += (
                f" SolidSeas closed while step {running.index} ({running.op}) was running, so what that "
                "step did to the part is not known."
            )
        elif self.ending is not None:
            message = _clip(self.ending.get("message"))
            if message:
                text += f" The run ended: {message}"
        else:
            text += " SolidSeas closed during the run."
        if any(s.status == "reverted" for s in self.steps):
            text += " A revert had started and did not finish."
        return text

    def _choices(self) -> str:
        done = len(self.done)
        if done:
            revert = (
                f"Revert takes the {done} step{'s' if done != 1 else ''} off the part in SOLIDWORKS, newest "
                "first, only if the part is open and still exactly as the run left it; otherwise it changes "
                "nothing and says why."
            )
        else:
            revert = "No step changed the part, so Revert has nothing to take off; it closes the run."
        return (
            f"{revert} Keep leaves the part as it is and closes the run. Neither one saves the part. "
            f"Decide Later asks again the next time the assistant opens, until SolidSeas removes this "
            f"run's folder, safety copy included, {KEEP_DAYS} days after its last change: on "
            f"{_day(self.removed_on)}."
        )

    # ----------------------------------------------------------------- the choices
    def release(self) -> None:
        """Decide Later: let go of the folder; nothing is written."""
        hold, self.hold = self.hold, None
        if hold is not None:
            hold.release()

    def keep(self) -> None:
        """Keep: the part stays as it is, and the journal says the run was kept."""
        if self.closed:
            return
        try:
            Journal(self.folder).write("kept", after_restart=True)
        finally:
            self.closed = True
            self.release()

    def revert(self, live: Any) -> RevertResult:
        """Revert (see the module notes). ``live`` is the window's session object. Called
        on a worker thread: it waits for SOLIDWORKS."""
        if self.closed:
            return RevertResult("The run is already closed.")
        done = self.done
        if not done and self.running is None:
            Journal(self.folder).write("reverted", after_restart=True)
            self.closed = True
            self.release()
            return RevertResult()
        expected = done[-1].state if done else self.baseline
        if expected is None:
            return RevertResult(
                "This run was made by an earlier SolidSeas, which did not record the part's state after "
                "each step, so SolidSeas cannot check the part before taking steps off. Nothing was changed. "
                + self._way_back()
            )
        if not all(_inverse_ok(s.inverse) for s in done):
            return RevertResult(
                "The run's journal does not hold a step's inverse SolidSeas can apply, so nothing was "
                "changed. " + self._way_back()
            )
        try:
            expected_part = snapshot_of_state(expected)
            before = [snapshot_of_state(self.baseline)] + [snapshot_of_state(s.state) for s in done]
        except ValueError:
            return RevertResult(
                "The part's state in the run's journal cannot be read, so SolidSeas cannot check the part "
                "before taking steps off. Nothing was changed. " + self._way_back()
            )
        if not hasattr(live, "operation"):
            return RevertResult(NO_BRIDGE)
        try:
            found = live.list()
        except Exception as exc:
            return RevertResult(f"SOLIDWORKS could not be listed: {exc}")
        target = self._find(found.sessions)
        if isinstance(target, str):
            return RevertResult(target)
        session, document = target
        try:
            writer = take_writer(session.pid)
        except WriterBusyError as exc:
            return RevertResult(str(exc))
        handed_over = False
        try:
            try:
                now = live.snapshot(session, document)
            except Exception as exc:
                return RevertResult(f"{self.title} could not be read: {exc}")
            changed = differences(expected_part, now)
            if changed:
                last = f"step {done[-1].index}" if done else "the run started"
                return RevertResult(
                    f"{self.title} changed after {last} ({', '.join(changed)}), so Revert would not put it "
                    "back as it was. Nothing was changed. " + self._way_back()
                )
            records = [
                StepRecord(
                    Step(s.index, s.op, {}),
                    before[k],
                    s.inverse,
                    after=before[k + 1],
                    made=[m for m in s.made if isinstance(m, str)],
                    status="done",
                )
                for k, s in enumerate(done)
            ]
            plan = Plan(VOCABULARY_VERSION, tuple(Step(s.index, s.op, {}) for s in self.steps))
            start = reopened(self.run_id, self.folder, self.checkpoint or "", plan, writer, self.hold)
            run = AutomaticRun.recovered(
                live,
                session,
                document,
                start,
                baseline=before[0],
                records=records,
                outcome=RunOutcome("interrupted", "SolidSeas closed before Keep or Revert.", len(done)),
            )
            handed_over = True  # revert gives the session and the folder back when it ends
            self.hold = None
            messages = run.revert()
        finally:
            if not handed_over:
                writer.release()
        self.closed = True
        return RevertResult(None, tuple(messages))

    def _way_back(self) -> str:
        if self.checkpoint:
            return (
                f"The safety copy, {self.checkpoint}, holds the part as it was before the run: open it in "
                "SOLIDWORKS as a separate document, or choose Keep."
            )
        return "Choose Keep to close the run."

    def _find(self, sessions: Any) -> tuple[LiveSession, LiveDocument] | str:
        """The SOLIDWORKS session and document the run worked on, or why there is none."""
        key = self.document.get("key")
        pid = self.document.get("pid")
        path = self.document.get("path")
        if not isinstance(key, str) or not key:
            return "The run's journal does not say which part it worked on, so nothing was changed."

        def same(d: LiveDocument) -> bool:
            return d.kind == "part" and ntpath.normcase(d.key) == ntpath.normcase(key)

        chosen = None
        for s in sessions:
            if s.pid == pid:
                chosen = next(((s, d) for d in s.documents if same(d)), None)
        if chosen is None and isinstance(path, str) and path:
            chosen = next(((s, d) for s in sessions for d in s.documents if same(d)), None)
        if chosen is None:
            if isinstance(path, str) and path:
                return (
                    f"{self.title} is not open in SOLIDWORKS. Open it, then choose Revert again; nothing was "
                    "changed."
                )
            return (
                f"{self.title} was never saved, and it is not open in the SOLIDWORKS it was made in, so the "
                "run's changes went with that window and there is nothing to take off. Choose Keep to close "
                "the run."
            )
        session, document = chosen
        if session.note:
            return (
                f"SOLIDWORKS (process {session.pid}) cannot be reached: {session.note}. Nothing was changed."
            )
        return session, document


# --------------------------------------------------------------------------- finding them
def _read_journal(path: str) -> list[dict] | None:
    """The journal's lines that are JSON objects with an event; None when it is not a
    plain file SolidSeas could have written."""
    try:
        st = os.lstat(path)
        if _is_link(st) or not stat.S_ISREG(st.st_mode) or st.st_size > MAX_JOURNAL_BYTES:
            return None
        with open(path, "rb") as f:
            raw = f.read(MAX_JOURNAL_BYTES + 1)
    except OSError:
        return None
    lines = []
    for line in raw.split(b"\n"):
        try:
            item = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue  # an empty line, or one cut short when the process ended
        if isinstance(item, dict) and isinstance(item.get("event"), str):
            lines.append(item)
    return lines


def _newest_change(folder: str) -> float:
    newest = os.lstat(folder).st_mtime
    for name in os.listdir(folder):
        try:
            newest = max(newest, os.lstat(os.path.join(folder, name)).st_mtime)
        except OSError:
            continue
    return newest


def read_run(folder: str, hold: RunHold | None = None) -> UnfinishedRun | None:
    """The run in ``folder`` when its journal says it ended without Keep or Revert;
    otherwise None. ``hold`` is kept by the result."""
    lines = _read_journal(os.path.join(folder, JOURNAL_NAME))
    if not lines or lines[0]["event"] != "run_started":
        return None
    if any(line["event"] in ENDS for line in lines):
        return None
    run_id = os.path.basename(folder)
    first = lines[0]
    document = first.get("document") if isinstance(first.get("document"), dict) else {}
    started = first.get("time") if type(first.get("time")) in (int, float) else None
    goal, notes, ending = _clip(first.get("goal")), "", None
    steps: dict[int, StepSeen] = {}
    for line in lines:
        event = line["event"]
        index = line.get("index")
        if event == "plan" and isinstance(line.get("steps"), list):
            notes = _clip(line.get("notes"))
            for raw in line["steps"]:
                if isinstance(raw, dict) and type(raw.get("index")) is int:
                    steps[raw["index"]] = StepSeen(raw["index"], _clip(raw.get("op")), _step_line(raw))
        elif type(index) is int and event.startswith("step_"):
            op = _clip(line.get("op"))
            seen = steps.setdefault(index, StepSeen(index, op, f"{index}. {op}"))
            if event == "step_started":
                seen.status, seen.inverse = "running", line.get("inverse")
            elif event == "step_done":
                made = line.get("made")
                seen.status, seen.state = "done", line.get("state")
                seen.made = list(made) if isinstance(made, list) else []
            elif event == "step_failed":
                seen.status = "failed"
            elif event == "step_reverted":
                seen.status = "reverted"
        elif event == "run_ended":
            ending = line
    checkpoint = os.path.join(folder, f"checkpoint-{run_id}.sldprt")
    try:
        last_change = _newest_change(folder)
    except OSError:
        return None
    return UnfinishedRun(
        run_id=run_id,
        folder=folder,
        hold=hold,
        checkpoint=checkpoint if os.path.isfile(checkpoint) else None,
        started=started,
        goal=goal,
        notes=notes,
        document=document,
        steps=[steps[k] for k in sorted(steps)],
        baseline=first.get("state"),
        ending=ending,
        last_change=last_change,
    )


def find_unfinished(root: str | None = None) -> list[UnfinishedRun]:
    """The runs in ``root`` (:func:`.automatic.runs_dir` by default) whose process ended
    before Keep or Revert, oldest first, each held by this process until the person chooses
    or :meth:`UnfinishedRun.release` (see the module notes)."""
    root = os.path.abspath(root or runs_dir())
    try:
        real_root = os.path.normcase(os.path.realpath(root))
        entries = sorted(e.name for e in os.scandir(root))[:MAX_ENTRIES]
    except OSError:
        return []
    found = []
    for name in entries:
        if not RUN_ID.fullmatch(name):
            continue
        folder = os.path.join(root, name)
        try:
            st = os.lstat(folder)
        except OSError:
            continue
        if _is_link(st) or not stat.S_ISDIR(st.st_mode):
            continue
        if os.path.dirname(os.path.normcase(os.path.realpath(folder))) != real_root:
            continue  # a junction, or a folder reached through one
        if not os.path.isfile(os.path.join(folder, JOURNAL_NAME)):
            continue
        if not os.path.lexists(os.path.join(folder, LOCK_NAME)):
            continue
        hold = RunHold.claim(folder)
        if hold is None:
            continue  # a run in this process or another holds it
        try:
            run = read_run(folder, hold)
        except Exception:
            run = None
        if run is None:
            hold.release()
        else:
            found.append(run)
    return found


__all__ = [
    "NO_BRIDGE",
    "RevertResult",
    "StepSeen",
    "UnfinishedRun",
    "find_unfinished",
    "read_run",
]
