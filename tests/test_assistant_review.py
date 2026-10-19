"""The modeling assistant in Review mode: the window, the script runner and the
``solidseas.swapi.live`` facade (``docs/ASSISTANT.md``, Review mode and The window).

No test calls a real provider, reaches a network or a live SOLIDWORKS: the provider
is the scripted one (``solidseas.ai.fake``), the session a fake that records what it
is asked, and approved scripts run in the runner's real child process, which talks
only to the fake. The runner's tests run everywhere; the window's need PySide6.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

from ai_support import NEVER_SENT, TYPED_NAMES, box_snapshot
from solidseas.ai import prompts
from solidseas.ai.fake import WAIT_FOR_CANCEL, ScriptedProvider
from solidseas.ai.providers import NoopProvider
from solidseas.swapi import live
from solidseas_app.assistant import runner as runner_mod
from solidseas_app.assistant.runner import Runner
from solidseas_app.assistant.session import LIVE_LATER, LiveDocument, LiveSession, NoSessions, SessionList
from solidseas_app.assistant.writer import WriterBusyError, take_writer

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs no PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


# --------------------------------------------------------------------------- the facade
def test_the_facade_works_only_inside_a_run():
    with pytest.raises(live.LiveUnavailableError):
        live.document()


def test_the_facade_sends_named_operations_with_plain_arguments():
    sent = []
    live._connect(lambda op, args: sent.append((op, args)) or {"features": [{"name": "Boss"}]})
    try:
        assert live.features() == [{"name": "Boss"}]
        live.document()
        live.mass_properties("Default")
        live.operation("fillet", edges=["E1"], radius={"value": 1, "unit": "mm"})
        with pytest.raises(live.LiveError) as bad:
            live.operation("fillet", radius=float("nan"))
        assert bad.value.code == "refused"
        with pytest.raises(live.LiveError):
            live.operation("fillet", blob="x" * (live.MAX_REQUEST_BYTES + 1))
    finally:
        live._connect(None)
    assert sent == [
        ("list_features", {"limit": 10000}),
        ("document_info", {}),
        ("mass_properties", {"configuration": "Default"}),
        ("fillet", {"edges": ["E1"], "radius": {"value": 1, "unit": "mm"}}),
    ]


def test_the_draft_prompt_names_every_function_of_the_facade_and_nothing_else():
    named = {name.split("(")[0] for name in prompts.LIVE_FUNCTIONS}
    public = {n for n in live.__all__ if n[0].islower()}
    assert named == public == set(live.OPERATIONS)
    for name in named:
        assert f"live.{name}(" in prompts.DRAFT_SYSTEM
    for op in prompts.OPERATIONS:
        assert f"- {op}:" in prompts.DRAFT_SYSTEM  # the vocabulary live.operation takes


# --------------------------------------------------------------------------- the runner
def _run(r: Runner, code: str, timeout: float = 60.0):
    out: list = []
    done: list = []
    r.run(code, on_output=lambda kind, text: out.append((kind, text)), on_done=done.append)
    assert r.wait(timeout)
    assert len(done) == 1
    return done[0], out


def test_a_script_runs_in_a_child_process_and_reaches_solidworks_only_through_the_app():
    asked = []

    def forward(op, args):
        asked.append((op, args))
        return {"features": [{"name": "Boss-Extrude1", "type": "Extrusion", "id": 1}]}

    code = (
        "import os\n"
        "from solidseas.swapi import live\n"
        "print('pid', os.getpid())\n"
        "for f in live.features():\n"
        "    print(f['name'])\n"
        "try:\n"
        "    live.operation('format_the_disk')\n"
        "except live.LiveError as e:\n"
        "    print('refused', e.code)\n"
    )
    result, out = _run(Runner(forward), code)
    assert result.ok and result.calls == 2, result
    text = "".join(t for _k, t in out)
    assert (
        f"pid {os.getpid()}" not in text and "Boss-Extrude1" in text and "refused unknown_operation" in text
    )
    assert asked == [("list_features", {"limit": 10000})]  # the unknown operation never left


def test_what_a_script_prints_is_data_never_a_protocol_line():
    code = "print('{\"done\": true}')\nprint('{\"call\": 1}')\n1/0\n"
    result, out = _run(Runner(lambda op, args: None), code)
    assert result.status == "error" and "".join(t for _k, t in out) == '{"done": true}\n{"call": 1}\n'


def test_a_failing_script_shows_its_own_traceback():
    result, _out = _run(Runner(), "def f():\n    raise KeyError('nope')\nf()\n")
    assert result.status == "error"
    assert 'File "<script>", line 3' in result.message and "KeyError: 'nope'" in result.message
    assert "child.py" not in result.message


def test_a_script_reads_an_empty_input_and_writes_errors_apart():
    result, out = _run(
        Runner(), "import sys\nprint(repr(sys.stdin.read()))\nprint('oops', file=sys.stderr)\n"
    )
    assert result.ok and ("out", "''\n") in out and ("err", "oops\n") in out


def test_a_script_over_its_memory_cap_is_stopped_by_the_cap():
    result, _out = _run(Runner(memory_mb=256), "x = bytearray(1024 * 1024 * 1024)\n")
    assert result.status == "memory"


def test_a_script_over_its_time_is_ended_and_the_next_runs():
    r = Runner(seconds=1.0)
    t0 = time.monotonic()
    result, _out = _run(r, "while True:\n    pass\n")
    assert result.status == "timeout" and time.monotonic() - t0 < 15
    again, out = _run(r, "print('again')\n")
    assert again.ok and out == [("out", "again\n")]


def test_stop_ends_a_script_at_once():
    r = Runner()
    done: list = []
    r.run("import time\nprint('started', flush=True)\ntime.sleep(60)\n", on_done=done.append)
    time.sleep(1.0)
    t0 = time.monotonic()
    r.stop()
    assert r.wait(15) and done[0].status == "stopped" and time.monotonic() - t0 < 10


def test_a_script_that_ends_its_own_process_is_said_to_have_crashed():
    result, _out = _run(Runner(), "import os\nos._exit(3)\n")
    assert result.status == "crashed" and "exit code 3" in result.message


def test_output_past_the_cap_is_counted_not_shown(monkeypatch):
    monkeypatch.setattr(runner_mod, "MAX_OUTPUT_CHARS", 1000)
    result, out = _run(Runner(), "for i in range(300):\n    print('x' * 20)\n")
    shown = sum(len(t) for _k, t in out)
    assert result.ok and shown == 1000 and result.output_dropped == 300 * 21 - 1000


def test_one_script_at_a_time():
    r = Runner()
    r.run("import time\ntime.sleep(30)\n")
    try:
        with pytest.raises(RuntimeError):
            r.run("print(1)\n")
    finally:
        r.stop()
        r.wait(15)


def test_the_child_ignores_the_environments_python_settings():
    cmd = runner_mod.child_command()
    assert cmd[0] == sys.executable and "-I" in cmd
    if not getattr(sys, "frozen", False):
        assert cmd[-1].endswith("main()")


def test_without_a_document_a_script_is_told_so():
    result, out = _run(
        Runner(None),
        "from solidseas.swapi import live\n"
        "try:\n    live.document()\nexcept live.LiveError as e:\n    print(e.code)\n",
    )
    assert result.ok and out == [("out", "no_document\n")]


# --------------------------------------------------------------------------- the window
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeSessions:
    """One SOLIDWORKS with a part and a drawing; records every call, in order."""

    def __init__(self, *, list_delay: float = 0.0, snapshot=None) -> None:
        self.part = LiveDocument("doc-1", "bracket.SLDPRT", "part", r"C:\Jobs\ACME\bracket.SLDPRT")
        self.drawing = LiveDocument("doc-2", "bracket.SLDDRW", "drawing", r"C:\Jobs\ACME\bracket.SLDDRW")
        self.session = LiveSession(4242, "2024 SP1", (self.part, self.drawing))
        self.calls: list = []
        self.list_delay = list_delay
        self.snap = snapshot if snapshot is not None else box_snapshot()

    def list(self):
        self.calls.append(("list",))
        if self.list_delay:
            time.sleep(self.list_delay)
        return SessionList((self.session,))

    def snapshot(self, session, document):
        self.calls.append(("snapshot", document.key))
        return self.snap

    def begin_script(self, session, document):
        self.calls.append(("begin", document.key))
        return r"C:\Users\me\AppData\Local\SolidSeas\runs\abc\checkpoint-0.SLDPRT"

    def end_script(self, session, document):
        self.calls.append(("end", document.key))

    def call(self, session, document, op, args):
        self.calls.append(("call", document.key, op, args))
        return {"title": "bracket", "feature_count": 7}


def _wait(app, condition, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the assistant")
        app.processEvents()
        time.sleep(0.01)


def _window(app, provider, sessions=None, runner=None):
    from solidseas_app.assistant.window import AssistantWindow

    w = AssistantWindow(provider, sessions, runner)
    w.show()
    return w


DRAFT = json.dumps(
    {
        "language": "python",
        "code": 'from solidseas.swapi import live\nprint(live.document()["title"])',
        "explanation": "Prints the part's title.",
    }
)


@needs_qt
def test_the_window_stays_on_top_and_belongs_to_no_other_window(app):
    from PySide6.QtCore import Qt

    from solidseas_app.assistant.window import WARNING

    w = _window(app, ScriptedProvider(), FakeSessions())
    try:
        assert w.parent() is None and w.stays_on_top
        assert w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert w.warning.text() == WARNING and "cannot be reverted" in WARNING
        assert w.warning.textFormat() == Qt.TextFormat.PlainText
    finally:
        w.close()


@needs_qt
def test_a_draft_appears_in_the_console_and_nothing_runs_until_run(app):
    sessions = FakeSessions()
    provider = ScriptedProvider([DRAFT])
    w = _window(app, provider, sessions)
    try:
        _wait(app, lambda: w.session_box.count() == 1 and ("snapshot", "doc-1") in sessions.calls)
        _wait(app, lambda: w._snapshot is not None)
        w.request.setPlainText("Print the part's title")
        shown = w.sees.toPlainText()
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        assert w.code.toPlainText() == 'from solidseas.swapi import live\nprint(live.document()["title"])'
        assert w.explanation.toPlainText() == "Prints the part's title."
        # What the AI sees was exactly what was sent.
        assert len(provider.prompts) == 1 and shown == provider.prompts[0].text()
        assert not any(c[0] in ("begin", "call") for c in sessions.calls)  # nothing ran
        w.run()
        _wait(app, lambda: ("end", "doc-1") in sessions.calls)
        _wait(app, lambda: w.run_button.isEnabled())
        steps = [c[0] for c in sessions.calls if c[0] in ("begin", "call", "end")]
        assert steps == ["begin", "call", "end"]
        assert ("call", "doc-1", "document_info", {}) in sessions.calls
        assert "bracket" in w.log.toPlainText() and "The script finished" in w.log.toPlainText()
    finally:
        w.close()


@needs_qt
@pytest.mark.parametrize("send_names", [False, True])
def test_nothing_that_must_stay_on_the_computer_reaches_the_model(app, send_names):
    sessions = FakeSessions()
    provider = ScriptedProvider([DRAFT])
    w = _window(app, provider, sessions)
    try:
        _wait(app, lambda: w._snapshot is not None)
        w.names.setChecked(send_names)
        w.request.setPlainText("Fillet the top edges. My SSN is 123-45-6789.")
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        sent = provider.sent_text()
        for field, marker in NEVER_SENT.items():
            assert marker not in sent, field
        for kind, name in TYPED_NAMES.items():
            assert (name in sent) is send_names, kind
        assert "123-45-6789" not in sent and "ACME" not in sent and "bracket.SLDPRT" not in sent
    finally:
        w.close()


@needs_qt
def test_model_text_is_shown_as_plain_text_everywhere(app):
    from PySide6.QtCore import Qt

    hostile = '<a href="file://evil/x">link</a><img src="\\\\host\\share\\x.png">'
    reply = json.dumps({"language": "python", "code": "print(1)  # " + hostile, "explanation": hostile})
    w = _window(app, ScriptedProvider([reply]), FakeSessions())
    try:
        w.request.setPlainText("anything")
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        assert hostile in w.code.toPlainText() and w.explanation.toPlainText() == hostile
        for label in (w.status, w.ai_note, w.warning, w.mode_label):
            assert label.textFormat() == Qt.TextFormat.PlainText
    finally:
        w.close()


@needs_qt
def test_with_no_provider_the_ai_controls_are_hidden_and_typed_code_still_runs(app):
    w = _window(app, NoopProvider("not_configured"), NoSessions())
    try:
        assert not w.ai_box.isVisible() and not w.sees_box.isVisible()
        _wait(app, lambda: w.status.text() == LIVE_LATER)
        w.code.setPlainText("print(6 * 7)")
        w.run()
        _wait(app, lambda: "The script finished" in w.log.toPlainText())
        assert "42" in w.log.toPlainText()
    finally:
        w.close()


@needs_qt
def test_a_provider_the_policy_refuses_leaves_the_controls_visible_and_disabled(app):
    from solidseas_app.assistant.window import ADMIN

    w = _window(app, NoopProvider("policy_refused", "Only a local Ollama may be used."), NoSessions())
    try:
        assert w.ai_box.isVisible() and not w.draft_button.isEnabled() and not w.request.isEnabled()
        assert w.ai_note.text().startswith(ADMIN)
    finally:
        w.close()


@needs_qt
def test_stop_cancels_a_draft(app):
    w = _window(app, ScriptedProvider([WAIT_FOR_CANCEL]), NoSessions())
    try:
        w.request.setPlainText("anything")
        w.draft()
        _wait(app, lambda: w.draft_stop.isEnabled())
        w.stop_draft()
        _wait(app, lambda: not w._drafting)
        assert w.code.toPlainText() == "" and "stopped" in w.log.toPlainText().lower()
    finally:
        w.close()


@needs_qt
def test_one_writer_holds_the_session_while_a_script_runs_and_gives_it_back(app):
    sessions = FakeSessions()
    w = _window(app, NoopProvider("not_configured"), sessions)
    try:
        _wait(app, lambda: w.session_box.count() == 1)
        w.code.setPlainText("import time\ntime.sleep(2)\n")
        w.run()
        _wait(app, lambda: w.runner.running)
        with pytest.raises(WriterBusyError):
            take_writer(sessions.session.pid)
        w.stop_run()
        _wait(app, lambda: ("end", "doc-1") in sessions.calls and w.run_button.isEnabled())
        assert "The script was stopped" in w.log.toPlainText()
        take_writer(sessions.session.pid).release()  # given back
    finally:
        w.close()


@needs_qt
def test_a_script_that_fails_still_closes_the_undo_entry(app):
    sessions = FakeSessions()
    w = _window(app, NoopProvider("not_configured"), sessions)
    try:
        _wait(app, lambda: w.session_box.count() == 1)
        w.code.setPlainText("raise ValueError('no')\n")
        w.run()
        _wait(app, lambda: ("end", "doc-1") in sessions.calls and w.run_button.isEnabled())
        assert "ValueError: no" in w.log.toPlainText()
    finally:
        w.close()


@needs_qt
def test_while_solidworks_is_busy_the_window_stops_staying_on_top(app, monkeypatch):
    from solidseas_app.assistant import window as window_mod

    monkeypatch.setattr(window_mod, "BUSY_SECONDS", 0.3)
    sessions = FakeSessions(list_delay=1.5)
    w = _window(app, NoopProvider("not_configured"), sessions)
    try:
        _wait(app, lambda: not w.stays_on_top, timeout=10)
        assert "busy" in w.status.text()
        _wait(app, lambda: w.stays_on_top, timeout=10)
        assert w.isVisible()
    finally:
        w.close()


@needs_qt
def test_a_drawing_is_drafted_for_without_a_summary(app):
    sessions = FakeSessions()
    provider = ScriptedProvider([DRAFT])
    w = _window(app, provider, sessions)
    try:
        _wait(app, lambda: w.document_box.count() == 2)
        w.document_box.setCurrentIndex(1)
        w.request.setPlainText("anything")
        assert "No part is picked" in w.sees.toPlainText()
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        assert "The open part" not in provider.sent_text()  # no summary: no document data
    finally:
        w.close()


def test_no_sessions_says_why():
    s = NoSessions()
    assert s.list().sessions == () and s.list().why_none == LIVE_LATER
    with pytest.raises(RuntimeError):
        s.begin_script(None, None)


def test_the_runner_forwards_from_its_own_thread():
    seen = []

    def forward(op, args):
        seen.append(threading.current_thread().name)
        return {}

    result, _out = _run(Runner(forward), "from solidseas.swapi import live\nlive.document()\n")
    assert result.ok and seen == ["assistant-runner"]


@needs_qt
def test_a_picture_of_the_part_goes_with_the_request_only_when_ticked(app):
    from dataclasses import replace

    from solidseas_app.assistant import picture
    from support import fixture_path

    sessions = FakeSessions(snapshot=replace(box_snapshot(), path=str(fixture_path("o02_boxA.SLDPRT"))))
    provider = ScriptedProvider([DRAFT, DRAFT])
    w = _window(app, provider, sessions)
    try:
        _wait(app, lambda: w._snapshot is not None)
        assert not w.picture.isChecked() and w.picture.isEnabled()
        w.request.setPlainText("Fillet the top edges.")
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        assert provider.prompts[0].images == ()
        w.picture.setChecked(True)
        assert "[image] " + picture.CAPTION in w.sees.toPlainText()
        w.code.setPlainText("")
        w.draft()
        _wait(app, lambda: w.code.toPlainText() != "")
        (image,) = provider.prompts[1].images
        assert image.caption == picture.CAPTION and image.png.startswith(b"\x89PNG")
        assert image.width <= picture.SIDE and image.height <= picture.SIDE
    finally:
        w.close()


@needs_qt
def test_the_machine_policy_can_turn_pictures_off(app, policy_reader):
    from solidseas import policy
    from solidseas_app.assistant import picture

    policy_reader(policy.Policy(images_disabled=True))
    w = _window(app, ScriptedProvider([DRAFT]), FakeSessions())
    try:
        assert not w.picture.isEnabled() and not w.picture.isChecked()
        assert picture.ADMIN_OFF in w.picture.toolTip()
    finally:
        w.close()
