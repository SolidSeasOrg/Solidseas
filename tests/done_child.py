"""Phase 1's "done when" in a fresh interpreter, for ``test_phase1_done``.

It lists a folder and reads an assembly's components through the CLI, then
does the same through a REST service with one worker, and prints one JSON line:
the exit codes, the HTTP statuses, and the modules loaded in this process and
in the worker. A fresh process is the only place to ask whether anything loaded
SOLIDWORKS automation: the test session imports it for its own tests. Not a test
module: the test runs it as a child process.
"""

import contextlib
import io
import json
import sys

from serve_support import Running
from solidseas import cli
from solidseas.workers import WorkerPool

if __name__ == "__main__":
    folder, assembly, part = sys.argv[1:4]
    with contextlib.redirect_stdout(io.StringIO()):
        codes = [
            cli.main(["list", folder, "--include", "properties", "--json"]),
            cli.main(["components", f"{folder}/{assembly}", "--json"]),
            cli.main(["props", f"{folder}/{part}", "--json"]),
        ]
    pool = WorkerPool(
        1,
        roots=[folder],
        reader_message=False,
        refuse_hard_links=True,
        jobs={"modules": "worker_jobs:modules"},
    )
    running = Running({"jobs": folder}, pool=pool)
    try:
        statuses = [
            running.get("list", root="jobs", include="properties,preview").status,
            running.get("components", root="jobs", path=assembly).status,
            running.get("preview", root="jobs", path=part).status,
        ]
        worker = pool.call("modules", {}).data["modules"]
    finally:
        running.close()
    result = {"codes": codes, "statuses": statuses, "process": sorted(sys.modules), "worker": worker}
    print(json.dumps(result))
