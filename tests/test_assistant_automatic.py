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
