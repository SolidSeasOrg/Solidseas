"""Automatic mode's run (``solidseas_app.assistant.run``) against a part held in memory: the
step loop, the check after each step, taking a step back, the journal, Stop and revert.
Nothing here reaches SOLIDWORKS; ``tests/test_swapi_live.py`` runs a plan in SolidSeas'
own SOLIDWORKS, opt-in."""

from __future__ import annotations

import dataclasses
import json
import math
import os

import pytest

from automatic_support import (
    BOSS,
    DEPTH,
    DOCUMENT,
    FILLET,
    FINISH,
    SESSION,
    SKETCH,
    VERTICAL,
    FakeLive,
    _pids,
    block,
    plan_of,
)
from solidseas.ai.context import Feature, PartSnapshot
from solidseas.swapi.bridge import BridgeRequestError
from solidseas_app.assistant.automatic import RunStart
from solidseas_app.assistant.run import (
    AutomaticRun,
    boss_box,
    differences,
    inverse_of,
    verify,
)
from solidseas_app.assistant.writer import take_writer


def started(tmp_path, plan) -> RunStart:
    folder = tmp_path / "run"
    folder.mkdir()
    checkpoint = folder / "checkpoint-run.sldprt"
    checkpoint.write_bytes(b"copy")
    return RunStart("run", str(folder), str(checkpoint), plan, take_writer(next(_pids)))


def journal(tmp_path) -> list[dict]:
    with open(tmp_path / "run" / "journal.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_of(tmp_path, live, plan, **kwargs) -> AutomaticRun:
    return AutomaticRun(live, SESSION, DOCUMENT, started(tmp_path, plan), baseline=live.state, **kwargs)


# --------------------------------------------------------------------------- the loop
def test_a_plan_is_carried_out_checked_and_journaled(tmp_path):
    live = FakeLive(block())
    plan = plan_of(live.state, FILLET, DEPTH, FINISH)
    events = []
    run = run_of(tmp_path, live, plan, on_event=lambda kind, data: events.append((kind, data.get("index"))))
    outcome = run.run()
    assert outcome.status == "done" and outcome.steps_done == 3
    assert [r.status for r in run.records] == ["done", "done", "done"]
    fillet, depth, finish = (c for c in live.calls if c[0] == "operation")
    assert fillet[1:] == (
        "fillet",
        {"edges": list(VERTICAL), "radius": pytest.approx(0.001)},
        "SolidSeas step 1: fillet",
        True,
    )
    assert depth[3] == "SolidSeas step 2: set_dimension" and depth[2]["value"] == pytest.approx(0.009)
    assert finish[3] is None  # a property edit is not on the undo list (answer 2)
    lines = journal(tmp_path)
    assert [line["event"] for line in lines] == [
        "run_started",
        "plan",
        "step_started",
        "step_done",
        "step_started",
        "step_done",
        "step_started",
        "step_done",
        "run_ended",
    ]
    assert lines[2]["inverse"] == {"kind": "delete_made"}
    assert lines[4]["inverse"] == {"kind": "set_dimension", "dimension": f"dim:{BOSS}:D1", "value": 0.008}
    assert lines[6]["inverse"] == {"kind": "property", "name": "Finish", "scope": "file", "value": None}
    assert lines[3]["made"] == ["RmlsMQ=="]
    assert ("ended", None) in events and ("step_done", 3) in events
    assert run.start.writer.held  # the session stays held until Keep or Revert
    run.keep()
    assert not run.start.writer.held and journal(tmp_path)[-1]["event"] == "kept"


def test_revert_takes_the_steps_off_newest_first(tmp_path):
    live = FakeLive(block())
    baseline = live.state
    run = run_of(tmp_path, live, plan_of(baseline, FILLET, DEPTH, FINISH))
    assert run.run().status == "done"
    live.calls.clear()
    assert run.revert() == []
    assert live.ops() == ["restore_property", "set_dimension", "delete"]
    assert live.calls[1][2] == {"dimension": f"dim:{BOSS}:D1", "value": 0.008}
    assert live.calls[1][3] == "SolidSeas revert of step 2"
    assert differences(baseline, live.state) == []
    assert [r.status for r in run.records] == ["reverted"] * 3
    assert not run.start.writer.held


def test_a_step_that_changes_more_than_it_may_is_taken_back_and_ends_the_run(tmp_path):
    def sloppy(state, args):
        new, reply = FakeLive.default_effects()["fillet"](state, args)
        dims = tuple(
            dataclasses.replace(d, value=0.03) if d.name == "D1@Sketch1" else d for d in new.dimensions
        )
        return dataclasses.replace(new, dimensions=dims), reply

    live = FakeLive(block(), {"fillet": sloppy})
    baseline = live.state
    run = run_of(tmp_path, live, plan_of(baseline, FILLET, DEPTH))
    outcome = run.run()
    assert outcome.status == "failed" and outcome.steps_done == 0
    assert "other dimension" in outcome.message
    assert live.ops() == ["fillet", "delete"]  # taken back at once; step 2 never ran
    assert differences(baseline, live.state) == []
    assert [line["event"] for line in journal(tmp_path)][-3:] == [
        "step_taken_back",
        "step_failed",
        "run_ended",
    ]


def test_a_refused_step_leaves_the_part_as_it_was(tmp_path):
    def refused(state, args):
        raise BridgeRequestError(
            "live_operation: SOLIDWORKS made no fillet: the radius may not fit the edges", code="failed"
        )

    live = FakeLive(block(), {"fillet": refused})
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH))
    outcome = run.run()
    assert outcome.status == "failed" and "made no fillet" in outcome.message
    assert live.ops() == ["fillet"]  # nothing was made, so nothing to delete
    assert run.records[0].problems == [
        "live_operation: SOLIDWORKS made no fillet: the radius may not fit the edges"
    ]


