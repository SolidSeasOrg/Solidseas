"""SolidCraft in the chat (``docs/EXTENSIONS.md`` section 9): the SolidCraft extension's
tools, as SolidSeas' MCP server lists them while the extension is on.

SolidCraft is a free parametric CAD program (MIT or Apache-2.0); its package carries
``solidcraft-cli.exe``, whose ``mcp`` command is an MCP server that models, measures,
takes screenshots and exports without a window. :class:`SolidCraft` starts it as the
extension's helper (:func:`solidseas_app.extensions.start_helper` with
:class:`solidseas.helpers.McpHelper`: the package checked again, a Job Object, a memory
cap, a timeout on every call), lists its tools under :data:`PREFIX`, and passes each call
on. Its files stay in one folder of SolidSeas' own, :func:`workspace`: SolidCraft is
started with that folder alone (``--allow-path``) and refuses the rest, and every path a
call names is checked here first too, so SolidCraft never reads or writes beside a
SOLIDWORKS file. ``crash_reports``, which can show paths from anywhere on the PC, is not
listed.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

from . import data_dir, read_state, start_helper

PREFIX = "solidcraft_"
LEFT_OUT = frozenset({"crash_reports"})
PATH_KEYS = ("path", "in", "out", "file", "directory", "folder")
CALL_SECONDS = 600.0
INSTRUCTIONS = """SolidCraft, a free parametric CAD program, is on as an extension: the solidcraft_* tools
model new parts in it without a window (sketches, features, parameters), measure them, take screenshots
and export STEP, 3MF or STL. Start with solidcraft_list_commands, build in solidcraft_batch calls and
check with solidcraft_measure and solidcraft_screenshot. Its files stay in one folder, {workspace};
give paths there. It never opens or changes a SOLIDWORKS file."""


class Refused(ValueError):
    """A call SolidSeas does not pass on, in words."""


def workspace() -> str:
    """The one folder SolidCraft's files go in, made when first wanted."""
    folder = os.path.join(data_dir(), "SolidCraft")
    os.makedirs(folder, exist_ok=True)
    return folder


def _inside(path: str, folder: str) -> bool:
    if not os.path.isabs(path):
        return False
    real, base = os.path.realpath(path), os.path.realpath(folder)
    try:
        return os.path.commonpath([real, base]) == base
    except ValueError:  # another drive
        return False


def check_paths(args: Mapping[str, Any], folder: str) -> None:
    """Refuse a call that names a file outside ``folder`` (a network path, a relative one,
    or one that leads out through ``..`` or a link)."""

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and key.lower() in PATH_KEYS:
            if value.startswith(("\\\\", "//")) or not _inside(value, folder):
                raise Refused(f"{value[:200]} is outside SolidCraft's folder, {folder}; give a path there")

    walk(args)


class SolidCraft:
    """The SolidCraft tools of one chat server (module notes). ``start`` gives the running
    MCP helper (default: the extension's, through :func:`start_helper`)."""

    def __init__(self, start: Callable[[str], Any] | None = None, folder: str | None = None) -> None:
        self.folder = folder or workspace()
        self._start = start or _start_helper
        self._helper: Any = None
        self._tools: list[dict] | None = None
        self._lock = threading.Lock()

    def _running(self) -> Any:
        with self._lock:
            if self._helper is None or not getattr(self._helper, "alive", True):
                self._helper = self._start(self.folder)
            return self._helper

    def tools(self) -> list[dict]:
        """SolidCraft's tools, each named with :data:`PREFIX` and its description saying it is
        SolidCraft's; listed once, from the running server."""
        if self._tools is None:
            listed = self._running().tools()
            self._tools = [
                {
                    **t,
                    "name": PREFIX + t["name"],
                    "description": "SolidCraft: " + str(t.get("description") or "")[:4000],
                }
                for t in listed
                if t["name"] not in LEFT_OUT
            ]
        return self._tools

    def names(self) -> frozenset[str]:
        return frozenset(t["name"] for t in self.tools())

    def call(self, name: str, args: Mapping[str, Any]) -> dict:
        """Pass the call on; SolidCraft's result (text and images) as it gave it."""
        if not name.startswith(PREFIX) or name[len(PREFIX) :] in LEFT_OUT:
            raise Refused(f"no SolidCraft tool {name[:64]!r}")
        check_paths(args, self.folder)
        result = self._running().call(name[len(PREFIX) :], args, timeout=CALL_SECONDS)
        content = result.get("content")
        if not isinstance(content, list):
            raise Refused("SolidCraft gave no answer to show")
        return {"content": content, "isError": bool(result.get("isError"))}

    def close(self) -> None:
        with self._lock:
            helper, self._helper = self._helper, None
        if helper is not None:
            helper.close(timeout=10)


def _start_helper(folder: str) -> Any:
    from solidseas.helpers import McpHelper

    return start_helper(
        "solidcraft",
        read_state(),
        helper_class=McpHelper,
        args=["mcp", "--allow-path", folder],
    )


__all__ = ["INSTRUCTIONS", "LEFT_OUT", "PREFIX", "Refused", "SolidCraft", "check_paths", "workspace"]
