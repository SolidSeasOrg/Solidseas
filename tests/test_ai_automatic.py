"""Automatic mode's entry: the confirmation gate, start_run's checks in their order, and one
writer per SOLIDWORKS session. The bridge is a stand-in that records what it was asked."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ai_support import FakeTarget, handle_of, mm, parse, plan_json, said_plan, square, step, summary_of
from solidseas.policy import Policy
from solidseas_app.assistant import automatic, writer
from solidseas_app.assistant.automatic import CHANGED_MESSAGE, RunRefused, confirmation, start_run
from solidseas_app.assistant.writer import BUSY_MESSAGE, WriterBusyError, mutex_name, take_writer

S = summary_of()
WIDTH = handle_of(S, "pr:dim:width")
EDGE = handle_of(S, "pr:edge:top0")
FRONT = handle_of(S, "pr:plane:front")
HOLE = handle_of(S, "pr:feat:hole")
SRC = Path(__file__).parents[1] / "src"
WINDOWS = sys.platform == "win32"


def plan(*steps, goal=""):
    return parse(plan_json(*steps), goal=goal, summary=S)


# --------------------------------------------------------------------------- the gate
def test_adding_and_shaping_and_said_dimensions_start_by_themselves():
    p = plan(
        step("set_dimension", dimension=WIDTH, value=mm(45)),
        step(
            "sketch_extrude_boss",
            plane=FRONT,
            profile=square(5),
            depth=mm(3),
            direction="normal",
            end="blind",
        ),
        step("fillet", edges=[EDGE], radius=mm(1)),
        step("shell", faces=[], thickness=mm(2)),
        step("linear_pattern", seeds=[HOLE], direction=EDGE, spacing=mm(5), count=3),
        goal="make it 45 mm wide, add a boss, round an edge and shell it",
    )
    gate = confirmation(p)
    assert not gate.waits and gate.reasons == ()


@pytest.mark.parametrize(
    "the_step, words",
    [
        (step("set_dimension", dimension=WIDTH, value=mm(46)), "a value you did not say"),
        (step("suppress", features=[HOLE]), "suppressed"),
        (step("unsuppress", features=[HOLE]), "suppressed"),
        (step("set_property", name="Description", value="Lid", scope="file"), "custom property Description"),
    ],
)
def test_overwrites_the_goal_did_not_spell_out_wait_for_run(the_step, words):
    gate = confirmation(plan(the_step, goal="make it 45 mm wide"))
    assert gate.waits and words in gate.reasons[0]


def test_always_confirm_makes_every_plan_wait():
    gate = confirmation(said_plan(), always_confirm=True)
    assert gate.waits and "Always confirm" in gate.reasons[0]


# --------------------------------------------------------------------------- start_run
def test_a_run_that_passes_every_check_starts(tmp_path):
    target = FakeTarget()
    run = start_run(target, said_plan(), runs_folder=str(tmp_path))
    try:
        assert target.calls[:3] == ["kind", "problem", ("unresolved", ("pr:dim:width",))]
        assert target.calls[3] == ("checkpoint", run.checkpoint)
        assert os.path.dirname(run.checkpoint) == run.folder and os.path.dirname(run.folder) == str(tmp_path)
        assert os.path.basename(run.checkpoint) == f"checkpoint-{run.run_id}.sldprt"
        assert os.path.getsize(run.checkpoint) > 0 and run.writer.held
        with pytest.raises(RunRefused) as info:
            start_run(FakeTarget(pid=target.sw_pid), said_plan(), runs_folder=str(tmp_path))
        assert info.value.code == "busy" and str(info.value) == BUSY_MESSAGE
    finally:
        run.release()
    assert not run.writer.held
    start_run(FakeTarget(pid=target.sw_pid), said_plan(), runs_folder=str(tmp_path)).release()


@pytest.mark.parametrize(
    "target_kw, plan_kw, code, message",
    [
        ({"kind": "assembly"}, {}, "not_a_part", "assemblies and drawings are refused"),
        ({"kind": "drawing"}, {}, "not_a_part", "one part"),
        ({"problem": "A sketch is open for editing."}, {}, "document_state", "sketch is open"),
        ({"unresolved": ["pr:dim:width"]}, {}, "changed", CHANGED_MESSAGE),
        ({"checkpoint": None}, {}, "checkpoint", "safety copy"),
        ({"checkpoint": b""}, {}, "checkpoint", "safety copy"),
        ({"checkpoint": OSError("disk full")}, {}, "checkpoint", "safety copy"),
        ({}, {"always_confirm": True}, "unconfirmed", "press Run"),
    ],
)
def test_each_check_refuses_and_gives_the_session_back(target_kw, plan_kw, code, message, tmp_path):
    target = FakeTarget(**target_kw)
    with pytest.raises(RunRefused) as info:
        start_run(target, said_plan(), runs_folder=str(tmp_path), **plan_kw)
    assert info.value.code == code and message in str(info.value)
    take_writer(target.sw_pid).release()  # the refused run did not keep the session
    assert os.listdir(tmp_path) == [], "a refused run leaves no run folder behind"


def test_the_checks_run_in_the_designed_order(tmp_path):
    target = FakeTarget(kind="assembly", problem="busy", unresolved=["pr:dim:width"])
    with pytest.raises(RunRefused) as info:
        start_run(target, said_plan(), runs_folder=str(tmp_path))
    assert info.value.code == "not_a_part" and target.calls == ["kind"]
    target = FakeTarget(problem="busy", unresolved=["pr:dim:width"])
    with pytest.raises(RunRefused):
        start_run(target, said_plan(), runs_folder=str(tmp_path))
    assert target.calls == ["kind", "problem"]
    waits = plan(step("suppress", features=[HOLE]))
    target = FakeTarget(unresolved=["pr:feat:hole"])
    with pytest.raises(RunRefused) as info:
        start_run(target, waits, runs_folder=str(tmp_path))
    assert info.value.code == "unconfirmed" and target.calls == ["kind", "problem"]
    with pytest.raises(RunRefused) as info:
        start_run(target, waits, confirmed=True, runs_folder=str(tmp_path))
    assert info.value.code == "changed"
    assert not any(isinstance(c, tuple) and c[0] == "checkpoint" for c in target.calls)


def test_a_confirmed_plan_that_waits_starts(tmp_path):
    waits = plan(step("set_property", name="Description", value="Lid", scope="file"))
    start_run(FakeTarget(), waits, confirmed=True, runs_folder=str(tmp_path)).release()


@pytest.mark.parametrize("bad", [None, "plan", object()])
def test_without_a_valid_plan_nothing_starts(bad, tmp_path):
    with pytest.raises(RunRefused) as info:
        start_run(FakeTarget(), bad, runs_folder=str(tmp_path))
    assert info.value.code == "no_plan"


def test_the_policy_is_read_fresh_before_anything_else(policy_reader, tmp_path):
    policy_reader(Policy(automatic_disabled=True, locked=True))
    target = FakeTarget()
    with pytest.raises(RunRefused) as info:
        start_run(target, said_plan(), runs_folder=str(tmp_path))
    assert info.value.code == "policy_refused" and "administrator" in str(info.value)
    assert target.calls == [] and os.listdir(tmp_path) == []
    take_writer(target.sw_pid).release()


def test_run_folders_default_to_the_solidseas_folder(tmp_path):
    run = start_run(FakeTarget(), said_plan())
    try:
        assert os.path.dirname(run.folder) == os.path.join(os.environ["SOLIDSEAS_CACHE_DIR"], "runs")
    finally:
        run.release()


# --------------------------------------------------------------------------- one writer per session
def test_one_writer_per_session():
    pid = 3_999_999_001
    with take_writer(pid) as hold:
        with pytest.raises(WriterBusyError):
            take_writer(pid)
        take_writer(pid + 1).release()  # another session is free
        assert hold.held
    assert not hold.held
    take_writer(pid).release()
    hold.release()  # twice does nothing


@pytest.mark.parametrize("pid", [0, -1, 2**32, 1.5, "123", True])
def test_bad_process_ids_are_refused(pid):
    with pytest.raises(ValueError):
        mutex_name(pid)


def test_the_mutex_name_is_the_designed_one():
    assert mutex_name(1234) == "Local\\SolidSeas-Live-1234"


@pytest.mark.skipif(not WINDOWS, reason="the named mutex is Windows only")
def test_another_process_holding_the_session_refuses_this_one():
    pid = 3_999_999_002
    code = (
        "import sys\n"
        "from solidseas_app.assistant.writer import take_writer\n"
        f"h = take_writer({pid})\n"
        "print('held', flush=True)\n"
        "sys.stdin.readline()\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
    )
    try:
        assert child.stdout.readline().strip() == b"held"
        with pytest.raises(WriterBusyError):
            take_writer(pid)
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    take_writer(pid).release()  # the session is free again once that process ended


def test_off_windows_a_set_in_this_process_stands_in(monkeypatch):
    monkeypatch.setattr(writer.sys, "platform", "linux")
    pid = 3_999_999_003
    with take_writer(pid):
        with pytest.raises(WriterBusyError):
            take_writer(pid)
    take_writer(pid).release()


# --------------------------------------------------------------------------- old run folders
DAY = 24 * 3600
LATER = DAY * (automatic.KEEP_DAYS + 1)  # how far past now a clean looks, to make folders old


def ended_run(root, run_id="20261001-120000-0123abcd", *, ended=True):
    """A run folder as a run leaves it: the safety copy, two copies after steps, the journal
    (ending with Keep when ``ended``) and the lock file, closed."""
    folder = root / run_id
    folder.mkdir(parents=True)
    (folder / f"checkpoint-{run_id}.sldprt").write_bytes(b"copy")
    (folder / f"checkpoint-{run_id}-step-1.sldprt").write_bytes(b"step 1")
    (folder / f"checkpoint-{run_id}-step-2.sldprt").write_bytes(b"step 2")
    events = ["run_started", "run_ended"] + (["kept"] if ended else [])
    (folder / "journal.jsonl").write_text("".join(f'{{"event": "{e}"}}\n' for e in events), encoding="utf-8")
    (folder / automatic.LOCK_NAME).write_bytes(b"")
    return folder


def contents(folder) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_run_folder_goes_once_nothing_in_it_changed_for_a_week(tmp_path):
    folder = ended_run(tmp_path)
    before = contents(folder)
    now = time.time()
    assert automatic.clean_old_runs(str(tmp_path), now=now + DAY * 6) == 0  # six days: it stays
    assert contents(folder) == before
    assert automatic.clean_old_runs(str(tmp_path), now=now + LATER) == 1
    assert not folder.exists() and list(tmp_path.iterdir()) == []


def test_the_week_starts_at_the_last_change_in_the_folder(tmp_path):
    folder = ended_run(tmp_path)
    old = time.time() - LATER
    for p in folder.iterdir():
        os.utime(p, (old, old))
    os.utime(folder, (old, old))
    os.utime(folder / "journal.jsonl")  # Keep pressed just now, on a run made long ago
    assert automatic.clean_old_runs(str(tmp_path)) == 0 and folder.exists()


def test_an_open_run_keeps_its_folder_however_old(tmp_path):
    run = start_run(FakeTarget(), said_plan(), runs_folder=str(tmp_path))
    try:
        assert os.path.isfile(os.path.join(run.folder, automatic.LOCK_NAME))
        assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER * 10) == 0
        assert os.path.isfile(run.checkpoint)
    finally:
        run.release()
    assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 1
    assert not os.path.exists(run.folder)


def test_an_open_run_whose_lock_could_not_be_taken_is_still_kept_here(tmp_path):
    folder = ended_run(tmp_path)  # run.lock is there, so the hold cannot make its own
    hold = automatic.RunHold(str(folder))
    try:
        assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 0
    finally:
        hold.release()
    assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 1


def test_a_run_another_process_holds_keeps_its_folder_until_that_process_ends(tmp_path):
    folder = tmp_path / "20261001-120000-00c0ffee"
    folder.mkdir()
    (folder / "checkpoint-20261001-120000-00c0ffee.sldprt").write_bytes(b"copy")
    code = (
        "import sys\n"
        "from solidseas_app.assistant.automatic import RunHold\n"
        f"h = RunHold({str(folder)!r})\n"
        "print('held', flush=True)\n"
        "sys.stdin.readline()\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
    )
    try:
        assert child.stdout.readline().strip() == b"held"
        assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 0
        assert contents(folder) == ["checkpoint-20261001-120000-00c0ffee.sldprt", automatic.LOCK_NAME]
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    # The process ended without Keep or Revert: its folder goes a week after its last change.
    assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 1
    assert not folder.exists()


def test_a_copy_that_cannot_be_removed_keeps_the_folder_whole(tmp_path, monkeypatch):
    folder = ended_run(tmp_path)
    before = contents(folder)
    real_remove = os.remove

    def remove(path, *a, **kw):
        if str(path).endswith("-step-2.sldprt"):
            raise PermissionError(13, "open in SOLIDWORKS", str(path))
        return real_remove(path, *a, **kw)

    monkeypatch.setattr(os, "remove", remove)
    assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 0
    assert "journal.jsonl" in contents(folder) and automatic.LOCK_NAME in contents(folder)
    monkeypatch.setattr(os, "remove", real_remove)
    assert set(contents(folder)) < set(before)  # the copies before the open one went
    assert automatic.clean_old_runs(str(tmp_path), now=time.time() + LATER) == 1  # closed: all of it goes


def test_only_run_folders_directly_in_the_runs_folder_are_looked_at(tmp_path):
    root = tmp_path / "runs"
    run = ended_run(root)
    for name in ("notes", "20261001-120000-4567ABCD", "20261001-1200-0123abcd", "x20261001-120000-0123abcd"):
        (root / name).mkdir()
        (root / name / "keep.txt").write_text("mine")
    (root / "20261001-120000-0000000f").write_text("a file named like a run")
    deeper = ended_run(root / "20261001-120000-00000010" / "inside", "20261001-120000-00000011")
    nested = ended_run(root / "20261001-120000-00000012", "20261001-120000-00000013")
    assert automatic.clean_old_runs(str(root), now=time.time() + LATER) == 1
    assert not run.exists()
    for name in ("notes", "20261001-120000-4567ABCD", "20261001-1200-0123abcd", "x20261001-120000-0123abcd"):
        assert (root / name / "keep.txt").read_text() == "mine"
    assert (root / "20261001-120000-0000000f").read_text() == "a file named like a run"
    assert contents(deeper) and contents(nested)  # a folder holding a folder is not a run's: it stays


def _link_or_skip(target, link, *, folder: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=folder)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symbolic links cannot be made here: {exc}")


def test_a_link_in_the_runs_folder_is_never_followed(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = ended_run(tmp_path / "elsewhere")
    before = contents(outside)
    link = root / outside.name
    _link_or_skip(outside, link, folder=True)
    assert automatic.clean_old_runs(str(root), now=time.time() + LATER) == 0
    assert contents(outside) == before and os.path.islink(link)


def test_a_run_folder_holding_a_link_is_left_alone(tmp_path):
    root = tmp_path / "runs"
    folder = ended_run(root)
    precious = tmp_path / "precious.sldprt"
    precious.write_bytes(b"the person's part")
    _link_or_skip(precious, folder / "checkpoint-extra.sldprt", folder=False)
    before = contents(folder)
    assert automatic.clean_old_runs(str(root), now=time.time() + LATER) == 0
    assert contents(folder) == before and precious.read_bytes() == b"the person's part"


@pytest.mark.skipif(not WINDOWS, reason="junctions are Windows only")
def test_a_junction_in_the_runs_folder_is_never_followed(tmp_path):
    import _winapi

    root = tmp_path / "runs"
    root.mkdir()
    outside = ended_run(tmp_path / "elsewhere")
    before = contents(outside)
    _winapi.CreateJunction(str(outside), str(root / outside.name))
    assert automatic.clean_old_runs(str(root), now=time.time() + LATER) == 0
    assert contents(outside) == before


def test_a_runs_folder_that_is_not_there_is_nothing_to_clean(tmp_path):
    assert automatic.clean_old_runs(str(tmp_path / "missing"), now=time.time() + LATER) == 0


def test_cleaning_on_its_own_thread_uses_the_runs_folder(tmp_path, monkeypatch):
    folder = ended_run(tmp_path / "runs")
    old = time.time() - LATER
    for p in folder.iterdir():
        os.utime(p, (old, old))
    os.utime(folder, (old, old))
    monkeypatch.setattr(automatic, "runs_dir", lambda: str(tmp_path / "runs"))
    automatic.clean_old_runs_later().join(timeout=30)
    assert not folder.exists()
