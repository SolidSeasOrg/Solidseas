"""SOLIDWORKS check: the native-writer check, in the person's own open SOLIDWORKS.

Run by the PC for a ``solidworks-check`` request with ``check`` = ``native-writer-attached``.
The person agreed on 2026-10-19, while SolidSeas' own instance could not start because
its licence was deactivated, that this check may run in their open session. It is
``native-writer.py`` with one difference: instead of starting a SOLIDWORKS it attaches,
through the ``SolidWorks_PID_<pid>`` moniker (``live_attach``), to the one reachable
SOLIDWORKS in this Windows session that SolidSeas did not start, and refuses when there
is none or more than one. In that session it only opens the candidate parts read-only
(refusing a name the session already has open), rebuilds and edits them in memory, saves
copies into this worktree and closes them unsaved (the bridge's ``--test-session``
operations). It never touches another document, imports nothing and never ends that
SOLIDWORKS.
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "native_writer_check", Path(__file__).with_name("native-writer.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

if __name__ == "__main__":
    raise SystemExit(_mod.main(attached=True))