def test_an_undo_entry_that_recorded_nothing_fails_the_step(tmp_path):
    def unrecorded(state, args):
        new, reply = FakeLive.default_effects()["fillet"](state, args)
        return new, {**reply, "undo_recorded": False}

    live = FakeLive(block(), {"fillet": unrecorded})
    outcome = run_of(tmp_path, live, plan_of(live.state, FILLET)).run()
    assert outcome.status == "failed" and "undo entry recorded nothing" in outcome.message
    assert live.ops() == ["fillet", "delete"]


def test_a_change_made_outside_the_run_stops_it(tmp_path):
    live = FakeLive(block())

    def person_renames(fake):  # the person renames a feature while the run works
        features = (dataclasses.replace(fake.state.features[0], name="Profile"),) + fake.state.features[1:]
        fake.state = dataclasses.replace(fake.state, features=features)
        fake.after_operation = None

    live.after_operation = person_renames
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH))
    outcome = run.run()
    assert outcome.status == "failed"  # step 1's check saw the rename as part of the fillet
    assert live.ops() == ["fillet", "delete"]


def test_a_change_between_steps_stops_the_run_before_the_next(tmp_path):
    live = FakeLive(block())
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH))

    def person_edits(kind, data):
        if kind == "step_done":
            live.state = dataclasses.replace(live.state, material="Brass")

    run.on_event = person_edits
    outcome = run.run()
    assert outcome.status == "changed" and "material" in outcome.message
    assert live.ops() == ["fillet"] and outcome.steps_done == 1


def test_the_part_must_stay_the_active_document(tmp_path):
    live = FakeLive(block())
    live.info["active"] = False
    outcome = run_of(tmp_path, live, plan_of(live.state, FILLET)).run()
    assert outcome.status == "changed" and "active document" in outcome.message and live.calls == []


def test_stop_takes_effect_between_steps(tmp_path):
    live = FakeLive(block())
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH, FINISH))
    run.on_event = lambda kind, data: run.stop() if kind == "step_done" else None
    outcome = run.run()
    assert outcome.status == "stopped" and outcome.steps_done == 1 and "step 2" in outcome.message
    assert live.ops() == ["fillet"]
    assert "stop_requested" in [line["event"] for line in journal(tmp_path)]


def test_the_run_deadline_ends_it_between_steps(tmp_path):
    live = FakeLive(block())
    now = iter([0.0, 0.0, 5.0, 5.0, 100.0, 100.0, 100.0])
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH), deadline_s=10.0, clock=lambda: next(now))
    outcome = run.run()
    assert outcome.status == "limit" and outcome.steps_done == 1


