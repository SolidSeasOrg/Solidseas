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

:func:`open_copy` is the plumbing of Open in SolidCraft: the shown model written as STEP
to a new file in that folder, then started in SolidCraft's own program
(``solidcraft.exe``, :func:`desktop_program`, checked as a helper is), which opens a STEP
file as a design with an Import base feature to edit. The program runs on its own, as
the slicer of 3D Print does, and outlives SolidSeas; the viewer has no menu item for it
yet.
"""

from __future__ import annotations

import os
import re
import shutil
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


def _within(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # another drive, or a share
        return False


def _inside(path: str, folder: str) -> bool:
    """Whether ``path`` lies in ``folder``: first by its text alone, so that a path elsewhere
    is refused before anything looks at it (on Windows ``realpath`` opens the path it is
    given, and a share in any spelling, ``/\\server``, ``\\/server`` or ``\\??\\UNC\\server``,
    would be sent this account's credentials), then once more with its links resolved."""
    if not os.path.isabs(path) or "\x00" in path:
        return False
    text, base = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    if not _within(text, base):
        return False
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return _within(os.path.normcase(real), os.path.normcase(base))


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


# --------------------------------------------------------------------------- Open in SolidCraft
DESKTOP = "solidcraft.exe"  # SolidCraft's own program, beside solidcraft-cli.exe in the package
_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def desktop_program(state=None, *, pol=None, root: str | None = None) -> str:
    """SolidCraft's own program in the extension's package, checked as a helper is
    before it starts (:func:`solidseas_app.extensions.start_helper`): only while the
    extension is on, its package added and every file of it the one its manifest names.
    Raises :class:`~solidseas_app.extensions.HelperRefused` in words otherwise, and for a
    package that carries no desktop program."""
    from . import HelperRefused, _added, _sha256, is_on

    state = state if state is not None else read_state()
    if not is_on("solidcraft", state, pol=pol, root=root):
        raise HelperRefused("SolidCraft is off; switch it on in Tools > Extensions")
    found = _added("solidcraft", root)
    if found is None or found[1].helper is None:
        raise HelperRefused("SolidCraft's package is not added")
    folder, added = found
    files = added.helper["files"]
    if DESKTOP not in files:
        raise HelperRefused(
            "SolidCraft's package has no solidcraft.exe; add the SolidCraft package of this SolidSeas release"
        )
    for name, want in files.items():
        path = os.path.join(folder, *name.split("/"))
        if os.path.islink(path) or not os.path.isfile(path) or _sha256(path) != want:
            raise HelperRefused(
                f"{name} in SolidCraft's package is not the file it was added with; remove the "
                "extension and add its package again"
            )
    return os.path.join(folder, DESKTOP)


def copy_path(stem: str, folder: str | None = None) -> str:
    """A name for a new STEP file of ``stem`` in SolidCraft's folder (:func:`workspace`):
    ``stem.step``, else ``stem (2).step`` and so on, never a file that is there."""
    folder = folder or workspace()
    clean = _UNSAFE.sub("_", stem).strip(" .")[:120] or "model"
    for n in range(1, 10000):
        name = f"{clean}.step" if n == 1 else f"{clean} ({n}).step"
        path = os.path.join(folder, name)
        if not os.path.lexists(path):
            return path
    raise Refused(f"SolidCraft's folder already holds too many copies of {clean}")


def open_copy(
    path: str,
    opened: str,
    *,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    allow_partial: bool = False,
    program: str | None = None,
    export: Callable[[dict], dict] | None = None,
    launch: Callable[[str, str], None] | None = None,
    folder: str | None = None,
) -> dict:
    """Open in SolidCraft (``docs/EXTENSIONS.md`` section 9): the part or assembly at
    ``path`` (in the opened folder ``opened``, ``nested`` and ``configuration`` as the
    viewer shows it) written as STEP to a new file in SolidCraft's folder, then that file
    started in SolidCraft's own program (``program``: :func:`desktop_program`), where it
    becomes a design whose Import base feature can be edited. A STEP file is copied
    instead. Nothing is written beside the document. ``export`` runs the export's
    request (:func:`solidseas_app.viewer.printing.export_in_process`) and ``launch``
    starts the program (:func:`solidseas_app.viewer.printing.launch`); tests stand in
    for both. Returns the export's result, with ``data["opened"]`` once the program was
    started."""
    from solidseas_app.viewer import printing, reading

    program = program or desktop_program()
    target = copy_path(reading.export_stem(path, tuple(nested)), folder)
    if not nested and os.path.splitext(path)[1].lower() in (".step", ".stp"):
        with open(path, "rb") as src, open(target, "xb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        result: dict = {"ok": True, "data": {"file": target, "bytes": os.path.getsize(target)}}
    else:
        request = {
            "job": "step",
            "path": path,
            "folder": opened,
            "within": within,
            "nested": tuple(nested),
            "configuration": configuration,
            "target": target,
            "overwrite": False,
            "allow_partial": allow_partial,
        }
        result = (export or printing.export_in_process)(request)
    if result.get("ok"):
        (launch or printing.launch)(program, result["data"]["file"])
        result["data"]["opened"] = True
    return result


def _start_helper(folder: str) -> Any:
    from solidseas.helpers import McpHelper

    return start_helper(
        "solidcraft",
        read_state(),
        helper_class=McpHelper,
        args=["mcp", "--allow-path", folder],
    )


__all__ = ["INSTRUCTIONS", "LEFT_OUT", "PREFIX", "Refused", "SolidCraft", "check_paths", "workspace"]
