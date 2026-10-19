"""Open and Show in File Explorer: a file handed to the program the system opens it
with, and the folder that holds it shown with the file selected.

Both are the user's own request, from the toolbar, the File menu or the right-click
menu of a file (the document list, a Components, Files, BOM, References, sheet or
Where Used row, the 3D view's legend and its components). SolidSeas starts nothing of
its own for them and writes nothing:

* :func:`open_file` asks the system to open the file as File Explorer's double-click
  does: :meth:`QDesktopServices.openUrl` with the file's URL, which on Windows is the
  shell's open verb (SOLIDWORKS for ``.sldprt``, ``.sldasm`` and ``.slddrw``, the
  default program for any other format), so a SOLIDWORKS already running is handed
  the document rather than started again. No command line or shell string is made.
  In the packaged viewer a program the shell starts would inherit the viewer's own
  packaging (PyInstaller's variables, its Qt plugin paths and DLL folder), which
  :func:`.printing.launch_environment` and the default DLL search order leave out for
  the instant of the start, as 3D Print's launcher does.
* :func:`show_file` shows the folder with the file selected: on Windows the shell's
  ``SHOpenFolderAndSelectItems`` on the file's item ID list (File Explorer's own
  window, no process started here); on macOS ``open -R`` with the path as its one
  argument; elsewhere the folder, opened as :func:`open_file` opens a file.

The program that opens a file may change it: a document opened in SOLIDWORKS can be
saved over there. That is the user's choice, as AGENTS.md's safety rules say, and the
action's tooltip says so. :func:`open_problem` decides what is offered at all: a
file that is there, a plain file and not a link, with the extension of a 3D format
SolidSeas lists (never a program, script or shortcut), and not a SOLIDWORKS lock file.

The window looks both up here each time, so the tests' session-wide guard
(``tests/conftest.py``) replaces them and no test starts a program or opens a window
of the system. Nothing here imports Qt at module level.
"""

import os
import stat
import sys
from typing import Any

OPEN_TEXT = "Open"
OPEN_TIP = (
    "Open the file in the program the system opens it with: SOLIDWORKS for a SOLIDWORKS document, the "
    "default program for any other format. SolidSeas writes nothing, but that program can save changes "
    "to the file."
)


def show_text() -> str:
    """The name of Show in File Explorer on this system."""
    if os.name == "nt":
        return "Show in File Explorer"
    if sys.platform == "darwin":
        return "Show in Finder"
    return "Show in Folder"


def show_tip() -> str:
    where = {"Show in File Explorer": "File Explorer", "Show in Finder": "Finder"}.get(show_text())
    if where is None:
        return "Open the folder that holds the file"
    return f"Open the folder that holds the file in {where}, with the file selected"


def open_problem(path: str | None, look: bool = True) -> str | None:
    """Why the file at ``path`` is not opened or shown, in a few words; None when it can
    be. Only the path and ``lstat`` are looked at: the file is not read. Without
    ``look`` only the path is, which costs nothing and is what enables an action; the
    action looks again when it is chosen."""
    from solidseas.formats import registry

    if not path or not os.path.isabs(path) or "\x00" in path:
        return "its place is not known"
    name = os.path.basename(path)
    if name.startswith("~$"):
        return "a SOLIDWORKS lock file"
    if not name.lower().endswith(registry.extensions("all")):
        return "not a 3D file"
    if not look:
        return None
    try:
        st = os.lstat(path)
    except OSError:
        return "not there any more"
    from solidseas.walk import reparse_link

    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    # The walker's rule: a symbolic link, a junction or another name surrogate is a link. A
    # cloud file (OneDrive's placeholders) is a file, which its service brings down when
    # the program opens it.
    if stat.S_ISLNK(st.st_mode) or reparse_link(attrs, int(getattr(st, "st_reparse_tag", 0) or 0)):
        return "a link, which SolidSeas never follows"
    if not stat.S_ISREG(st.st_mode):
        return "not a file"
    return None


def open_file(path: str) -> None:
    """Have the system open the file at ``path`` in its program (see the module notes).
    Raises OSError when the system says it could not."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    with _clean_start():
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    if not ok:
        raise OSError(f"the system could not open {os.path.basename(path)}")


def show_file(path: str) -> None:
    """Show the folder that holds ``path`` with the file selected (see the module notes).
    Raises OSError when the system says it could not."""
    if os.name == "nt":
        _select_in_explorer(path)
        return
    if sys.platform == "darwin":
        import subprocess

        from .printing import launch_environment

        subprocess.Popen(
            ["open", "-R", path],  # a list and no shell: the path is one argument
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=launch_environment(),
        )
        return
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    with _clean_start():
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
    if not ok:
        raise OSError("the system could not open the folder")


def _select_in_explorer(path: str) -> None:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    ole32.CoInitializeEx.restype = ctypes.c_long
    shell32.ILCreateFromPathW.argtypes = (wintypes.LPCWSTR,)
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.SHOpenFolderAndSelectItems.argtypes = (
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    shell32.ILFree.argtypes = (ctypes.c_void_p,)
    # Apartment threaded, as Qt's thread already is (S_FALSE); each success is undone.
    initialized = ole32.CoInitializeEx(None, 0x2) in (0, 1)
    try:
        pidl = shell32.ILCreateFromPathW(os.path.normpath(path))
        if not pidl:
            raise OSError("File Explorer could not find the file")
        try:
            result = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        finally:
            shell32.ILFree(pidl)
    finally:
        if initialized:
            ole32.CoUninitialize()
    if result != 0:
        raise OSError(f"File Explorer could not show the file (0x{result & 0xFFFFFFFF:08x})")


class _clean_start:
    """In the packaged viewer, for the instant of a start through the system: the
    environment without the viewer's packaging (:func:`.printing.launch_environment`)
    and the default DLL search order, put back afterwards. Elsewhere nothing changes."""

    def __enter__(self):
        from .printing import _DefaultDllDirectory, launch_environment

        self.frozen = bool(getattr(sys, "frozen", False))
        self.saved: dict[str, str] | None = None
        self.dlls = _DefaultDllDirectory(self.frozen)
        if self.frozen:
            self.saved = dict(os.environ)
            clean = launch_environment(bundle=getattr(sys, "_MEIPASS", None))
            for key in [k for k in os.environ if k not in clean]:
                del os.environ[key]
            os.environ.update(clean)
        self.dlls.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.dlls.__exit__(*exc)
        finally:
            if self.saved is not None:
                for key in [k for k in os.environ if k not in self.saved]:
                    del os.environ[key]
                os.environ.update(self.saved)


__all__ = ["OPEN_TEXT", "OPEN_TIP", "open_file", "open_problem", "show_file", "show_text", "show_tip"]
