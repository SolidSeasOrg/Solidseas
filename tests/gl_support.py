"""Running the viewer's OpenGL code on the real display, from a test.

Qt's offscreen platform has no OpenGL on Windows, so the tests that draw run a
script in a child process on the real display. Such a test may skip only when
there is nothing to draw on: the Qt platform could not start (the script ends
before it says anything) or :func:`view3d.gl_status` says OpenGL is not there.
So every script starts with :data:`PREAMBLE`, which prints a marker line with
that answer before any other work, and :func:`run_gl` skips only without the
marker or on its "no". Once the marker says OpenGL works, a non-zero exit, a
traceback anywhere on stderr (PySide prints the ones raised in slots and goes
on) or a hang fails the test: a regression must not pass as a missing display.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parent.parent / "src")
MARKER = "SOLIDSEAS_GL_STATUS "
PREAMBLE = f"""
import json, sys
from PySide6.QtWidgets import QApplication
app = QApplication([])
from solidseas_app.viewer import view3d
ok, why = view3d.gl_status()
print({MARKER!r} + json.dumps({{"gl": ok, "why": why}}), flush=True)
if not ok:
    raise SystemExit(0)
"""


def display_env(**extra: str) -> dict[str, str]:
    """The environment of a child on the real display: without the offscreen platform."""
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PYTHONPATH"] = SRC
    env.update(extra)
    return env


def _status(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER) :])
    return None


def run_gl(script: str, *args: str, timeout: float = 180, env: dict[str, str] | None = None) -> dict:
    """Run :data:`PREAMBLE` then ``script`` (whose last line of output is its JSON result)
    with ``args``, and ``env`` added to the environment (``QT_SCALE_FACTOR``, say); the
    result, or a skip or a failure as the module docstring says."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", PREAMBLE + script, *args],
            env=display_env(**(env or {})),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        status = _status(out)
        if status is None:
            pytest.skip("the display did not answer in time")
        pytest.fail(f"the display script did not finish in {timeout:.0f} s after OpenGL started")
    status = _status(proc.stdout)
    if status is None:
        pytest.skip(f"no display to draw on here: {proc.stderr.strip()[-300:]}")
    if not status["gl"]:
        pytest.skip(f"OpenGL is not available here ({status['why']})")
    if proc.returncode != 0 or "Traceback" in proc.stderr:
        why = proc.stderr.strip()[-3000:]
        pytest.fail(f"the display script failed (exit code {proc.returncode}):\n{why}")
    lines = [line for line in proc.stdout.splitlines() if line.strip() and not line.startswith(MARKER)]
    if not lines:
        pytest.fail("the display script printed no result")
    return json.loads(lines[-1])


def run_self_test(args: list[str], shots: Path, *, appdata: Path, timeout: float = 300) -> dict:
    """Run the viewer's self-test with ``args`` on the real display and return its report.
    It skips when no report was written and nothing was raised (no display), or when the
    report says OpenGL is not available; a traceback fails the test."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "solidseas_app", *args],
            env=display_env(APPDATA=str(appdata)),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("the display did not answer in time")
    if "Traceback" in proc.stderr:
        pytest.fail(f"the self-test raised:\n{proc.stderr.strip()[-3000:]}")
    report_path = shots / "selftest.json"
    if not report_path.exists():
        pytest.skip(f"no display to draw on here: {proc.stderr.strip()[-300:]}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not (report.get("opengl") or {}).get("available"):
        pytest.skip("OpenGL is not available here")
    assert proc.returncode == 0 and report["ok"], report
    return report
