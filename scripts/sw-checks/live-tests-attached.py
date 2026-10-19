"""SOLIDWORKS check: the live-mode tests, in the person's own open SOLIDWORKS.

Run by the PC for a ``solidworks-check`` request with ``check`` = ``live-tests-attached``.
The person agreed on 2026-10-19 that the opt-in tests may use their open session while
SolidSeas' own instance cannot start. It finds the one reachable SOLIDWORKS in this
Windows session that SolidSeas did not start (refusing when there is none or more than
one), then runs ``tests/test_swapi_live.py`` with ``SOLIDSEAS_SWAPI_ATTACH_PID`` set to it:
each test makes its own new part from the template there, models in it and closes it
unsaved; nothing else in the session is touched, nothing is imported and that SOLIDWORKS
is never ended. It prints one JSON object of counts.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from solidseas.swapi.bridge import Bridge  # noqa: E402
from solidseas.swapi.build import build_bridge  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "native_writer_check", Path(__file__).with_name("native-writer.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

OUT = ROOT / "build" / "live-tests-attached"


def main() -> int:
    result: dict = {"check": "live-tests-attached"}
    if OUT.exists():
        print(json.dumps({**result, "error": "the output folder exists; run from a fresh worktree"}))
        return 2
    exe = build_bridge(OUT / "bridge")
    with Bridge(exe, test_session=True) as b:
        try:
            pid = _mod.person_session(b)
        except Exception as e:  # noqa: BLE001 - reported, not raised
            print(json.dumps({**result, "error": str(e)[:120]}))
            return 4
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "SOLIDSEAS_SWBRIDGE": str(exe),
        "SOLIDSEAS_SWAPI_ATTACH_PID": str(pid),
        "QT_QPA_PLATFORM": "offscreen",
    }
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_swapi_live.py", "-rfEs"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=3 * 3600,
    )
    tail = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed)", tail)}
    failing = [
        ln.split(" ", 1)[1].split(" - ")[0]
        for ln in run.stdout.splitlines()
        if ln.startswith(("FAILED ", "ERROR "))
    ]
    (OUT / "pytest.txt").write_text(run.stdout + "\n" + run.stderr, encoding="utf-8")
    print(
        json.dumps(
            {
                **result,
                "exit": run.returncode,
                "counts": counts,
                "failing": failing[:50],
                "log_file": "build/live-tests-attached/pytest.txt",
            }
        )
    )
    return 0 if run.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
