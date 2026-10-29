"""Automatic runs whose process ended before Keep or Revert (``solidseas_app.assistant.unfinished``):
finding them, what the offer says, and what Revert, Keep and Decide Later do, against the part
held in memory (``automatic_support.WindowLive``). A run is "left open" by releasing its hold
and session without Keep or Revert, as the end of its process would. Nothing here reaches
SOLIDWORKS."""

from __future__ import annotations

import dataclasses
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from automatic_support import DEPTH, FILLET, GOAL, WindowLive, block, left_open
from solidseas_app.assistant.automatic import KEEP_DAYS, LOCK_NAME, RunHold
from solidseas_app.assistant.run import differences, snapshot_of_state, state_of
from solidseas_app.assistant.session import LiveSession
from solidseas_app.assistant.unfinished import find_unfinished
from solidseas_app.assistant.writer import BUSY_MESSAGE, take_writer

SRC = Path(__file__).parents[1] / "src"


def journal(folder) -> list[dict]:
    with open(os.path.join(folder, "journal.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def files(folder) -> dict[str, tuple[bytes | int, float]]:
    out = {}
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        st = os.stat(path)
        if name == LOCK_NAME:  # Windows refuses reads of the range a holder has locked: its size
            out[name] = (st.st_size, st.st_mtime)
            continue
        with open(path, "rb") as f:
            out[name] = (f.read(), st.st_mtime)
    return out


def test_a_run_left_open_is_found_and_says_what_it_was(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET, DEPTH)
    [offer] = find_unfinished(str(tmp_path))
    try:
        assert offer.run_id == run.start.run_id and offer.checkpoint == run.start.checkpoint
        text = offer.describe()
        assert text.startswith("SolidSeas closed before you chose Keep or Revert for this Automatic run")
        assert "Part: block.SLDPRT" in text and f"Goal: {GOAL}" in text
        assert "  1. fillet: edges E1, E2, E3, E4 " in text and "[done and checked]" in text
        assert "How far it got: 2 of 2 steps done and checked." in text
        assert "The run ended: All 2 steps were carried out and checked." in text
        assert f"Safety copy, the part as it was before the run: {run.start.checkpoint}" in text
        assert "Revert takes the 2 steps off the part in SOLIDWORKS, newest first" in text
        removed = time.strftime("%Y-%m-%d", time.localtime(offer.last_change + KEEP_DAYS * 86400))
        assert f"{KEEP_DAYS} days after its last change: on {removed}." in text
        assert live.calls == []  # finding and describing it reached nothing
    finally:
        offer.release()


def test_kept_and_reverted_runs_and_other_folders_are_not_offered(tmp_path):
    live = WindowLive(block())
    kept = left_open(tmp_path, live, FILLET)
    kept.keep()
    reverted = left_open(tmp_path, live, DEPTH)
    reverted.revert()
    script = tmp_path / "20261001-120000-0000beef"  # a Review mode script's: a safety copy only
    script.mkdir()
    (script / "checkpoint-20261001-120000-0000beef.sldprt").write_bytes(b"copy")
    assert find_unfinished(str(tmp_path)) == []
    assert find_unfinished(str(tmp_path / "missing")) == []


def test_revert_takes_the_steps_off_when_the_part_is_as_the_run_left_it(tmp_path):
    live = WindowLive(block())
    baseline = live.state
    run = left_open(tmp_path, live, FILLET, DEPTH)
    [offer] = find_unfinished(str(tmp_path))
    result = offer.revert(live)
    assert result.done and result.messages == ()
    assert live.ops() == ["set_dimension", "delete"]  # the existing revert path, newest first
    assert live.calls[0][3] == "SolidSeas revert of step 2"
    assert differences(baseline, live.state) == []
    events = [line["event"] for line in journal(run.start.folder)]
    assert events[-3:] == ["step_reverted", "step_reverted", "reverted"]
    take_writer(live.session.pid).release()  # the session was given back
    assert find_unfinished(str(tmp_path)) == []  # closed, and no longer held


def test_a_part_changed_since_the_last_step_refuses_revert_and_stays_open(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET, DEPTH)
    live.state = dataclasses.replace(live.state, equations=("D1@Sketch1 = 25",))
    before = files(run.start.folder)
    [offer] = find_unfinished(str(tmp_path))
    result = offer.revert(live)
    assert not result.done
    assert "changed after step 2 (equations), so Revert would not put it back" in result.refused
    assert "Nothing was changed" in result.refused and run.start.checkpoint in result.refused
    assert live.ops() == []  # not one inverse applied
    assert files(run.start.folder) == before  # nothing written: the run is still open
    take_writer(live.session.pid).release()
    offer.release()
    assert [o.run_id for o in find_unfinished(str(tmp_path))] == [run.start.run_id]


def test_revert_refuses_when_the_part_is_not_open_or_the_session_is_busy(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET)
    [offer] = find_unfinished(str(tmp_path))
    try:
        with take_writer(live.session.pid):
            result = offer.revert(live)
        assert result.refused == BUSY_MESSAGE
        live.session = LiveSession(live.session.pid, live.session.version, ())
        result = offer.revert(live)
        assert result.refused.startswith("block.SLDPRT is not open in SOLIDWORKS. Open it")
        assert live.ops() == [] and journal(run.start.folder)[-1]["event"] == "run_ended"
    finally:
        offer.release()


def test_a_step_running_when_the_process_ended_is_said_and_checked(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET, DEPTH)
    lines = journal(run.start.folder)
    cut = [i for i, line in enumerate(lines) if line["event"] == "step_started"][-1] + 1
    with open(os.path.join(run.start.folder, "journal.jsonl"), "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(line) + "\n" for line in lines[:cut]) + '{"event": "step_do')
    [offer] = find_unfinished(str(tmp_path))
    try:
        text = offer.describe()
        assert "[running when SolidSeas closed]" in text and "1 of 2 steps done and checked" in text
        assert "what that step did to the part is not known" in text
        result = offer.revert(live)  # step 2 did change the part: it is not as step 1 left it
        assert "changed after step 1 (dimensions, volume, extents)" in result.refused
        assert live.ops() == []
    finally:
        offer.release()


def test_a_journal_without_the_part_states_cannot_revert(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET)
    lines = [{k: v for k, v in line.items() if k != "state"} for line in journal(run.start.folder)]
    with open(os.path.join(run.start.folder, "journal.jsonl"), "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(line) + "\n" for line in lines))
    [offer] = find_unfinished(str(tmp_path))
    try:
        assert "made by an earlier SolidSeas" in offer.revert(live).refused and live.ops() == []
    finally:
        offer.release()


def test_keep_closes_the_run_and_leaves_the_part_as_it_is(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET, DEPTH)
    after = live.state
    [offer] = find_unfinished(str(tmp_path))
    offer.keep()
    assert live.calls == [] and live.state is after
    last = journal(run.start.folder)[-1]
    assert last["event"] == "kept" and last["after_restart"] is True
    take_writer(live.session.pid).release()  # Keep never took the session
    assert find_unfinished(str(tmp_path)) == []


def test_decide_later_writes_nothing_and_the_run_is_offered_again(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET)
    before = files(run.start.folder)
    [offer] = find_unfinished(str(tmp_path))
    assert find_unfinished(str(tmp_path)) == []  # held by the first offer meanwhile
    offer.release()
    assert files(run.start.folder) == before  # the day it is removed has not moved
    [again] = find_unfinished(str(tmp_path))
    again.release()
    assert again.run_id == offer.run_id and again.last_change == offer.last_change and live.calls == []


def test_a_folder_another_process_holds_is_left_alone(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET)
    before = files(run.start.folder)
    hold = RunHold.claim(run.start.folder)  # a run of this process
    assert hold is not None and find_unfinished(str(tmp_path)) == []
    hold.release()
    code = (
        "import sys\n"
        "from solidseas_app.assistant.automatic import RunHold\n"
        f"h = RunHold.claim({run.start.folder!r})\n"
        "print('held' if h else 'not held', flush=True)\n"
        "sys.stdin.readline()\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
    )
    try:
        assert child.stdout.readline().strip() == b"held"
        assert find_unfinished(str(tmp_path)) == []
        assert files(run.start.folder) == before
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    [offer] = find_unfinished(str(tmp_path))  # that process ended: the run is offered
    offer.release()


def test_the_journaled_state_compares_as_the_part_it_was_taken_from():
    snap = block()
    dims = tuple(
        dataclasses.replace(d, value=math.nan) if d.name == "D2@Sketch1" else d for d in snap.dimensions
    )
    snap = dataclasses.replace(snap, dimensions=dims)
    state = json.loads(json.dumps(state_of(snap), allow_nan=False))  # as the journal keeps it
    assert differences(snapshot_of_state(state), snap) == []
    moved = dataclasses.replace(snap, box_max=(0.02, 0.01, 0.009))
    assert differences(snapshot_of_state(state), moved) == ["extents"]
    assert state_of(None) is None
    with pytest.raises(ValueError):
        snapshot_of_state({"features": "not a list"})


def test_a_run_folder_without_its_lock_file_is_not_offered(tmp_path):
    live = WindowLive(block())
    run = left_open(tmp_path, live, FILLET)
    os.remove(os.path.join(run.start.folder, LOCK_NAME))
    assert find_unfinished(str(tmp_path)) == []
