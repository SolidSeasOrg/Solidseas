"""The worker pool: JSON in and out, a deadline per job with the worker killed, joined
and only then replaced, a crash reported as ``worker_crashed``, a memory cap through a
Windows Job Object or ``RLIMIT_AS``, and results that are never unpickled."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from serve_support import wait_for
from solidseas import model, workers
from solidseas.errors import InvalidArgumentError, WorkerCrashedError, WorkerJobError, WorkerTimeoutError
from solidseas.formats.solidworks import open_document
from solidseas.listing import scan
from support import fixture_path

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
O02 = fixture_path("o02_boxA.SLDPRT")
O04 = fixture_path("o04_boxA_props.SLDPRT")
O06 = fixture_path("o06_boxA_props_mat_cfg.SLDPRT")
TEST_JOBS = {
    name: f"worker_jobs:{name}"
    for name in ("echo", "pid", "sleep", "crash", "allocate", "big", "nan", "image", "spawn", "error_mode")
}


@pytest.fixture(scope="module")
def pool():
    with workers.WorkerPool(2, timeout_s=30, jobs=TEST_JOBS) as p:
        yield p


def _replaced(pool, old_pid: int) -> int:
    """The pid that replaced ``old_pid``, once the pool has started it."""
    found: list[int] = []

    def done() -> bool:
        found[:] = [e[2] for e in list(pool.events) if e[0] == "replaced" and e[1] == old_pid]
        return bool(found)

    assert wait_for(done, 60), list(pool.events)
    return found[0]


# --------------------------------------------------------------------------- JSON jobs
def test_jobs_take_and_return_json(pool):
    r = pool.call("echo", {"a": [1, 2.5, "ü", None, True]})
    assert r.data["echo"] == {"a": [1, 2.5, "ü", None, True]} and r.payload is None
    info = pool.worker_info()
    assert len(info) == 2 and len({w["pid"] for w in info}) == 2
    assert os.getpid() not in {w["pid"] for w in info}  # the jobs run in other processes
    r = pool.call("image", {"n": 10})
    assert r.data == {"bytes": 10} and r.payload == b"\x89PNG\r\n\x1a\n" + bytes(10)


def test_a_document_job_gives_the_builders_data(pool):
    r = pool.call("document_summary", {"path": str(O04)})
    with open_document(O04) as doc:
        assert r.data == model.build_document_summary(doc)  # the same builder, the same data


def test_a_failed_job_comes_back_as_its_error_object(pool, tmp_path):
    bogus = tmp_path / "bogus.SLDPRT"
    bogus.write_bytes(b"ISO-10303-21;\n")
    with pytest.raises(WorkerJobError) as caught:
        pool.call("document_summary", {"path": str(bogus)})
    info = model.error_info(caught.value)
    assert (info["code"], info["exception"]) == ("unknown_format", "UnknownFormatError")
    with open_document(O06) as doc:
        try:
            model.build_properties(doc, configuration="nope")
        except Exception as exc:  # the same failure, in this process
            local = model.error_info(exc)
    with pytest.raises(WorkerJobError) as caught:
        pool.call("properties", {"path": str(O06), "configuration": "nope"})
    assert model.error_info(caught.value) == local
    with pytest.raises(WorkerJobError) as caught:
        pool.call("no_such_job", {})
    assert caught.value.code == "invalid_argument"


def test_the_pool_runs_envelopes(pool):
    env = pool.run("document_summary", O04)
    with open_document(O04) as doc:
        assert env == model.envelope("document_summary", model.build_document_summary(doc))
    env = pool.run("properties", O06, configuration="nope")
    assert not env["ok"] and env["error"]["code"] == "configuration_not_found"


def test_a_non_json_result_is_refused_in_the_worker(pool):
    with pytest.raises(WorkerJobError) as caught:
        pool.call("nan", {})
    assert caught.value.code == "internal"  # the strict encoder refused NaN before it was sent
    assert pool.call("echo", {}).data["echo"] == {}  # the worker lives on


def test_reader_messages_can_be_left_out(tmp_path):
    bogus = tmp_path / "bogus.SLDPRT"
    bogus.write_bytes(b"\x00" * 64)
    with workers.WorkerPool(1, reader_message=False) as quiet:
        with pytest.raises(WorkerJobError) as caught:
            quiet.call("document_summary", {"path": str(bogus)})
    info = model.error_info(caught.value)
    assert info["reader_message"] is None and info["code"] in ("unknown_format", "damaged_file")


# --------------------------------------------------------------------------- deadlines and crashes
def test_a_slow_job_times_out_and_its_worker_is_killed_joined_and_replaced():
    with workers.WorkerPool(1, timeout_s=30, jobs=TEST_JOBS) as p:
        (old,) = [w["pid"] for w in p.worker_info()]
        start = time.monotonic()
        with pytest.raises(WorkerTimeoutError):
            p.call("sleep", {"seconds": 120}, timeout=1.0)
        assert time.monotonic() - start < 6
        new = _replaced(p, old)
        assert new != old
        events = list(p.events)
        joined = next(i for i, e in enumerate(events) if e[0] == "joined" and e[1] == old)
        started = next(i for i, e in enumerate(events) if e[0] == "started" and e[1] == new)
        assert events[joined][3] is False  # the old worker had ended...
        assert joined < started  # ...before its replacement started (critique 3.15)
        # and the first try worked: a replacement started too early is turned away by the
        # Job Object's active-process limit and retried, which the order above cannot show
        assert [e for e in events if e[0] in ("assign_failed", "replace_retry", "replace_failed")] == []
        assert ("killed", old, "timeout") in events
        assert p.call("pid", {}).data["pid"] == new  # and the pool works on


def test_waiting_for_a_free_worker_counts_toward_the_deadline():
    with workers.WorkerPool(1, timeout_s=30, jobs=TEST_JOBS) as p:
        (busy,) = [w["pid"] for w in p.worker_info()]
        hold = threading.Thread(target=lambda: _swallow(p.call, "sleep", {"seconds": 120}, timeout=60))
        hold.start()
        time.sleep(0.5)  # the only worker is now asleep
        start = time.monotonic()
        with pytest.raises(WorkerTimeoutError) as err:
            p.call("pid", {}, timeout=1.0)
        assert time.monotonic() - start < 3
        assert err.value.detail == {"rule": "no_free_worker"}  # no job was sent: the file was never tried
        assert ("killed", busy, "timeout") not in list(p.events)  # the busy worker was left alone
    hold.join(15)


def _swallow(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        pass


@pytest.mark.skipif(not WINDOWS, reason="SetErrorMode is a Windows call")
def test_a_worker_never_shows_an_error_dialog():
    import ctypes

    kernel32 = ctypes.windll.kernel32
    # A child inherits its parent's error mode, and a CI runner may already set these
    # flags, so clear them here first: the worker must then set them itself.
    old = kernel32.SetErrorMode(0)
    try:
        assert kernel32.GetErrorMode() & 0x8003 != 0x8003  # control: this process differs
        with workers.WorkerPool(1, jobs=TEST_JOBS) as p:
            # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX, read in the worker
            assert p.call("error_mode", {}).data["error_mode"] & 0x8003 == 0x8003
    finally:
        kernel32.SetErrorMode(old)


def test_a_crash_is_worker_crashed_and_the_pool_carries_on():
    with workers.WorkerPool(1, jobs=TEST_JOBS) as p:
        (old,) = [w["pid"] for w in p.worker_info()]
        with pytest.raises(WorkerCrashedError):
            p.call("crash", {})
        new = _replaced(p, old)
        assert p.call("pid", {}).data["pid"] == new != old


def _frames_read(monkeypatch) -> list[int]:
    """The length of every frame the pool parses in this process."""
    sizes: list[int] = []
    real = workers._loads

    def loads(raw):
        sizes.append(len(raw))
        return real(raw)

    monkeypatch.setattr(workers, "_loads", loads)
    return sizes


def test_a_reply_over_the_cap_is_refused_in_the_worker(monkeypatch):
    """The worker refuses an over-long answer itself: nothing that long crosses the pipe or is
    parsed here, and the worker lives on. A call may lower the pool's cap for itself."""
    with workers.WorkerPool(1, max_result_bytes=10_000, jobs=TEST_JOBS) as p:
        (old,) = [w["pid"] for w in p.worker_info()]
        sizes = _frames_read(monkeypatch)
        assert len(p.call("big", {"n": 1000}).data["text"]) == 1000
        with pytest.raises(WorkerJobError) as caught:
            p.call("big", {"n": 50_000})
        assert (caught.value.code, caught.value.detail) == ("response_too_large", {"limit": 10_000})
        with pytest.raises(WorkerJobError) as caught:
            p.call("big", {"n": 3000}, max_result_bytes=2000)  # this call's own, lower cap
        assert (caught.value.code, caught.value.detail) == ("response_too_large", {"limit": 2000})
        assert len(p.call("big", {"n": 3000}).data["text"]) == 3000  # control: within the pool's cap
        assert max(sizes) < 10_000 and len(sizes) == 4
        assert p.call("pid", {}).data["pid"] == old  # the same worker answered throughout


