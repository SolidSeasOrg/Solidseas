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
model, the goal or the document. While the run is open (until Keep or Revert, or until
the process that ran it ends) it holds a lock on ``run.lock`` in its folder.

:func:`clean_old_runs` removes the folders of runs that ended and whose files have not
changed for :data:`KEEP_DAYS` days; the assistant window and the MCP server call it when
they start. It looks only at folders directly in the runs folder that are named like a
run id, never follows a link or a junction, removes only plain files and then the empty
folder that held them, and leaves alone a folder whose lock a run still holds.

:mod:`.run` carries a started run out: the step loop, verification, the journal and
revert.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from solidseas import policy
from solidseas.ai.prompts import SAID, VOCABULARY_VERSION, Plan
from solidseas.ai.usage import data_dir
from solidseas.walk import reparse_link

from .writer import WriterBusyError, WriterHold, take_writer

POLICY_MESSAGE = "Set by your administrator: Automatic mode is turned off on this PC."
CHANGED_MESSAGE = "The part changed since the plan was made."
KEEP_DAYS = 7  # a run's folder stays this long after its last change, once the run ended
KEEP_SECONDS = KEEP_DAYS * 24 * 3600
LOCK_NAME = "run.lock"  # held while a run is open, so no process removes its folder
MAX_CLEAN_ENTRIES = 10_000  # entries of the runs folder looked at, at most, when cleaning
MAX_RUN_FILES = 1_000  # a folder with more files than this is not one a run made, and stays
RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{8}")  # what new_run_id makes


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
    hold: RunHold | None = None

    def release(self) -> None:
        self.writer.release()
        if self.hold is not None:
            self.hold.release()


def runs_dir() -> str:
    return os.path.join(data_dir(), "runs")


