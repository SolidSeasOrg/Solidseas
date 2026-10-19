"""Automatic mode in the assistant's window: planning a goal through the scripted provider,
the confirmation gate, the run on a part held in memory (``automatic_support.FakeLive``),
Stop, Keep, Revert and the machine policy. No test reaches a network or SOLIDWORKS."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from automatic_support import DEPTH, FILLET, FINISH, WindowLive, block
from solidseas import policy
from solidseas.ai.fake import ScriptedProvider
from solidseas_app.assistant.run import differences

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs no PySide6
    HAVE_QT = False

pytestmark = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def plan_reply(*steps, notes: str = "") -> str:
    return json.dumps({"vocabulary": 1, "steps": list(steps), "notes": notes})


def _wait(app, condition, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the assistant")
        app.processEvents()
        time.sleep(0.01)


def _window(app, provider, live):
    from solidseas_app.assistant.window import AssistantWindow

    w = AssistantWindow(provider, live)
    w.show()
    _wait(app, lambda: w._snapshot is not None)
    w.automatic.setChecked(True)
    return w


def _log(w) -> str:
    return w.log.toPlainText()


def test_automatic_plans_instead_of_drafting_and_shows_the_planning_prompt(app):
    w = _window(app, ScriptedProvider(), WindowLive(block()))
    try:
        assert w.draft_button.text() == "Plan"
        assert w.plan_box.isVisibleTo(w) and not w.console_box.isVisibleTo(w)
        w.request.setPlainText("Round the four vertical edges 1 mm")
        shown = w.sees.toPlainText()
        assert "You plan changes to one SOLIDWORKS part" in shown and "<goal>" in shown
        w.automatic.setChecked(False)
        assert w.draft_button.text() == "Draft" and w.console_box.isVisibleTo(w)
    finally:
        w.close()


def test_a_plan_that_overwrites_nothing_starts_by_itself_and_reverts(app):
    live = WindowLive(block())
    baseline = live.state
    provider = ScriptedProvider([plan_reply(FILLET, notes="Four 1 mm rounds.")])
    w = _window(app, provider, live)
    try:
        w.request.setPlainText("Round the four vertical edges 1 mm")
        shown = w.sees.toPlainText()
        w.draft()
        _wait(app, lambda: w._run is not None and w._run.outcome is not None and w.plan_revert.isEnabled())
        assert shown == provider.prompts[0].text()  # what the AI saw is what was sent
        plan = w.plan_view.toPlainText()
        assert plan.startswith("1. fillet: edges E1, E2, E3, E4 (from the model); radius 1 mm (you said)")
        assert "Notes: Four 1 mm rounds." in plan
        log = _log(w)
        assert "It starts by itself." in log and "Step 1 of 1: fillet..." in log
        assert "Step 1 done and checked." in log and "All 1 steps were carried out and checked." in log
        assert ("checkpoint" in [c[0] for c in live.calls]) and w._run.start.writer.held
        w.revert_run()
        _wait(app, lambda: "Reverted: the part is as it was before the run." in _log(w))
        assert differences(baseline, live.state) == []
        assert not w._run.start.writer.held and not w.plan_keep.isEnabled()
    finally:
        w.close()


def test_a_plan_that_overwrites_what_you_have_waits_for_run_plan(app):
    live = WindowLive(block())
    w = _window(app, ScriptedProvider([plan_reply(DEPTH, FINISH)]), live)
    try:
        w.request.setPlainText("Make it deeper and black")
        w.draft()
        _wait(app, lambda: w.plan_run.isEnabled())
        assert "It waits for Run plan." in w.plan_note.text()
        assert "a value you did not say" in w.plan_note.text()  # 9 mm came from the model
        assert "writes the custom property Finish" in w.plan_note.text()
        assert not [c for c in live.calls if c[0] in ("operation", "checkpoint")]  # nothing ran
        w.run_plan()
        _wait(app, lambda: w.plan_keep.isEnabled())
        assert [c[1] for c in live.calls if c[0] == "operation"] == ["set_dimension", "set_property"]
        w.keep_run()
        assert not w._run.start.writer.held and "Kept" in w.plan_note.text()
        assert live.state.custom_properties["Finish"] == "black"
    finally:
        w.close()


def test_stop_ends_the_run_between_steps(app):
    live = WindowLive(block())
    w = _window(app, ScriptedProvider([plan_reply(FILLET, FINISH)]), live)
    in_step, go_on = threading.Event(), threading.Event()

    def hold(fake):  # step 1 is running in SOLIDWORKS when the person presses Stop
        in_step.set()
        go_on.wait(30)

    try:
        w.request.setPlainText("Round the edges 1 mm and make it black")
        live.after_operation = hold
        w.draft()
        _wait(app, lambda: w.plan_run.isEnabled())  # set_property waits
        w.run_plan()
        _wait(app, lambda: in_step.is_set() and w._run is not None)
        w.stop_plan()
        go_on.set()
        _wait(app, lambda: w._run is not None and w._run.outcome is not None)
        assert w._run.outcome.status == "stopped" and w._run.outcome.steps_done == 1
        assert "Stopping after the current step." in _log(w)
        assert [c[1] for c in live.calls if c[0] == "operation"] == ["fillet"]
    finally:
        w.close()


def test_a_refused_start_says_why_and_changes_nothing(app):
    live = WindowLive(block())
    live.info["active"] = False
    w = _window(app, ScriptedProvider([plan_reply(FILLET)]), live)
    try:
        w.request.setPlainText("Round the four vertical edges 1 mm")
        w.draft()
        _wait(app, lambda: "The run did not start" in _log(w))
        assert "is not the active document" in _log(w)
        assert not [c for c in live.calls if c[0] in ("operation", "checkpoint")]
        assert not w.run_active
    finally:
        w.close()


def test_the_machine_policy_can_turn_automatic_mode_off(app, policy_reader):
    from solidseas_app.assistant.aisettings import ADMIN

    policy_reader(policy.Policy(automatic_disabled=True))
    from solidseas_app.assistant.window import AssistantWindow

    w = AssistantWindow(ScriptedProvider(), WindowLive(block()))
    try:
        assert not w.automatic.isEnabled() and ADMIN in w.automatic.toolTip()
        assert w.draft_button.isEnabled()  # Review mode stays
    finally:
        w.close()


def test_the_saved_always_confirm_setting_makes_every_plan_wait(app):
    live = WindowLive(block())
    w = _window(app, ScriptedProvider([plan_reply(FILLET)]), live)
    try:
        w.ai.settings.update(always_confirm=True)
        w.request.setPlainText("Round the four vertical edges 1 mm")
        w.draft()
        _wait(app, lambda: w.plan_run.isEnabled())
        assert "Always confirm the plan before a run is on." in w.plan_note.text()
        assert not [c for c in live.calls if c[0] in ("operation", "checkpoint")]
    finally:
        w.close()


# --------------------------------------------------------------------------- a look after each step
def _drawn_without_rendering(monkeypatch):
    """The copy after each step is "drawn" as a tiny PNG: the stand-in part's copy is not a
    real SOLIDWORKS file (``tests/test_assistant_review.py`` draws a real one)."""
    from solidseas.ai.prompts import part_image
    from solidseas.formats._source import encode_png
    from solidseas_app.assistant import picture

    drawn = []

    def draw(path, caption, *, side=picture.SIDE):
        drawn.append(path)
        return part_image(encode_png(2, 2, bytes(12), 3), caption)

    monkeypatch.setattr(picture, "drawn", draw)
    return drawn


def test_the_look_after_each_step_is_offered_only_with_the_picture_and_says_what_goes(app):
    from solidseas_app.assistant import picture

    w = _window(app, ScriptedProvider(), WindowLive(block()))
    try:
        w.request.setPlainText("Round the four vertical edges 1 mm")
        box = w.step_pictures
        assert box.text() == picture.STEP_TEXT and box.isVisibleTo(w)
        assert not box.isEnabled() and not box.isChecked() and picture.STEP_NEEDS_PICTURE in box.toolTip()
        w.picture.setChecked(True)
        assert box.isEnabled() and not box.isChecked()  # off until ticked
        assert "after each step" not in w.sees.toPlainText()
        box.setChecked(True)
        shown = w.sees.toPlainText()
        assert "[after each step that passes SolidSeas' checks, one more request]" in shown
        assert "the part after step N, drawn from a copy SolidSeas saved after the step" in shown
        w.picture.setChecked(False)  # the picture's box is the word that pictures may go at all
        assert not box.isChecked() and not box.isEnabled()
        assert "after each step" not in w.sees.toPlainText()
        w.automatic.setChecked(False)
        assert not box.isVisibleTo(w)
    finally:
        w.close()


def test_with_the_look_ticked_the_model_sees_the_part_after_each_step(app, monkeypatch):
    drawn = _drawn_without_rendering(monkeypatch)
    live = WindowLive(block())
    looks = [
        json.dumps({"as_expected": True, "reason": "Four rounded edges."}),
        json.dumps({"as_expected": False, "reason": "The part looks unchanged."}),
    ]
    provider = ScriptedProvider([plan_reply(FILLET, FINISH), *looks])
    w = _window(app, provider, live)
    try:
        w.picture.setChecked(True)
        w.step_pictures.setChecked(True)
        w.request.setPlainText("Round the four vertical edges 1 mm and make it black")
        w.draft()
        _wait(app, lambda: w.plan_run.isEnabled())  # set_property waits
        w.run_plan()
        _wait(app, lambda: w._run is not None and w._run.outcome is not None and w.plan_revert.isEnabled())
        assert w._run.outcome.status == "looks_wrong" and w._run.outcome.steps_done == 2
        assert [os.path.basename(p) for p in drawn] == [
            f"checkpoint-{w._run.start.run_id}-step-1.sldprt",
            f"checkpoint-{w._run.start.run_id}-step-2.sldprt",
        ]
        plan_call, first, second = provider.prompts
        assert plan_call.task == "plan" and (first.task, second.task) == ("look", "look")
        assert "Round the four vertical edges" in first.user and "Step 2 of 2" in second.user
        log = _log(w)
        assert "After each step, the model is shown the part" in log
        assert "Step 1: the model looked at the part and says it looks right: Four rounded edges." in log
        assert "Step 2: the model looked at the part and says it does not look right" in log
        assert "Keep it, or Revert." in log and w.plan_keep.isEnabled()
    finally:
        w.close()


def test_without_the_look_no_picture_is_made_after_a_step(app, monkeypatch):
    drawn = _drawn_without_rendering(monkeypatch)
    live = WindowLive(block())
    provider = ScriptedProvider([plan_reply(FILLET)])
    w = _window(app, provider, live)
    try:
        w.picture.setChecked(True)  # a picture with the plan only
        w.request.setPlainText("Round the four vertical edges 1 mm")
        w.draft()
        _wait(app, lambda: w._run is not None and w._run.outcome is not None)
        assert w._run.outcome.status == "done" and drawn == [] and len(provider.prompts) == 1
        assert [c[0] for c in live.calls].count("checkpoint") == 1  # the safety copy, and no other
    finally:
        w.close()


def test_the_machine_policy_greys_out_the_look_after_each_step(app, policy_reader):
    from solidseas_app.assistant import picture

    policy_reader(policy.Policy(images_disabled=True))
    w = _window(app, ScriptedProvider(), WindowLive(block()))
    try:
        assert not w.step_pictures.isEnabled() and not w.step_pictures.isChecked()
        assert picture.ADMIN_OFF in w.step_pictures.toolTip()
    finally:
        w.close()