def test_a_step_past_its_soft_limit_is_taken_back(tmp_path):
    live = FakeLive(block())
    now = iter([0.0, 0.0, 0.0, 120.0, 120.0])
    run = run_of(tmp_path, live, plan_of(live.state, FILLET), clock=lambda: next(now))
    outcome = run.run()
    assert outcome.status == "failed" and "past its limit" in outcome.message
    assert live.ops() == ["fillet", "delete"]


def test_revert_stops_where_the_part_changed_after_the_run(tmp_path):
    live = FakeLive(block())
    run = run_of(tmp_path, live, plan_of(live.state, FILLET, DEPTH))
    assert run.run().status == "done"
    live.state = dataclasses.replace(live.state, equations=("D1@Sketch1 = 25",))
    live.calls.clear()
    messages = run.revert()
    assert len(messages) == 1 and "step 2" in messages[0] and "checkpoint-run.sldprt" in messages[0]
    assert live.calls == []  # nothing applied to a part that is not as the run left it
    assert not run.start.writer.held


def test_an_inverse_that_cannot_be_recorded_keeps_the_step_from_running(tmp_path):
    snap = block()
    dims = tuple(
        dataclasses.replace(d, value=math.nan) if d.name == "D1@Boss-Extrude1" else d for d in snap.dimensions
    )
    plan = plan_of(snap, DEPTH)
    live = FakeLive(dataclasses.replace(snap, dimensions=dims))
    outcome = run_of(tmp_path, live, plan).run()
    assert outcome.status == "failed" and "did not run" in outcome.message and live.ops() == []


# --------------------------------------------------------------------------- the rules
def _step(snap: PartSnapshot, raw: dict):
    return plan_of(snap, raw).steps[0]


def test_a_boss_may_fill_only_its_profile_extruded_by_its_depth():
    snap = block()
    raw = {
        "op": "sketch_extrude_boss",
        "args": {
            "plane": "Fa1",
            "profile": {"unit": "mm", "segments": [{"type": "circle", "center": [10, 5], "radius": 2}]},
            "depth": {"value": 3, "unit": "mm"},
            "direction": "normal",
            "end": "blind",
        },
    }
    step = _step(snap, raw)
    box = boss_box(step, snap)
    assert box == (pytest.approx((0.008, 0.003, 0.008)), pytest.approx((0.012, 0.007, 0.011)))
    sketch = Feature("U2sy", "Sketch2", "ProfileFeature")
    boss = Feature("Qm8y", "Boss-Extrude2", "ICE")
    good = dataclasses.replace(
        snap,
        features=snap.features + (sketch, boss),
        volume=snap.volume + 3.7e-8,
        box_max=(0.02, 0.01, 0.011),
    )
    reply = {"feature": boss.ref, "undo_recorded": True}
    assert verify(step, snap, good, reply) == []
    too_tall = dataclasses.replace(good, box_max=(0.02, 0.01, 0.012))
    assert verify(step, snap, too_tall, reply) == [
        "the extents grew beyond the profile extruded by its depth"
    ]
    unchanged = dataclasses.replace(good, volume=snap.volume)  # inside material already there
    assert verify(step, snap, unchanged, reply) == ["the volume did not grow: the boss added no material"]
    second_body = dataclasses.replace(good, solid_bodies=2)
    assert "solid bodies" in verify(step, snap, second_body, reply)[0]
    wrong_kind = dataclasses.replace(
        good, features=snap.features + (sketch, Feature("Q3V0", "Cut-Extrude1", "Cut"))
    )
    assert "not of the kind" in verify(step, snap, wrong_kind, {**reply, "feature": "Q3V0"})[0]


