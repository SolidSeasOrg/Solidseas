"""A service process for the shutdown test: one root, a worker whose document job sleeps
for any file named ``slow``, the shutdown path the CLI uses. Prints its port, then serves
until it is signalled. Not a test module: the test runs it as a child process."""

import sys

from serve_support import TOKEN
from solidseas import Root, Roots
from solidseas.serve import ServeConfig, Server, configure_logging, run_until_signalled
from solidseas.workers import WorkerPool

if __name__ == "__main__":
    pool = WorkerPool(1, jobs={"document_summary": "worker_jobs:document_summary"}, reader_message=False)
    config = ServeConfig(
        roots=Roots([Root("a", sys.argv[1])]),
        tokens={"tests": TOKEN},
        port=0,
        workers=1,
        deadlines={"document": 60.0},
        shutdown_budget_s=5.0,
    )
    server = Server(config, pool=pool)
    server.start()
    server.wait_ready(60)
    configure_logging()
    sys.stdout.write(f"{server.port}\n")
    sys.stdout.flush()
    run_until_signalled(server)