def test_a_worker_that_sends_too_much_anyway_is_not_read_and_is_replaced(monkeypatch):
    """The pipe's own limit is the guard: a worker that ignores the cap it was told (made to
    here by telling it none) is cut off at the pipe and replaced."""

    class _NoLimitTold:
        loads = staticmethod(json.loads)

        @staticmethod
        def dumps(obj, **kwargs):
            if isinstance(obj, dict) and "limit" in obj:
                obj = {**obj, "limit": None}
            return json.dumps(obj, **kwargs)

    with workers.WorkerPool(1, max_result_bytes=10_000, jobs=TEST_JOBS) as p:
        (old,) = [w["pid"] for w in p.worker_info()]
        monkeypatch.setattr(workers, "json", _NoLimitTold)
        sizes = _frames_read(monkeypatch)
        with pytest.raises(WorkerJobError) as caught:
            p.call("big", {"n": 50_000})
        assert caught.value.code == "response_too_large"
        assert sizes == [] and _replaced(p, old) != old


def test_a_lost_worker_is_replaced_even_after_failed_starts(monkeypatch):
    """A replacement that fails to start (memory pressure, a slow start) is tried again with a
    growing wait for as long as the pool is open, so the pool never shrinks for good; each
    event is logged."""
    monkeypatch.setattr(workers, "RETRY_FIRST_S", 0.05)
    log = logging.getLogger("tests.pool")
    lines: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        with workers.WorkerPool(1, jobs=TEST_JOBS, log=log) as p:
            (old,) = [w["pid"] for w in p.worker_info()]
            real, failing = p._spawn, {"left": 4}

            def flaky():
                if failing["left"]:
                    failing["left"] -= 1
                    raise OSError(1455, "the paging file is too small for this operation to complete")
                return real()

            p._spawn = flaky
            with pytest.raises(WorkerCrashedError):
                p.call("crash", {})
            new = _replaced(p, old)
            assert p.call("pid", {}).data["pid"] == new != old and p.alive() == 1
            assert len([e for e in p.events if e[0] == "replace_retry"]) == 4
    finally:
        log.removeHandler(handler)
    assert sum("event=replace_retry" in line for line in lines) == 4
    assert any(line.startswith("pool event=replaced") and line.endswith("workers=1") for line in lines)