# --------------------------------------------------------------------------- open runs
def _lock(fd: int) -> None:
    """Take the lock on ``fd`` now, or raise OSError when someone else holds it."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


_FLAGS = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_open_here: set[str] = set()  # this process's open runs, which stay even when no lock could be taken
_open_here_lock = threading.Lock()


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class RunHold:
    """An open run's claim on its folder: a lock on ``run.lock`` there, which the system
    lets go of when the process ends, and a note in this process. :func:`clean_old_runs`
    never removes a folder while either is there."""

    def __init__(self, folder: str) -> None:
        self.key = _key(folder)
        self._fd: int | None = None
        with _open_here_lock:
            _open_here.add(self.key)
        try:
            fd = os.open(os.path.join(folder, LOCK_NAME), _FLAGS | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            return  # the note in this process still holds it; other processes go by its age
        try:
            _lock(fd)
        except OSError:
            os.close(fd)
            return
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            _unlock(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        with _open_here_lock:
            _open_here.discard(self.key)


def _is_link(st: os.stat_result) -> bool:
    """A symbolic link, a junction or another name-surrogate reparse point."""
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    tag = int(getattr(st, "st_reparse_tag", 0) or 0)
    return stat.S_ISLNK(st.st_mode) or reparse_link(attrs, tag) is not None


def _held(folder: str) -> bool:
    """Whether a run still holds ``folder``: one of this process's, or one anywhere whose
    lock on ``run.lock`` is taken. A lock file that cannot be checked counts as held."""
    with _open_here_lock:
        if _key(folder) in _open_here:
            return True
    try:
        fd = os.open(os.path.join(folder, LOCK_NAME), _FLAGS)
    except FileNotFoundError:
        return False  # a Review mode script's folder, or one from before runs took a lock
    except OSError:
        return True
    try:
        if _is_link(os.fstat(fd)):
            return True
        _lock(fd)
    except OSError:
        return True
    else:
        _unlock(fd)
        return False
    finally:
        os.close(fd)


def _old_files(folder: str, dev: int | None, cutoff: float) -> list[str] | None:
    """The files in ``folder`` when it holds nothing but plain files (no link, junction,
    folder or other drive) and neither it nor any of them changed after ``cutoff``;
    otherwise None."""
    try:
        newest = os.lstat(folder).st_mtime
        names = os.listdir(folder)
    except OSError:
        return None
    if len(names) > MAX_RUN_FILES:
        return None
    files = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            st = os.lstat(path)
        except OSError:
            return None
        if _is_link(st) or not stat.S_ISREG(st.st_mode) or (dev is not None and st.st_dev != dev):
            return None
        newest = max(newest, st.st_mtime)
        files.append(path)
    if newest > cutoff:
        return None
    # The safety copies first and the lock last: a copy open in SOLIDWORKS cannot be
    # removed, and the folder then stays whole, journal included, for the next time.
    files.sort(key=lambda p: (not p.lower().endswith(".sldprt"), os.path.basename(p) == LOCK_NAME, p))
    return files


def _remove(folder: str, files: list[str]) -> bool:
    for path in files:
        try:
            os.remove(path)
        except FileNotFoundError:
            continue
        except OSError:
            return False
    try:
        os.rmdir(folder)  # only when empty: anything that appeared meanwhile keeps it
    except OSError:
        return False
    return True


def clean_old_runs(
    root: str | None = None, *, now: float | None = None, keep_seconds: float = KEEP_SECONDS
) -> int:
    """Remove the folders of runs in ``root`` (:func:`runs_dir` by default) that no run
    holds and in which nothing changed for ``keep_seconds``. Only a folder directly in
    ``root``, named like a run id, a plain folder on the same drive whose real path lies
    in ``root``'s, and only when everything in it is a plain file: each file is removed
    by name and then the empty folder. A file that cannot be removed (a safety copy open
    in SOLIDWORKS) leaves its folder for the next time. At most
    :data:`MAX_CLEAN_ENTRIES` entries are looked at. Returns how many folders went."""
    now = time.time() if now is None else now
    cutoff = now - keep_seconds
    root = os.path.abspath(root or runs_dir())
    try:
        real_root = _key(root)
        root_st = os.stat(root)  # the root is configuration, and may itself be a link
        entries = os.scandir(root)
    except OSError:
        return 0
    dev = None if sys.platform == "win32" else root_st.st_dev  # Windows: a mount point is a junction
    removed = 0
    with entries:
        for k, entry in enumerate(entries):
            if k >= MAX_CLEAN_ENTRIES:
                break
            if not RUN_ID.fullmatch(entry.name):
                continue
            folder = os.path.join(root, entry.name)
            try:
                st = os.lstat(folder)
            except OSError:
                continue
            if _is_link(st) or not stat.S_ISDIR(st.st_mode) or (dev is not None and st.st_dev != dev):
                continue
            if os.path.dirname(_key(folder)) != real_root or _held(folder):
                continue
            files = _old_files(folder, dev, cutoff)
            if files is not None and _remove(folder, files):
                removed += 1
    return removed


def clean_old_runs_later(root: str | None = None) -> threading.Thread:
    """:func:`clean_old_runs` on a thread of its own, so a window or a server that starts
    does not wait for it. A failure is not reported: the next start tries again."""

    def work() -> None:
        try:
            clean_old_runs(root)
        except Exception:
            pass

    t = threading.Thread(target=work, daemon=True, name="clean-old-runs")
    t.start()
    return t


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
        hold = None
        try:
            os.makedirs(folder, exist_ok=False)
            hold = RunHold(folder)
            target.write_checkpoint(checkpoint)
            written = os.path.isfile(checkpoint) and os.path.getsize(checkpoint) > 0
        except Exception:
            written = False
        if not written:
            if hold is not None:
                hold.release()
            shutil.rmtree(folder, ignore_errors=True)  # the run folder made a moment ago, and nothing else
            raise RunRefused("checkpoint", "The safety copy could not be written, so the run did not start.")
        return RunStart(run_id, folder, checkpoint, plan, writer, hold=hold)
    except BaseException:
        writer.release()
        raise


__all__ = [
    "CHANGED_MESSAGE",
    "KEEP_DAYS",
    "KEEP_SECONDS",
    "LOCK_NAME",
    "Gate",
    "LiveTarget",
    "RunHold",
    "RunRefused",
    "RunStart",
    "clean_old_runs",
    "clean_old_runs_later",
    "confirmation",
    "runs_dir",
    "start_run",
]
