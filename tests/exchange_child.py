"""A second process for ``test_exchange``: it claims a request or writes requests on the
real file system, so races are between processes as they are between the two machines.
Not a test module: the tests run it as a child process.

Usage: ``exchange_child.py XCHG ROOT claim ID GO_FILE`` prints ``ready``, waits for
``GO_FILE`` to exist, claims, prints ``won`` (exit 0) or ``lost`` (exit 4).
``exchange_child.py XCHG ROOT write COUNT`` writes COUNT valid requests and prints their ids.
"""

import importlib.util
import json
import sys
import time
from pathlib import Path


def _load(path: str):
    spec = importlib.util.spec_from_file_location("xchg", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["xchg"] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    xchg_path, root, mode = sys.argv[1:4]
    xchg = _load(xchg_path)
    ex = xchg.Exchange(root)
    if mode == "claim":
        rid, go = sys.argv[4], Path(sys.argv[5])
        print("ready", flush=True)
        deadline = time.monotonic() + 60
        while not go.exists() and time.monotonic() < deadline:
            time.sleep(0.001)
        try:
            xchg.claim(ex, rid, who="racer")
        except xchg.Conflict:
            print("lost", flush=True)
            sys.exit(4)
        print("won", flush=True)
        sys.exit(0)
    if mode == "write":
        ids = []
        for _ in range(int(sys.argv[4])):
            obj = xchg.write_request(ex, kind="windows-tests", ref="main", commit="c" * 40, notes="n" * 1900)
            ids.append(obj["id"])
        print(json.dumps(ids), flush=True)
        sys.exit(0)
    sys.exit(2)