def test_a_replacement_waits_until_the_worker_it_replaces_has_ended():
    """A killed worker stuck in I/O may outlive the join: its replacement must not start
    before it ends, or the Job Object's active-process limit would end the replacement."""

    class _Stuck:
        def __init__(self) -> None:
            self.exitcode = None
            self.joins = 0

        def join(self, timeout=None) -> None:
            self.joins += 1
            if self.joins == 2:
                self.exitcode = -9

        def is_alive(self) -> bool:
            return self.exitcode is None

    with workers.WorkerPool(1, jobs=TEST_JOBS) as p:
        p._kill(p._idle.get(timeout=5), "test")  # its one worker gone: room for the replacement
        stuck = _Stuck()
        old = type("Old", (), {"proc": stuck, "pid": 999_999})()
        real, at_spawn = p._spawn, []

        def spawn():
            at_spawn.append(stuck.exitcode)
            return real()

        p._spawn = spawn
        p._replace_later(old)
        _replaced(p, 999_999)
        assert at_spawn == [-9] and stuck.joins == 2
        assert len([e for e in p.events if e == ("replace_waiting", 999_999)]) == 2


MAIN_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
from solidseas.workers import WorkerPool

def make():
    try:
        with WorkerPool(1, start_timeout_s=60) as pool:
            print("started", pool.alive(), flush=True)
    except Exception as exc:
        if __name__ == "__main__":
            print("refused", type(exc).__name__, exc, flush=True)
        raise
{body}
"""


@pytest.mark.parametrize("guarded", [False, True], ids=["no_main_guard", "main_guard"])
def test_a_script_without_a_main_guard_is_told_why_its_workers_failed(tmp_path, guarded):
    """Workers start with spawn, which runs the main module again in each worker: without
    ``if __name__ == "__main__":`` each worker fails as it starts, and the error says why."""
    src = str(Path(workers.__file__).resolve().parents[1])
    body = 'if __name__ == "__main__":\n    make()\n' if guarded else "make()\n"
    script = tmp_path / "pool_script.py"
    script.write_text(MAIN_SCRIPT.format(src=src, body=body), encoding="utf-8")
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=180)
    out = done.stdout.strip().splitlines()
    if guarded:
        assert out == ["started 1"], done.stderr[-2000:]
    else:
        assert out and out[-1].startswith("refused WorkerCrashedError"), (out, done.stderr[-2000:])
        assert 'if __name__ == "__main__":' in out[-1]


def test_closing_the_pool_ends_a_call_still_waiting():
    p = workers.WorkerPool(1, jobs=TEST_JOBS)
    errors = []

    def wait():
        try:
            p.call("sleep", {"seconds": 120}, timeout=60)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.5)
    start = time.monotonic()
    p.close()
    t.join(15)
    assert not t.is_alive() and time.monotonic() - start < 10
    assert len(errors) == 1 and isinstance(errors[0], WorkerCrashedError)
    with pytest.raises(WorkerCrashedError):
        p.call("echo", {})
    assert p.worker_info() == []


# --------------------------------------------------------------------------- limits
@pytest.mark.skipif(not WINDOWS, reason="the Job Object is the Windows memory cap")
def test_a_memory_bomb_is_contained_by_the_job_object():
    with workers.WorkerPool(1, memory_mb=256, jobs=TEST_JOBS) as capped:
        assert all(w["in_job"] for w in capped.worker_info())
        with pytest.raises(WorkerJobError) as caught:
            capped.call("allocate", {"mb": 1024})
        assert caught.value.code == "limit_exceeded" and caught.value.detail == {"limit": "memory"}
        assert capped.call("allocate", {"mb": 16}).data == {"bytes": 16 << 20}  # it lives on
    with workers.WorkerPool(1, memory_mb=None, jobs=TEST_JOBS) as uncapped:  # control: the cap did it
        assert uncapped.call("allocate", {"mb": 1024}).data == {"bytes": 1024 << 20}


@pytest.mark.skipif(not LINUX, reason="RLIMIT_AS is the Linux memory cap")
def test_a_memory_bomb_is_contained_by_rlimit_as():  # pragma: no cover - Linux only
    with workers.WorkerPool(1, memory_mb=512, jobs=TEST_JOBS) as capped:
        (info,) = capped.worker_info()
        assert info["limits"]["rlimit_as"] == 512 << 20 and info["limits"]["pdeathsig"] is True
        with pytest.raises(WorkerJobError) as caught:
            capped.call("allocate", {"mb": 2048})
        assert caught.value.code == "limit_exceeded"
        assert capped.call("allocate", {"mb": 16}).data == {"bytes": 16 << 20}
    with workers.WorkerPool(1, memory_mb=None, jobs=TEST_JOBS) as uncapped:  # control: the cap did it
        assert uncapped.call("allocate", {"mb": 1024}).data == {"bytes": 1024 << 20}


@pytest.mark.skipif(not WINDOWS, reason="the Job Object's active-process limit")
def test_a_worker_cannot_start_another_process():
    with workers.WorkerPool(1, jobs=TEST_JOBS) as p:
        assert p.call("spawn", {}).data == {"spawned": False}
    from worker_jobs import spawn

    assert spawn({}) == {"spawned": True}  # control: outside the job the same code starts one


# --------------------------------------------------------------------------- what a job may open
def test_document_jobs_stay_inside_the_pools_roots(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir()
    outside.mkdir()
    shutil.copy2(O02, inside / "a.SLDPRT")
    shutil.copy2(O02, outside / "b.SLDPRT")
    with workers.WorkerPool(1, roots=[str(inside)]) as p:
        assert p.call("configurations", {"path": str(inside / "a.SLDPRT"), "within": str(inside)}).data
        for params in (
            {"path": str(outside / "b.SLDPRT"), "within": str(outside)},
            {"path": str(outside / "b.SLDPRT")},
        ):
            with pytest.raises(WorkerJobError) as caught:
                p.call("configurations", params)
            assert (caught.value.code, caught.value.detail) == ("path_refused", {"rule": "outside_roots"})
        with pytest.raises(WorkerJobError) as caught:  # within the root, but the file is not below it
            p.call("configurations", {"path": str(outside / "b.SLDPRT"), "within": str(inside)})
        assert caught.value.detail == {"rule": "escapes_root"}


def test_hard_links_can_be_refused(tmp_path):
    shutil.copy2(O02, tmp_path / "a.SLDPRT")
    try:
        os.link(tmp_path / "a.SLDPRT", tmp_path / "b.SLDPRT")
    except OSError:
        pytest.skip("hard links are not supported here")
    shutil.copy2(O02, tmp_path / "c.SLDPRT")
    with workers.WorkerPool(1, refuse_hard_links=True) as p:
        with pytest.raises(WorkerJobError) as caught:
            p.call("configurations", {"path": str(tmp_path / "b.SLDPRT")})
        assert (caught.value.code, caught.value.detail) == ("link_refused", {"rule": "hard_link"})
        assert p.call("configurations", {"path": str(tmp_path / "c.SLDPRT")}).data  # control


# --------------------------------------------------------------------------- a listing through the pool
def test_a_listing_with_a_pool_survives_slow_and_crashing_files(tmp_path):
    for name in ("a.SLDPRT", "crash.SLDPRT", "slow.SLDPRT", "z.SLDPRT"):
        shutil.copy2(O02, tmp_path / name)
    with workers.WorkerPool(2, jobs={"listing_entry": "worker_jobs:listing_entry"}) as p:
        listing = scan(tmp_path, pool=p, file_timeout=2.0, include=("properties", "preview")).listing()
    by_name = {e["path"]: e for e in listing["entries"]}
    assert set(by_name) == {"a.SLDPRT", "crash.SLDPRT", "slow.SLDPRT", "z.SLDPRT"}
    assert by_name["crash.SLDPRT"]["error"]["code"] == "worker_crashed"
    assert by_name["slow.SLDPRT"]["error"]["code"] == "timeout"
    assert by_name["a.SLDPRT"]["status"] == by_name["z.SLDPRT"]["status"] == "ok"
    assert listing["counts"]["error"] == 2 and listing["counts"]["ok"] == 2
    plain = {e["path"]: e for e in scan(tmp_path, include=("properties", "preview")).listing()["entries"]}
    assert by_name["a.SLDPRT"] == plain["a.SLDPRT"]  # the worker builds the same entry


# --------------------------------------------------------------------------- never unpickled
def _code_only(source: str) -> str:
    q = chr(34) * 3
    without_docstrings = re.sub(q + ".*?" + q, "", source, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in without_docstrings.split("\n"))


def test_worker_results_are_never_unpickled():
    src = Path(workers.__file__).read_text(encoding="utf-8")
    code = _code_only(src)
    assert "recv_bytes(" in code and "_loads(" in code and "json.loads(" in code  # the anchors exist
    assert re.findall(r"\.recv\(", code) == []  # Connection.recv() unpickles
    assert "pickle" not in code and "ProcessPoolExecutor" not in code and ".Pool(" not in code
    # nothing else in the service or the command line talks to a process: only the pool does
    for module in ("serve/server.py", "jobs.py", "listing.py", "cli.py"):
        other = _code_only((Path(workers.__file__).parent / module).read_text(encoding="utf-8"))
        assert "multiprocessing" not in other and "pickle" not in other, module
        assert "ProcessPoolExecutor" not in other and ".Pool(" not in other, module


def test_only_the_command_lines_pool_runs_the_job_that_writes(tmp_path):
    """batch_document writes a document's preview and Parasolid files. It is not in the
    default table, so a pool the service builds cannot run it; the CLI's pool adds it, and
    even there it reads only below the pool's roots."""
    from solidseas import cli

    src, other = tmp_path / "in", tmp_path / "other"
    src.mkdir()
    other.mkdir()
    shutil.copy2(O02, src / "a.SLDPRT")
    shutil.copy2(O02, other / "b.SLDPRT")
    opts = {"preview": True, "parasolid": True, "text": False, "max_bytes": 1 << 26}
    opts.update(allow_source_dir=False, force=False)
    assert "batch_document" not in workers.DEFAULT_JOBS
    with workers.WorkerPool(1) as p:  # the default table, as the service's pool has it
        with pytest.raises(WorkerJobError) as caught:
            params = {"path": str(src / "a.SLDPRT"), "folder": str(src), "out_dir": str(tmp_path / "o1")}
            p.call("batch_document", {**params, "opts": opts})
        assert caught.value.code == "invalid_argument"
    assert not (tmp_path / "o1").exists()
    with workers.WorkerPool(1, roots=[str(src)], jobs=cli.WORKER_JOBS) as p:
        params = {"path": str(other / "b.SLDPRT"), "folder": str(other), "out_dir": str(tmp_path / "o2")}
        with pytest.raises(WorkerJobError) as caught:
            p.call("batch_document", {**params, "opts": opts})
        assert (caught.value.code, caught.value.detail) == ("path_refused", {"rule": "outside_roots"})
        assert not (tmp_path / "o2").exists()
        params = {"path": str(src / "a.SLDPRT"), "folder": str(src), "out_dir": str(tmp_path / "o3")}
        row = p.call("batch_document", {**params, "opts": opts}).data["row"]  # control
        assert row["status"] == "ok" and (tmp_path / "o3" / "a.SLDPRT.png").exists()


def test_a_below_normal_pool_runs_its_workers_below_normal_priority():
    with workers.WorkerPool(1, priority="below_normal", jobs={"priority": "worker_jobs:priority"}) as p:
        got = p.call("priority").data
        assert p.priority == "below_normal"
    if os.name == "nt":
        assert got["class"] == 0x4000  # BELOW_NORMAL_PRIORITY_CLASS, from the Job Object
    else:
        assert got["nice"] >= 10
    with pytest.raises(InvalidArgumentError):
        workers.WorkerPool(1, priority="realtime")