def test_a_cut_must_remove_material_and_stay_within_the_part():
    snap = block()
    raw = {
        "op": "sketch_extrude_cut",
        "args": {
            "plane": "Fa1",
            "profile": {"unit": "mm", "segments": [{"type": "circle", "center": [10, 5], "radius": 2}]},
            "depth": {"value": 3, "unit": "mm"},
            "direction": "reversed",
            "end": "blind",
        },
    }
    step = _step(snap, raw)
    sketch = Feature("U2sy", "Sketch2", "ProfileFeature")
    cut = Feature("Qc8y", "Cut-Extrude1", "Cut")
    good = dataclasses.replace(snap, features=snap.features + (sketch, cut), volume=snap.volume - 3.7e-8)
    reply = {"feature": cut.ref, "undo_recorded": True}
    assert verify(step, snap, good, reply) == []
    missed = dataclasses.replace(good, volume=snap.volume)  # the profile missed the part
    assert verify(step, snap, missed, reply) == ["the volume did not shrink: the cut removed no material"]
    grew = dataclasses.replace(good, volume=snap.volume + 1e-9)
    assert verify(step, snap, grew, reply) == ["the volume increased"]
    unmeasured = dataclasses.replace(good, volume=None)  # no volume to compare: the rule cannot say
    assert not any("did not shrink" in p for p in verify(step, snap, unmeasured, reply))


def test_a_fillet_must_consume_the_planned_edges_and_no_more_volume_than_it_may():
    snap = block()
    step = _step(snap, FILLET)
    live = FakeLive(snap)
    after, reply = live.effects["fillet"](snap, {"edges": list(VERTICAL), "radius": 0.001})
    assert verify(step, snap, after, {**reply, "undo_recorded": True}) == []
    neighbour = dataclasses.replace(after, edges=snap.edges[1:])  # built on another edge: E1 still there
    problems = verify(step, snap, neighbour, {**reply, "undo_recorded": True})
    assert any("still there" in p for p in problems)
    gouged = dataclasses.replace(after, volume=snap.volume - 1e-7)
    assert any("size squared" in p for p in verify(step, snap, gouged, {**reply, "undo_recorded": True}))


def test_a_property_step_may_change_that_property_only():
    snap = block()
    step = _step(snap, FINISH)
    good = dataclasses.replace(snap, custom_properties={"Description": "block", "Finish": "black"})
    assert verify(step, snap, good, {}) == []
    also = dataclasses.replace(snap, custom_properties={"Description": "plate", "Finish": "black"})
    assert verify(step, snap, also, {}) == ["custom properties other than the one named changed"]
    moved = dataclasses.replace(good, volume=1.7e-6)
    assert verify(step, snap, moved, {}) == ["the part's geometry or tree changed"]


def test_new_rebuild_errors_fail_a_step_and_old_ones_are_the_baseline():
    snap = dataclasses.replace(block(), whats_wrong=((BOSS, 7, True), (SKETCH, 3, False)))
    step = _step(snap, DEPTH)
    after, reply = FakeLive.default_effects()["set_dimension"](
        snap, {"dimension": f"dim:{BOSS}:D1", "value": 0.009}
    )
    assert verify(step, snap, after, {**reply, "undo_recorded": True}) == []
    worse = dataclasses.replace(after, whats_wrong=after.whats_wrong + (("RmlsMQ==", 51, False),))
    assert verify(step, snap, worse, {**reply, "undo_recorded": True}) == [
        "What's Wrong has 1 new rebuild error(s)"
    ]


def test_inverses_are_what_puts_each_step_back():
    snap = block()
    assert inverse_of(_step(snap, FILLET), snap) == {"kind": "delete_made"}
    assert inverse_of(_step(snap, DEPTH), snap) == {
        "kind": "set_dimension",
        "dimension": f"dim:{BOSS}:D1",
        "value": 0.008,
    }
    assert inverse_of(_step(snap, {"op": "suppress", "args": {"features": ["F2"]}}), snap) == {
        "kind": "suppression",
        "features": [[BOSS, False]],
    }
    assert inverse_of(_step(snap, FINISH), snap)["value"] is None


def test_the_journal_is_synced_json_lines(tmp_path):
    live = FakeLive(block())
    run = run_of(tmp_path, live, plan_of(live.state, FILLET))
    run.run()
    raw = (tmp_path / "run" / "journal.jsonl").read_text(encoding="utf-8")
    assert raw.endswith("\n") and all(json.loads(line)["time"] > 0 for line in raw.splitlines())
    assert os.path.getsize(tmp_path / "run" / "journal.jsonl") == len(raw.encode("utf-8"))
