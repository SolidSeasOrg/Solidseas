"""The 3D Print button's workings, without Qt: which program, which format, where the
export goes, and the one function that starts the program.

* **Programs.** Bambu Studio, OrcaSlicer, PrusaSlicer and UltiMaker Cura are found
  in their usual install folders (``Program Files``, ``Program Files (x86)`` and
  the per-user ``Programs`` folder) and in the registry's App Paths, which is only
  read (:func:`detect`). Each has the formats it takes, the first, 3MF, being its
  default: Bambu Studio, OrcaSlicer and PrusaSlicer take 3MF, STL and STEP;
  UltiMaker Cura 3MF and STL (STEP only through a plug-in). Any other executable
  the user picks takes all three.
* **The choice** is kept in ``Viewer.ini``, section ``[Print]``
  (:func:`load_choice`, :func:`save_choice`): the program's key, the path of
  another program, and the format. Until one is chosen, Bambu Studio is used when
  it is installed; otherwise the window asks. A format the program chosen next
  does not take is dropped for that program's first (:func:`with_program`,
  :func:`format_dropped`).
* **STEP** is the part's exact geometry, written by :mod:`solidseas.step` as File >
  Export STEP writes it (:func:`step_for_print`). An assembly, which that export
  does not write yet, and a part it refuses (geometry STEP cannot hold without loss,
  an approximation it cannot bring within its limit, its time or size limits,
  nothing to write) are sent as 3MF instead, and the result says why
  (``format_fallback``); a STEP with bodies left out is never sent. A Parasolid
  file's part goes through the same export; any other 3D file is sent as 3MF, the
  result saying why (:func:`step_unavailable`): its format holds triangles, or
  bodies that are not Parasolid's.
* **The export** (:func:`export_for_print`) is written in the folder of the model it
  was made from (:func:`model_folder`): the part's or assembly's own file, or for a
  virtual component, which has no file of its own, the document that stores it (an
  assembly, or the sub-assembly that keeps it, inside which :func:`find_virtual`
  finds it). It is named after the document, a space and the local date
  (:func:`print_label`, :func:`print_stem`), ``bracket 2026-10-03.3mf``: the file's
  name, or a virtual component's own, with the configuration exported when it is not
  the active one, ``frame (Lite) 2026-10-03.3mf`` (a long name is cut before the
  configuration is), and `` (assembly)`` for an assembly whose folder holds a part of
  its name, so the two never share a numbering; a 3D file of another format whose
  folder holds a document of its name in another format carries its extension
  instead, ``frame (STL) 2026-10-03.3mf`` beside ``frame.SLDPRT``'s
  ``frame 2026-10-03.3mf``. When that name is taken the new file
  is ``bracket 2026-10-03 (2).3mf``, then ``(3)``, always one past the highest number
  of that name and extension there (:func:`highest_number`), so of one day's prints
  the highest number is the newest; a file that is there is never opened, renamed or
  replaced. The file is written under a temporary name (:func:`part_path`), never
  through a link at its name, and then given its own by a rename that refuses a name
  taken (:func:`_claim`, :func:`rename_new`), so two prints at once never take the
  same one. Outside Windows that rename is a second link to the file, which a file
  system without hard links (FAT, exFAT, some network shares) cannot make.
* **The fallback.** When the model's folder must not or cannot be written
  (:func:`folder_problem`: a link or junction there or in any folder above it, a
  cloud placeholder, a network share outside the opened folder, a device or stream
  path, a file system without hard links; or the write fails: read-only, permission
  denied, the link refused), when it is outside the
  self-test's folder, and when the setting Save 3D Print Files Next to the Model is
  off, the file goes to a folder of the user's own under the system's temporary
  folder (:func:`export_folder`) instead, named the same way; the result says why.
  Exports older than a week are removed from that folder, and only from it, when the
  next one is made (:func:`clean_old`), except while a program still holds one open:
  nothing next to a model is ever removed but the temporary file of an export that
  failed, was cancelled, or was being written when the viewer ended
  (:func:`sweep_abandoned`, by the next 3D Print). The window runs the export in a
  process of its own (:func:`export_in_process`), which it can end at once and which,
  on Windows, a job object holds to a memory limit.
* **Starting the program** goes through :func:`launch` alone: the file is its one
  argument, no shell runs, and what the packaged viewer set for itself (its
  PyInstaller variables, Qt plugin paths and DLL directory) is not passed on
  (:func:`launch_environment`). Tests and the self-test's dry run replace it, so
  nothing is ever started by them.
"""

import datetime
import errno
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass, replace
from typing import Any

from solidseas.errors import OutputRefusedError

FORMATS = ("3mf", "stl", "step")
FORMAT_LABELS = {"3mf": "3MF", "stl": "STL", "step": "STEP"}
A_FORMAT = {"3mf": "a 3MF", "stl": "an STL", "step": "a STEP"}  # "an STL": its letters are read out
EXTENSIONS = {"3mf": ".3mf", "stl": ".stl", "step": ".step"}
STEP = "step"
STEP_FALLBACK = "3mf"  # what a print asked for as STEP is sent as when it cannot be one
SECTION = "print"
FOLDER_NAME = "SolidSeas Print"
KEEP_SECONDS = 7 * 24 * 3600  # exports older than a week are removed
MAX_CLEAN_ENTRIES = 10_000  # entries of the export folder looked at, at most, when cleaning
MAX_NUMBER = 9_999_999  # the highest number a print file is given, "name (9999999)"
MAX_TRIES = 1_000  # names tried past the highest number taken, when others take them meanwhile
MAX_SCAN = 100_000  # entries of a folder looked at, at most, for the numbers taken
MODEL, TEMP = "model", "temp"  # where a print file went: next to its model, or the temporary folder
MAX_STEM = 80
MAX_CONFIG_STEM = 40  # of a print file's name, at most this much is the configuration's
ASSEMBLY_MARK = "assembly"  # "frame (assembly) 2026-10-03.3mf" beside a part named frame
MAX_SOURCE_STEM = 12  # "frame (STL) 2026-10-03.3mf": a model file's extension (format_mark)
PART_PREFIX = ".solidseas-print-"  # an export being written: ".solidseas-print-<token>.part"
JOURNAL_SUFFIX = ".exporting"  # in the temporary folder, "<token>.exporting" while one is written
MAX_JOURNAL_BYTES = 16_384
_TOKEN = re.compile(r"[0-9a-f]{16}")
MAX_PATH_TEXT = 1024
OTHER = "other"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
# The extension a program must have on Windows: an executable. A batch file or a script
# runs through an interpreter that parses its arguments again, so none is accepted.
EXECUTABLE_EXTENSIONS = (".exe",)
_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]) *(\..*)?", re.I)
_UNSAFE = re.compile(r"[^\w .,()+\-]")


@dataclass(frozen=True)
class Slicer:
    """A program the viewer knows: its key in ``Viewer.ini``, its name, the formats it
    takes (the first is its default), its executable's names and the folders it
    installs to, below a programs folder (``*`` matches a version)."""

    key: str
    name: str
    formats: tuple[str, ...]
    executables: tuple[str, ...]
    folders: tuple[str, ...]


# Which formats each opens, as docs/guide/3d-print.md says: documented by Bambu Lab's
# wiki, OrcaSlicer's wiki and Prusa's knowledge base for all three, by UltiMaker for 3MF and
# STL (STEP needs its STEP and IGES plug-in).
SLICERS: tuple[Slicer, ...] = (
    Slicer("bambu", "Bambu Studio", FORMATS, ("bambu-studio.exe",), ("Bambu Studio",)),
    Slicer("orca", "OrcaSlicer", FORMATS, ("orca-slicer.exe",), ("OrcaSlicer", "Orca Slicer")),
    Slicer(
        "prusa",
        "PrusaSlicer",
        FORMATS,
        ("prusa-slicer.exe",),
        ("Prusa3D\\PrusaSlicer", "Prusa3D\\PrusaSlicer-*", "PrusaSlicer"),
    ),
    Slicer(
        "cura",
        "UltiMaker Cura",
        ("3mf", "stl"),
        ("UltiMaker-Cura.exe", "Cura.exe"),
        ("UltiMaker Cura *", "Ultimaker Cura *", "UltiMaker Cura", "Ultimaker Cura"),
    ),
)
BY_KEY = {s.key: s for s in SLICERS}
DEFAULT_KEY = "bambu"


@dataclass(frozen=True)
class Program:
    """A program to send an export to: its key (one of :data:`BY_KEY`, or ``other``), the
    name shown, its executable and the formats it takes."""

    key: str
    name: str
    path: str
    formats: tuple[str, ...]


@dataclass(frozen=True)
class PrintChoice:
    """What ``Viewer.ini`` remembers: ``program`` (a key, ``other`` or None until one is
    chosen), ``path`` (the executable, for ``other``) and ``format`` (None: the
    program's default)."""

    program: str | None = None
    path: str | None = None
    format: str | None = None


# --------------------------------------------------------------------------- finding programs
def program_folders(env: dict[str, str] | None = None) -> list[str]:
    """The folders programs install to: Program Files (64- and 32-bit) and the
    per-user Programs folder, each once, as the environment names them."""
    env = os.environ if env is None else env
    out: list[str] = []
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = env.get(key)
        if value and os.path.isabs(value):
            out.append(value)
    local = env.get("LOCALAPPDATA")
    if local and os.path.isabs(local):
        out.append(os.path.join(local, "Programs"))
    seen: set[str] = set()
    unique = []
    for folder in out:
        k = os.path.normcase(os.path.normpath(folder))
        if k not in seen:
            seen.add(k)
            unique.append(folder)
    return unique


def _version_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name)[:6])


def _matches(folder: str, pattern: str, listdir) -> list[str]:
    """The folders below ``folder`` that ``pattern`` names (``\\`` separated, a ``*`` in
    its last part), the highest version first."""
    *head, last = pattern.split("\\")
    base = os.path.join(folder, *head)
    if "*" not in last:
        return [os.path.join(base, last)]
    rx = re.compile(re.escape(last).replace(r"\*", ".*"), re.I)
    try:
        names = [n for n in listdir(base) if rx.fullmatch(n)]
    except OSError:
        return []
    return [os.path.join(base, n) for n in sorted(names[:200], key=_version_key, reverse=True)]


def registry_app_path(executable: str) -> str | None:
    """The path the registry's App Paths gives ``executable`` (for this user, then the
    machine, in its 64- and 32-bit views), or None. Only read, never written."""
    if os.name != "nt":
        return None
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, f"{APP_PATHS}\\{executable}", 0, winreg.KEY_READ | view) as key:
                    value, kind = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
                continue
            value = value.strip().strip('"')[:MAX_PATH_TEXT]
            if kind == winreg.REG_EXPAND_SZ:
                value = winreg.ExpandEnvironmentStrings(value)
            if value:
                return value
    return None


def detect(
    env: dict[str, str] | None = None,
    *,
    app_path=registry_app_path,
    is_file=os.path.isfile,
    listdir=os.listdir,
    windows: bool | None = None,
) -> list[Program]:
    """The known programs installed here, in :data:`SLICERS` order: each from the
    registry's App Paths or its usual install folders, the first executable found.
    Nothing is started and nothing is written. Elsewhere than on Windows none is
    detected: choose the program instead."""
    if not (os.name == "nt" if windows is None else windows):
        return []
    folders = program_folders(env)
    found = []
    for s in SLICERS:
        path = None
        for exe in s.executables:
            candidate = app_path(exe)
            if candidate and os.path.isabs(candidate) and is_file(candidate):
                path = candidate
                break
        if path is None:
            for folder in folders:
                for pattern in s.folders:
                    for where in _matches(folder, pattern, listdir):
                        for exe in s.executables:
                            candidate = os.path.join(where, exe)
                            if is_file(candidate):
                                path = candidate
                                break
                        if path:
                            break
                    if path:
                        break
                if path:
                    break
        if path:
            found.append(Program(s.key, s.name, os.path.normpath(path), s.formats))
    return found


def program_problem(path: str | None) -> str | None:
    """Why ``path`` cannot be the program to start, or None: it must be an absolute
    path to a file that is there and, on Windows, an executable (``.exe``), never a
    batch file or a script."""
    if not path or not os.path.isabs(path) or len(path) > MAX_PATH_TEXT or "\x00" in path:
        return "choose a program by its full path"
    if os.name == "nt" and os.path.splitext(path)[1].lower() not in EXECUTABLE_EXTENSIONS:
        return "choose a program file (.exe); a batch file, script or shortcut is not started"
    try:
        st = os.stat(path)
    except OSError:
        return "the program is not there"
    if not stat.S_ISREG(st.st_mode):
        return "that is not a program file"
    if os.name != "nt" and not os.access(path, os.X_OK):
        return "that file is not executable"
    return None


def other_program(path: str) -> Program:
    name = os.path.splitext(os.path.basename(path))[0] or path
    return Program(OTHER, name, path, FORMATS)


def resolve(choice: PrintChoice, detected: list[Program]) -> Program | None:
    """The program ``choice`` names: a detected one, another program by its path, or a
    known one that is no longer found (its ``path`` empty). None when none is chosen."""
    if choice.program == OTHER:
        return other_program(choice.path) if choice.path else None
    s = BY_KEY.get(choice.program or "")
    if s is None:
        return None
    for p in detected:
        if p.key == s.key:
            return p
    return Program(s.key, s.name, "", s.formats)


def first_choice(detected: list[Program]) -> PrintChoice | None:
    """What to use when nothing is chosen yet: Bambu Studio when installed, else None
    (the window asks)."""
    if any(p.key == DEFAULT_KEY for p in detected):
        return PrintChoice(DEFAULT_KEY)
    return None


def format_for(program: Program, choice: PrintChoice) -> str:
    """The format to send: the one chosen when the program takes it, else its default."""
    return choice.format if choice.format in program.formats else program.formats[0]


def describe(choice: PrintChoice, detected: list[Program], *, with_format: bool = True) -> str:
    """The choice in a line, for Preferences (without the format where Preferences offers
    it beside); the program's file is in the menu's tooltips."""
    program = resolve(choice, detected)
    if program is None:
        if first_choice(detected) is not None:
            return f"{BY_KEY[DEFAULT_KEY].name}, found here and used until you choose another"
        if detected:
            return "not chosen yet; the first 3D Print asks"
        return "not chosen yet, and no known program found; the first 3D Print asks"
    gone = "" if program.path else " (no longer found)"
    if not with_format:
        return program.name + gone
    fmt = FORMAT_LABELS[format_for(program, choice)]
    return f"{program.name}, sent as {fmt}{gone}"


# --------------------------------------------------------------------------- the remembered choice
def _path_text(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(value, str):
            return None
        raw = value
    if raw.startswith("@") or "\x00" in raw or len(raw) > MAX_PATH_TEXT or not os.path.isabs(raw):
        return None
    return os.path.normpath(raw)


def parse_choice(values: dict[str, str]) -> PrintChoice:
    """The ``[Print]`` section's values as a choice; anything not valid is left out."""
    program = (values.get("program") or "").strip().lower() or None
    path = _path_text(values.get("path"))
    if program not in (*BY_KEY, OTHER) or (program == OTHER and path is None):
        program, path = None, None
    if program != OTHER:
        path = None
    fmt = (values.get("format") or "").strip().lower() or None
    return PrintChoice(program, path, fmt if fmt in FORMATS else None)


def load_choice(store) -> PrintChoice:
    try:
        return parse_choice(store.load_section(SECTION))
    except Exception:  # a damaged file: nothing chosen
        return PrintChoice()


# JSON leaves these three as they are, and Viewer.ini's reader (str.splitlines) ends a line
# at each: a path holding one would make the whole file look damaged.
_LINE_BREAKS = {c: f"\\u{c:04x}" for c in (0x85, 0x2028, 0x2029)}


def _json_line(text: str) -> str:
    """``text`` as a JSON string that stays on one line of ``Viewer.ini``."""
    return json.dumps(text, ensure_ascii=False).translate(_LINE_BREAKS)


def save_choice(store, choice: PrintChoice) -> bool:
    values: dict[str, str] = {}
    if choice.program:
        values["program"] = choice.program
    if choice.program == OTHER and choice.path:
        values["path"] = _json_line(choice.path)
    if choice.format:
        values["format"] = choice.format
    return store.save_section(SECTION, values or None)


def with_program(choice: PrintChoice, program: Program) -> PrintChoice:
    """``choice`` switched to ``program``, keeping the format only when it takes it: else
    the program's first (:func:`format_dropped` says which was dropped)."""
    fmt = choice.format if choice.format in program.formats else None
    path = program.path if program.key == OTHER else None
    return replace(choice, program=program.key, path=path, format=fmt)


def format_dropped(choice: PrintChoice, program: Program) -> str | None:
    """The format ``choice`` remembers that ``program`` does not take, which switching to
    it drops for its first; None when there is none."""
    return choice.format if choice.format and choice.format not in program.formats else None


def dropped_text(choice: PrintChoice, program: Program) -> str:
    """What switching ``choice`` to ``program`` does to its format, for the status line:
    ``, sent as 3MF: it does not take STEP`` when it drops one, else ""."""
    dropped = format_dropped(choice, program)
    if dropped is None:
        return ""
    return f", sent as {FORMAT_LABELS[program.formats[0]]}: it does not take {FORMAT_LABELS[dropped]}"


# --------------------------------------------------------------------------- the export
DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_RAMDISK = 2, 3, 4, 6
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Why a print file did not go next to its model, as the status line and the result say it.
ODD_PATH = "the model's folder has a path SolidSeas does not write to (a device or a stream of a file)"
NETWORK = (
    "the model's folder is on a network share or drive outside the folder you opened, which SolidSeas "
    "never touches"
)
LINKED = "the model's folder, or one it is in, is a link or a junction, which SolidSeas never writes through"
PLACEHOLDER = "the model's folder is a cloud placeholder, whose files are not on this computer"
NOT_A_FOLDER = "the model's folder is not a folder"
READ_ONLY = "the model's folder is read-only"
DENIED = "permission to add a file to the model's folder was denied"
NO_LINKS = (
    "the model's folder is on a file system without hard links (a FAT or exFAT drive, or some network "
    "shares), and SolidSeas names a new file there through one so that it never replaces a file"
)
FULL = (
    f"the model's folder already has a print of it from today numbered {MAX_NUMBER:,}, the highest "
    "number a print is given"
)
TAKEN = "every name tried for it in the model's folder was taken by other files while it was saved"
SETTING_OFF = "Save 3D Print Files Next to the Model is off"
CONFINED = "the model's folder is outside the folder under test, where alone the self-test adds print files"


# File systems that keep no hard links, by the type the mount table gives them (Linux's
# vfat, msdos and exfat; macOS's msdos and exfat). A folder on one is known before
# anything is written there (folder_problem); any other that refuses a link says so when
# a print file is named (rename_new).
NO_LINK_TYPES = frozenset({"vfat", "msdos", "exfat"})
# What a link refused by its file system raises: EPERM on Linux, where the file system has
# no hard links (link(2); FAT, exFAT, a FUSE file system without them), EOPNOTSUPP from an
# SMB share that refuses them, ENOTSUP on macOS, ENOSYS from an older FUSE.
NO_LINK_ERRNOS = frozenset({errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS})
NO_HARD_LINKS = "no_hard_links"  # the rule of the OutputRefusedError rename_new raises for one


def _link(st: os.stat_result) -> bool:
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(st.st_mode) or bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def today() -> str:
    """The local date, as print files are named with it: ``2026-10-03``."""
    return datetime.date.today().isoformat()


def export_folder_path(base: str | None = None) -> str:
    """Where :func:`export_folder` is, without making it."""
    base = base or tempfile.gettempdir()
    name = FOLDER_NAME if os.name == "nt" else f"{FOLDER_NAME.replace(' ', '-')}-{os.getuid()}"
    return os.path.join(base, name)


def export_folder(base: str | None = None) -> str:
    """The user's own export folder under the system's temporary folder (or ``base``),
    made if need be. Refused (``OutputRefusedError``) when it is a link or a junction,
    not a folder, or, outside Windows, another account's or writable by others."""
    folder = export_folder_path(base)
    try:
        os.mkdir(folder, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(folder)
    if _link(st) or not stat.S_ISDIR(st.st_mode):
        raise OutputRefusedError(
            f"the 3D print folder {folder} is a link or not a folder, so nothing is written there",
            detail={"rule": "link"},
        )
    if os.name != "nt" and (st.st_uid != os.getuid() or st.st_mode & 0o022):
        raise OutputRefusedError(
            f"the 3D print folder {folder} belongs to another account or others may write to it",
            detail={"rule": "not_own_folder"},
        )
    return folder


def model_folder(path: str) -> str:
    """The folder a print file of the document at ``path`` goes to: the file's own, which
    for a virtual component is the document that stores it."""
    return os.path.dirname(os.path.abspath(path))


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def inside(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or lies below it, compared as the system compares names."""
    p, f = _key(path), _key(folder)
    try:
        return os.path.commonpath([p, f]) == f
    except ValueError:  # another drive
        return False


def _windows_drive_type(root: str) -> int:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    return int(kernel32.GetDriveTypeW(root))


def _no_drive_type(root: str) -> int:
    return DRIVE_FIXED


# What kind of drive a drive letter is (GetDriveTypeW reads the letter's mapping and
# connects nowhere); behind a module attribute so tests can stand in for it.
drive_type = _windows_drive_type if os.name == "nt" else _no_drive_type


def _local(path: str) -> bool:
    """Whether ``path`` is on a drive of this computer, judged from its text and its drive
    letter's kind only: a UNC path or a mapped network drive is not. On Linux and macOS a network
    file system's mount is not either (:mod:`solidseas.netfs`, from the kernel's mount
    table)."""
    if os.name != "nt":
        from solidseas import netfs

        return not netfs.is_network(path)
    p = path.replace("/", "\\")
    if p.startswith("\\\\"):
        return False
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    return drive_type(drive + "\\") in (DRIVE_FIXED, DRIVE_REMOVABLE, DRIVE_RAMDISK)


def _without_links(path: str) -> bool:
    """Whether ``path`` lies on a file system of :data:`NO_LINK_TYPES`, from its text and the
    mount table alone (:mod:`solidseas.netfs`). Never on Windows, where a rename refuses a
    name taken by itself and no link is made."""
    if os.name == "nt":
        return False
    from solidseas import netfs

    try:
        return netfs.mount_type(path) in NO_LINK_TYPES
    except Exception:  # a table that cannot be read tells nothing; a refused link still says so
        return False


def _may_look(path: str, opened: str) -> bool:
    """Whether ``path`` may be looked at: inside the folder the user opened, or on a drive
    of this computer; never a network share or drive outside the opened folder."""
    return bool(opened) and inside(path, opened) or _local(path)


def _plain_folder(path: str) -> str | None:
    """Why ``path`` is not a plain folder of this computer to add a file to, or None: read
    with ``lstat``, never followed, by the rules the folder walker lists a folder by."""
    from solidseas import walk

    try:
        st = os.lstat(path)
    except OSError as exc:
        return f"the model's folder could not be looked at ({exc.strerror or exc})"
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    tag = int(getattr(st, "st_reparse_tag", 0) or 0)
    if stat.S_ISLNK(st.st_mode) or walk.reparse_link(attrs, tag) is not None:
        return LINKED
    placeholder = walk.FILE_ATTRIBUTE_OFFLINE | walk.FILE_ATTRIBUTE_RECALL_ON_OPEN
    if attrs & (placeholder | walk.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
        return PLACEHOLDER
    if not stat.S_ISDIR(st.st_mode):
        return NOT_A_FOLDER
    return None


def ancestry(folder: str) -> list[str]:
    """``folder`` and every folder it is in, from the root of its drive (or of its share)
    down to it, as the path's text names them: nothing is looked at."""
    chain = [folder]
    while len(chain) < MAX_PATH_TEXT:
        up = os.path.dirname(chain[-1])
        if not up or up == chain[-1]:
            break
        chain.append(up)
    return chain[::-1]


def folder_problem(folder: str, opened: str) -> str | None:
    """Why a print file must not be written in ``folder``, the model's folder, said for the
    user; None when it may be tried. ``opened`` is the folder the user opened.

    Refused: a device or extended-length path or a stream of a file (on Windows); a
    folder outside ``opened`` that is not on a drive of this computer (a UNC path or a
    mapped network drive, never contacted); a link, a junction or a cloud placeholder
    at the folder or at any folder it is in, from the root of its drive down
    (:func:`ancestry`), so the rule is the same whichever folder was opened and wherever
    the model was found; outside Windows, a folder this account may not write in, and one
    on a file system without hard links (:data:`NO_LINK_TYPES`, from the mount table),
    where the print file could not be named without the risk of replacing a file. Only
    the path's text, ``lstat`` and the mount table are used: nothing is opened or
    written. A Windows folder's read-only attribute is not a refusal: Windows sets it on
    Documents and Desktop to keep their icons and adds files to such folders all the
    same. Whether the folder takes the file is only known by writing it, which
    :func:`export_for_print` does."""
    if not folder or "\x00" in folder or len(folder) > MAX_PATH_TEXT:
        return ODD_PATH
    if os.name == "nt":
        p = folder.replace("/", "\\")
        if p.startswith(("\\\\?\\", "\\\\.\\")) or ":" in os.path.splitdrive(p)[1]:
            return ODD_PATH
    folder = os.path.abspath(folder)
    if not inside(folder, opened) and not _local(folder):
        return NETWORK  # the share or drive the user opened is theirs to choose; no other is looked at
    for f in ancestry(folder):
        why = _plain_folder(f)
        if why is not None:
            return why
    if os.name != "nt" and not os.access(folder, os.W_OK | os.X_OK):
        return READ_ONLY
    if _without_links(folder):
        return NO_LINKS
    return None


def write_problem(exc: BaseException) -> str:
    """Why writing a print file in the model's folder failed, said for the user."""
    if isinstance(exc, OutputRefusedError):
        detail = exc.detail or {}
        if detail.get("rule") == "exists":
            return FULL if detail.get("highest", 0) >= MAX_NUMBER else TAKEN
        if detail.get("rule") == NO_HARD_LINKS:
            return NO_LINKS
        return f"the model's folder was refused: {exc}"
    winerror = getattr(exc, "winerror", None)
    if winerror == 19 or getattr(exc, "errno", None) == errno.EROFS:  # ERROR_WRITE_PROTECT
        return READ_ONLY
    if isinstance(exc, PermissionError):
        return DENIED
    if isinstance(exc, OSError):
        return f"the model's folder could not be written ({exc.strerror or exc})"
    return f"the model's folder could not be written ({exc})"


def safe_stem(name: str, limit: int = MAX_STEM) -> str:
    """A file name stem from a document's name: characters a file name cannot hold, or
    that a shell or a slicer could misread, become ``_``; at most ``limit`` (80)
    characters, never a Windows device name (which Windows also reads in ``nul .x``),
    never empty."""
    stem = _UNSAFE.sub("_", name).strip(" .")
    stem = re.sub(r"_{2,}", "_", stem)[: max(1, limit)].strip(" .")
    if not stem:
        return "model"
    if _RESERVED.fullmatch(stem):
        stem = "_" + stem[: max(1, limit) - 1]
    return stem


def document_name(name: str) -> str:
    """A document's name without its folder and its SOLIDWORKS extension:
    ``Part12^o16_asm_features`` for ``Part12^o16_asm_features.SLDPRT``."""
    base = os.path.basename(name.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    return stem if stem and ext.lower() in (".sldprt", ".sldasm", ".slddrw") else base or name


def print_label(
    name: str, configuration: str | None = None, *, assembly: bool = False, source: str | None = None
) -> str:
    """The document's part of a print file's name: its ``name`` made safe, `` (assembly)``
    with ``assembly``, ``source`` in brackets when it is given (a model file's extension,
    ``frame (STL)``, :func:`format_mark`), and ``configuration`` in brackets when it is
    given, ``frame (Lite)``. The configuration keeps up to :data:`MAX_CONFIG_STEM`
    characters and the name is cut to what is left of :data:`MAX_STEM`, so a long name
    never pushes the configuration out of it."""
    tail = f" ({ASSEMBLY_MARK})" if assembly else ""
    if source:
        tail += f" ({safe_stem(source, MAX_SOURCE_STEM)})"
    if configuration:
        tail += f" ({safe_stem(configuration, MAX_CONFIG_STEM)})"
    return safe_stem(name, MAX_STEM - len(tail)) + tail


def print_stem(label: str, date: str) -> str:
    """What a print file's name starts with: the document's name (and configuration) made
    safe (:func:`safe_stem`, :func:`print_label`), a space and the date, ``bracket
    2026-10-03``."""
    if not _DATE.fullmatch(date or ""):
        raise ValueError(f"a print file's date is written YYYY-MM-DD, not {date!r}")
    return f"{safe_stem(label)} {date}"


def candidate_names(stem: str, ext: str, start: int = 1):
    """``stem + ext``, then ``stem (2) + ext`` and so on, from the ``start``-th: at most
    :data:`MAX_TRIES` names, and none numbered past :data:`MAX_NUMBER`."""
    first = max(1, start)
    for n in range(first, min(first + MAX_TRIES, MAX_NUMBER + 1)):
        yield stem + ext if n == 1 else f"{stem} ({n}){ext}"


def _part_named(folder: str, name: str, *, limit: int = MAX_SCAN) -> bool:
    """Whether ``folder`` holds a part file named ``name`` (``name.SLDPRT``, in any case),
    looking at no more than ``limit`` of its entries and opening none."""
    want = f"{name}.sldprt".casefold()
    try:
        entries = os.scandir(folder)
    except OSError:
        return False
    with entries:
        for k, entry in enumerate(entries):
            if k >= limit:
                return False
            if entry.name.casefold() == want:
                return True
    return False


def format_mark(path: str) -> str:
    """What marks a print of the 3D file at ``path`` beside a document of its name in
    another format: its extension, as the list's type buttons show it, ``STL`` for
    ``frame.stl``."""
    return os.path.splitext(os.path.basename(path))[1].lstrip(".").upper()


def _named_alike(path: str, *, limit: int = MAX_SCAN) -> bool:
    """Whether the folder of the file at ``path`` holds another document of its name in
    another format, ``frame.SLDPRT`` beside ``frame.stl``: a file named the same before
    its extension, without regard to case, whose extension a 3D format SolidSeas knows
    has, the file itself apart. No more than ``limit`` entries are looked at, and none is
    opened."""
    from solidseas.formats import registry

    folder, base = os.path.split(path)
    own = base.casefold()
    want = os.path.splitext(own)[0]
    try:
        entries = os.scandir(folder or ".")
    except OSError:
        return False
    with entries:
        for k, entry in enumerate(entries):
            if k >= limit:
                return False
            name = entry.name.casefold()
            if name == own or os.path.splitext(name)[0] != want:
                continue
            try:
                plain = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            if plain and registry.by_extension(entry.name) is not None:
                return True
    return False


def highest_number(folder: str, stem: str, ext: str, *, limit: int = MAX_SCAN) -> int:
    """The highest number among ``folder``'s files named as prints of ``stem``: 1 for
    ``stem + ext``, n for ``stem (n) + ext``, compared without regard to case as Windows
    compares names; 0 when there is none. At most ``limit`` entries are looked at, and
    none is opened."""
    rx = re.compile(re.escape(stem) + r"(?: \(([0-9]{1,7})\))?" + re.escape(ext), re.IGNORECASE)
    highest = 0
    try:
        entries = os.scandir(folder)
    except OSError:
        return 0
    with entries:
        for k, entry in enumerate(entries):
            if k >= limit:
                break
            m = rx.fullmatch(entry.name)
            if m:
                highest = max(highest, int(m.group(1)) if m.group(1) else 1)
    return highest


def clean_old(folder: str, *, now: float | None = None, keep_seconds: float = KEEP_SECONDS) -> int:
    """Remove this folder's exports (``.3mf``, ``.stl``, ``.step``, and a ``.part`` left by a
    write that was stopped) older than ``keep_seconds``; regular files only, links and
    folders are left alone, and a file a program holds open stays. At most
    :data:`MAX_CLEAN_ENTRIES` entries are looked at. Returns how many were removed.
    Only ever called on :func:`export_folder`, never on a model's folder."""
    now = time.time() if now is None else now
    removed = 0
    try:
        entries = os.scandir(folder)
    except OSError:
        return 0
    with entries:
        for k, entry in enumerate(entries):
            if k >= MAX_CLEAN_ENTRIES:
                break
            low = entry.name.lower()
            if not low.endswith((*EXTENSIONS.values(), ".part")):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _link(st) or not stat.S_ISREG(st.st_mode) or now - st.st_mtime < keep_seconds:
                continue
            try:
                os.remove(entry.path)
                removed += 1
            except OSError:  # a slicer still has it open
                continue
    return removed


def part_path(folder: str, token: str) -> str:
    """Where an export is written before it gets its name: ``.solidseas-print-<token>.part``
    in the folder it goes to, so a process ended while writing leaves no file named
    like an export, and says what it is; the window removes what an export it stopped
    left by that name, and the next 3D Print what one left that the viewer could not
    (:func:`sweep_abandoned`)."""
    return os.path.join(folder, f"{PART_PREFIX}{token}.part")


def rename_new(part: str, target: str) -> None:
    """Give the finished file at ``part`` the name ``target``, never replacing a file there:
    ``FileExistsError`` when the name is taken. On Windows a rename refuses a name taken;
    elsewhere a second link to the file refuses it too, and then the first name goes. A
    file system without hard links (FAT, exFAT, an SMB share that refuses them) cannot make
    that link: ``OutputRefusedError`` with the rule :data:`NO_HARD_LINKS` says so, rather
    than the permission error the system gives, and ``part`` is left for the caller."""
    if os.name == "nt":
        os.rename(part, target)
        return
    try:
        os.link(part, target)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in NO_LINK_ERRNOS:
            raise
        raise OutputRefusedError(
            f"{os.path.dirname(target)} is on a file system without hard links, and a new file is "
            "named there through one so that it never replaces a file",
            detail={"rule": NO_HARD_LINKS, "errno": errno.errorcode.get(exc.errno or 0, exc.errno)},
        ) from exc
    os.remove(part)


def _claim(part: str, folder: str, names) -> str:
    """Give the finished export at ``part`` the first of ``names`` not taken, never
    replacing a file (:func:`rename_new`)."""
    for name in names:
        target = os.path.join(folder, name)
        try:
            rename_new(part, target)
            return target
        except FileExistsError:
            continue
    raise OutputRefusedError(
        f"{folder} has no free name left for a print file of that name", detail={"rule": "exists"}
    )


def _write_named(model, folder: str, fmt: str, stem: str, token: str) -> tuple[str, int]:
    """Write ``model`` as ``fmt`` in ``folder`` as :func:`part_path`, then name it the
    first of :func:`candidate_names` past :func:`highest_number`: the file and its size.
    A STEP's header names the file it is expected to become; one that passes the STEP
    export's file-size limit as it is written raises :class:`_StepTooLarge`. The part
    is removed when anything fails."""
    ext = EXTENSIONS[fmt]
    part = part_path(folder, token)
    if fmt == STEP:
        from solidseas.errors import SldLimitError
        from solidseas.step import write_step

        expected = next(candidate_names(stem, ext, highest_number(folder, stem, ext) + 1), stem + ext)
        try:
            size = write_step(model, part, file_name=expected).bytes  # created new; a failed write removes it
        except SldLimitError as exc:
            raise _StepTooLarge(step_refusal(exc)) from exc
    else:
        from solidseas.export import write_export

        size = write_export(model, part, fmt).bytes
    try:
        highest = highest_number(folder, stem, ext)
        if highest >= MAX_NUMBER:
            raise OutputRefusedError(
                f"{folder} holds a print file of that name numbered {MAX_NUMBER:,}",
                detail={"rule": "exists", "highest": highest},
            )
        file = _claim(part, folder, candidate_names(stem, ext, highest + 1))
    except BaseException:
        _remove_part(part)
        raise
    return file, size


# Why a print asked for as STEP went as 3MF, as the status line and the result say it.
STEP_PARTIAL = "the STEP export would have left bodies out, and an incomplete STEP is never sent"
STEP_MESH = "{name} files hold triangles, not the exact faces and edges a STEP is made of"
STEP_MODEL_FILE = (
    "SolidSeas writes STEP from Parasolid bodies (SOLIDWORKS parts and Parasolid files), "
    "not from {name} files"
)
# Why File > Export STEP is off for a drawing.
STEP_DRAWING = "STEP holds 3D models, not drawings: export the model the drawing shows instead"
# The formats whose parts the STEP export writes (solidseas.step.MODEL_FILE_FORMATS and SOLIDWORKS).
STEP_SOURCES = ("solidworks", "parasolid")
MAX_REFUSED_LISTED = 2  # bodies named in the reason a STEP was refused


def step_unavailable(fmt: str | None, doc_type: str | None) -> str | None:
    """Why a document cannot go as STEP, from what the listing says of it, before anything
    is read: ``fmt`` is its registry id (None or ``solidworks`` for a SOLIDWORKS
    document). None when the STEP export may write it, a part of :data:`STEP_SOURCES`,
    which can still refuse it (:func:`step_refusal`); a SOLIDWORKS assembly is written as
    one (:mod:`solidseas.step.assembly`), and so is a Parasolid file's assembly, but
    for the .x_b SOLIDWORKS writes for a multi-body part, which the export reads as
    that part (:func:`solidseas.formats.xt.bodies_in_place`)."""
    from solidseas.formats import registry

    if doc_type == "drawing":
        return STEP_DRAWING
    if fmt is None or fmt in STEP_SOURCES:
        return None
    spec = registry.FORMATS.get(fmt)
    name = spec.name if spec is not None else fmt
    if spec is not None and spec.kind == "mesh":
        return STEP_MESH.format(name=name)
    return STEP_MODEL_FILE.format(name=name)


def step_refusal(exc: BaseException) -> str:
    """Why a document could not be sent as STEP, said for the user, from what
    :func:`solidseas.step.step_model` or :func:`solidseas.step.write_step` raised."""
    from solidseas.errors import (
        NothingToExportError,
        NotRepresentableError,
        SldLimitError,
        UnsupportedOperationError,
    )
    from solidseas.step import DEFAULT_MAX_BYTES, DEFAULT_MAX_FACES, DEFAULT_MAX_SECONDS

    if isinstance(exc, UnsupportedOperationError):  # a model file of another format
        detail = getattr(exc, "detail", None) or {}
        return step_unavailable(detail.get("value"), None) or str(exc)
    detail = getattr(exc, "detail", None) or {}
    if isinstance(exc, NotRepresentableError) and detail.get("rule") == "instances_left_out":
        listed = "; ".join(detail.get("instances") or [])[:400]
        n = detail.get("value") or 0
        what = "one of its instances" if n == 1 else f"{n} of its instances"
        return f"{what} cannot be written as STEP" + (f" ({listed})" if listed else "")
    if isinstance(exc, NotRepresentableError):
        bodies = list(exc.bodies)
        if not bodies:
            return f"STEP cannot hold its geometry without loss ({exc})"
        listed = "; ".join(f"{b.name}: {b.message or b.reason}" for b in bodies[:MAX_REFUSED_LISTED])
        more = len(bodies) - MAX_REFUSED_LISTED
        what = "a body" if len(bodies) == 1 else f"{len(bodies)} bodies"
        return f"STEP cannot hold {what} of it without loss ({listed}" + (
            f"; {more} more)" if more > 0 else ")"
        )
    if isinstance(exc, SldLimitError):
        limit = detail.get("limit")
        if limit == "max_seconds":
            return f"the STEP export stopped at its limit of {DEFAULT_MAX_SECONDS:.0f} seconds"
        if limit == "max_faces":
            return f"the part has more than the {DEFAULT_MAX_FACES:,} faces the STEP export takes"
        if limit == "max_bytes":
            gib = DEFAULT_MAX_BYTES >> 30
            return f"its STEP file would be larger than the {gib} GiB the STEP export writes"
        return f"the STEP export reached one of its limits ({exc})"
    if isinstance(exc, NothingToExportError):
        if detail.get("rule") == "sheets_not_asked":
            return "the part's bodies are surfaces, which a slicer cannot print from a STEP"
        text = str(exc)
        return "the STEP export found nothing to write: " + (text.split(": ", 1)[1] if ": " in text else text)
    return f"the part's bodies could not be read for a STEP ({exc})"


def _active_instead(doc, configuration: str | None):
    """The warning for a STEP of the part's active configuration in place of
    ``configuration``, when the part stores no bodies of that one and does of its active
    one, as a 3MF of it is made (:func:`solidseas.export.print_model`); None otherwise."""
    from solidseas.errors import ReaderWarning
    from solidseas.step import step_configurations

    active = doc.active_configuration
    if not configuration or configuration == active:
        return None
    stored = step_configurations(doc)
    if configuration in stored or active not in stored:
        return None
    return ReaderWarning(
        "mesh_configuration_differs",
        f"the part stores no bodies of configuration {configuration!r}; those of its active "
        f"configuration {active!r} are exported, whose geometry may differ",
    )


def step_for_print(doc, configuration: str | None, name: str, roots=None, *, outside: bool = True):
    """The STEP of ``doc`` for a print, in ``configuration`` (None: the active one) and
    named ``name``, as File > Export STEP maps it (:func:`solidseas.step.step_model`,
    its solid bodies; an assembly's component files found under ``roots``, and with
    ``outside`` at a stored path outside them on a drive of this computer):
    ``(model, None)``, or ``(None, why)`` when it cannot be one: an assembly with
    instances the export cannot write, or a part it refuses (geometry
    STEP cannot hold without loss, an approximation past its limit, its time or size
    limits, nothing to write, bodies it cannot read). A part that stores no bodies of
    ``configuration`` gives its active configuration's, as its 3MF would, and says so.
    Bodies are never left out on request, so a STEP sent is never a partial one. A
    model file (:mod:`solidseas.formats`) is a Parasolid file's part, mapped the same
    way, or of a format the export does not write (:func:`step_unavailable`)."""
    from solidseas.errors import NothingToExportError, NotRepresentableError, SldFormatError
    from solidseas.formats.base import ModelDocument
    from solidseas.step import step_model

    if isinstance(doc, ModelDocument):
        why = step_unavailable(doc.format, doc.doc_type)
        if why is not None:
            return None, why
    try:
        try:
            model = step_model(doc, configuration, name=name, roots=roots, allow_outside_roots=outside)
        except NothingToExportError:
            instead = _active_instead(doc, configuration)
            if instead is None:
                raise
            model = step_model(doc, None, name=name, roots=roots, allow_outside_roots=outside)
            model = replace(model, warnings=(*model.warnings, instead))
    except (NotRepresentableError, NothingToExportError, NotImplementedError, SldFormatError) as exc:
        return None, step_refusal(exc)
    if model.partial:  # allow_partial is never asked for: this cannot happen, and is never sent
        return None, STEP_PARTIAL
    return model, None


def _step_data(model) -> dict[str, Any]:
    """What a print sent as STEP holds, for the window's note and the self-test's check."""
    c = model.counts
    return {
        "exact": model.exact,
        "solids": c.get("solids", 0),
        "sheets": c.get("sheets", 0),
        "faces": c.get("faces", 0),
        "max_deviation_mm": None if model.max_deviation_m is None else model.max_deviation_m * 1000.0,
        "max_tolerance_mm": None if model.max_tolerance_m is None else model.max_tolerance_m * 1000.0,
        "uncertainty_mm": model.uncertainty_m * 1000.0,
    }


def find_virtual(doc, stored: str):
    """The nested document of ``doc`` that holds the virtual component whose stored path
    (or file name) is ``stored``, as the 3D view finds a virtual part inside the
    sub-assembly that uses it (:mod:`solidseas.geometry`): the nested file of the same
    file name. Raises ``StreamNotFoundError`` when ``doc`` stores none."""
    from solidseas.errors import StreamNotFoundError

    def base(text: str | None) -> str:
        return os.path.basename((text or "").replace("\\", "/"))

    want = base(stored).casefold()
    for f in doc.reference_set().files.values():
        if want and f.nested and base(f.stored_path).casefold() == want:
            return doc.nested(f.nested), f.nested
    raise StreamNotFoundError(f"the sub-assembly that uses {base(stored)!r} stores no copy of it")


def _opened(path: str, within: str, nested: tuple[str, ...]):
    """The document to print: a SOLIDWORKS document as the viewer opens one (a nested
    document from inside it), any other 3D file SolidSeas reads as a model file, a
    file wearing a SOLIDWORKS extension over another format's content included
    (:func:`solidseas.formats.open_any`)."""
    from solidseas.formats import open_any

    from . import reading

    if nested:
        return reading.opened(path, within, tuple(nested))
    return open_any(path, within=within)


def format_of(path: str) -> str | None:
    """The registry id of the 3D format the file at ``path`` is named as, when it is not
    SOLIDWORKS; None for a SOLIDWORKS name or one no format has."""
    from solidseas.formats import registry

    spec = registry.by_extension(path)
    return None if spec is None or spec.id == registry.SOLIDWORKS else spec.id


def sent_format(fmt: str, model_format: str | None, doc_type: str | None) -> tuple[str, str | None]:
    """The format a print asked for as ``fmt`` goes in, and why it is not ``fmt``, as far
    as the document's format (``model_format``, the registry id of what the file holds;
    None for a SOLIDWORKS document) and type tell before anything is read: a document
    that cannot go as STEP (:func:`step_unavailable`) goes as :data:`STEP_FALLBACK`. A
    part the STEP export refuses once it is read goes as 3MF too, which only the export
    finds out."""
    if fmt == STEP:
        why = step_unavailable(model_format, doc_type)
        if why is not None:
            return STEP_FALLBACK, why
    return fmt, None


def as_is(path: str, fmt: str, content: str | None) -> bool:
    """Whether the file at ``path`` already is a ``fmt`` file a slicer opens as it is: a
    3MF for a print that goes as 3MF, an STL for one that goes as STL (a 3MF asked for
    as STEP goes as 3MF, :func:`sent_format`), by both what it holds (``content``, the
    registry id of the format the listing or the opened document found inside it) and
    its name, which is what the slicer goes by. Opened as it is, a slicer project keeps
    its plates and settings (Settings > Open 3MF and STL Files As They Are). A STEP is
    never opened as it is, nor a file whose name says another format than it holds
    (an STL saved as ``.3mf``): each is exported to a new file."""
    from solidseas.formats import registry

    if fmt not in ("3mf", "stl") or content != fmt:
        return False
    spec = registry.by_extension(path)
    return spec is not None and spec.id == fmt


def export_for_print(
    path: str,
    folder: str,
    fmt: str,
    *,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    out_base: str | None = None,
    next_to_model: bool = True,
    date: str | None = None,
    cache=None,
    token: str | None = None,
    name: str | None = None,
    virtual: tuple[str, ...] = (),
    confine: str | None = None,
    outside: bool = True,
) -> dict[str, Any]:
    """Export the document at ``path`` (opened read-only ``within`` the opened
    ``folder``, or the nested document ``nested`` leads to, then for each of
    ``virtual`` the virtual component of that stored name it keeps, :func:`find_virtual`)
    as ``fmt`` for printing, in ``configuration`` (None: the active one), as a new file
    named :func:`print_stem` of the document's name and ``date`` (None: :func:`today`).
    The name is the file's, or for a nested document ``name`` (the component's, as the
    window shows it), with the configuration exported when it is not the active one,
    and `` (assembly)`` for an assembly whose folder holds a part of its name
    (:func:`print_label`). An assembly's files are found in the opened folder, as the
    3D view finds them, and without ``outside`` in that folder alone.

    With ``next_to_model`` the file goes to :func:`model_folder` unless
    :func:`folder_problem` refuses it, the folder is outside ``confine`` (the
    self-test's folder) or writing there fails; then, and without ``next_to_model``,
    to :func:`export_folder` under ``out_base``, whose old exports are removed first.
    It is written as :func:`part_path` (``token``: a random one) and then named.
    A ``fmt`` of ``step`` writes the part's STEP (:func:`step_for_print`), or, for an
    assembly or a part the STEP export refuses, a 3MF, named for that; so does a STEP
    its write stops at the file-size limit, which is found only as it is written: no
    part of it is kept, and the document is exported again as 3MF.
    Returns what was written, for the window and the dry run: ``format`` is the format
    written and ``requested_format`` the one asked for, ``format_fallback`` why they
    differ, ``place`` is :data:`MODEL` or :data:`TEMP`, ``fallback`` says why it is not
    next to the model when it could have been, ``requested_configuration`` the
    configuration asked for, which a part that stores no bodies of it does not export
    as 3MF or STL, and ``step`` what a STEP holds. A 3D file of another format SolidSeas
    reads (an STL...) is opened as a model file (:func:`solidseas.formats.open_any`) and
    exported from its scene."""
    from solidseas.errors import InvalidArgumentError

    if fmt not in FORMATS:
        raise InvalidArgumentError(
            f"a print's format is one of {', '.join(FORMATS)}",
            detail={"parameter": "fmt", "value": str(fmt)[:16]},
        )
    t0 = time.perf_counter()
    options = {
        "within": within,
        "nested": nested,
        "configuration": configuration,
        "out_base": out_base,
        "next_to_model": next_to_model,
        "date": date or today(),
        "cache": cache,
        "token": token or os.urandom(8).hex(),
        "name": name,
        "virtual": virtual,
        "confine": confine,
        "outside": outside,
    }
    try:
        result = _export_once(path, folder, fmt, **options)
    except _StepTooLarge as exc:
        result = _export_once(path, folder, STEP_FALLBACK, **options)
        result.update(requested_format=fmt, format_fallback=exc.why)
    result["seconds"] = round(time.perf_counter() - t0, 3)
    return result


class _StepTooLarge(Exception):
    """A print's STEP that its write stopped at the STEP export's file-size limit
    (:func:`_write_named`), its part removed: :func:`export_for_print` sends the
    document as 3MF instead, saying ``why``."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def _export_once(
    path: str,
    folder: str,
    fmt: str,
    *,
    within: str | None,
    nested: tuple[str, ...],
    configuration: str | None,
    out_base: str | None,
    next_to_model: bool,
    date: str,
    cache,
    token: str,
    name: str | None,
    virtual: tuple[str, ...],
    confine: str | None,
    outside: bool,
) -> dict[str, Any]:
    """:func:`export_for_print` as ``fmt``, its options settled, but for its time and a
    STEP its write stopped (:class:`_StepTooLarge`, raised)."""
    from solidseas.export import print_model

    from . import reading

    asked = fmt
    with _opened(path, within or folder, nested) as doc:
        for stored in virtual:
            doc, stream = find_virtual(doc, stored)
            nested = (*nested, stream)
        if nested and name:
            document = document_name(name)
        elif nested:
            document = reading.export_stem(path, nested)
        else:
            document = os.path.splitext(os.path.basename(path))[0]
        roots = reading.roots_for(folder) if doc.doc_type == "assembly" else None
        model, step_why = None, None
        if fmt == STEP:
            model, step_why = step_for_print(doc, configuration, document, roots, outside=outside)
            if model is None:
                fmt = STEP_FALLBACK
        if model is None:
            model = print_model(
                doc, configuration, name=document, roots=roots, cache=cache, allow_outside_roots=outside
            )
        exported = model.configuration
        named = exported if len(doc.configurations) > 1 and exported != doc.active_configuration else None
    here = model_folder(path)
    source_format = getattr(model, "source_format", None) or "solidworks"
    own = not nested and source_format != "solidworks"  # a 3D file of another format, its own file
    # Its folder is listed for a document of its name only where it may be looked at: never
    # on a network share or drive outside the opened folder. A model file beside one of its
    # name in another format is marked with its extension, an assembly with (assembly).
    looked = not nested and _may_look(here, folder)
    source = format_mark(path) if own and looked and _named_alike(path) else None
    mark = model.doc_type == "assembly" and not own and looked and _part_named(here, document)
    label = print_label(document, named, assembly=mark, source=source)
    stem = print_stem(label, date)
    place, fallback, file, size = TEMP, None, None, 0
    if next_to_model:
        fallback = CONFINED if confine and not inside(here, confine) else folder_problem(here, folder)
        if fallback is None:
            try:
                file, size = _write_named(model, here, fmt, stem, token)
                place = MODEL
            except (OSError, OutputRefusedError) as exc:
                fallback = write_problem(exc)
    if file is None:
        out = export_folder(out_base)
        clean_old(out)  # the temporary folder only: nothing next to a model is ever removed
        file, size = _write_named(model, out, fmt, stem, token)
    step = fmt == STEP
    warnings = [*model.warnings, *(w for o in ([] if step else model.objects) for w in o.warnings)]
    return {
        "file": file,
        "format": fmt,
        "requested_format": asked,
        "format_fallback": step_why,
        "bytes": size,
        "place": place,
        "out_folder": os.path.dirname(file),
        "model_folder": here,
        "fallback": fallback,
        "stem": stem,
        "label": label,
        "document": document,
        "date": date,
        "source": path,
        "nested": list(nested),
        "name": model.name,
        "doc_type": model.doc_type,
        "configuration": model.configuration,
        "requested_configuration": configuration,
        "named_configuration": named,
        "assembly_mark": mark,
        "format_mark": source,
        "source_format": source_format,
        "objects": model.counts.get("bodies", 0) if step else len(model.objects),
        "items": model.counts.get("bodies", 0) if step else len(model.items),
        "triangles": 0 if step else model.counts["triangles"],
        "closed": model.closed,
        "skipped": 0 if step else model.counts.get("skipped", 0),
        "display_mesh_objects": 0 if step else sum(1 for o in model.objects if o.source == "display_mesh"),
        "step": _step_data(model) if step else None,
        "warnings": [{"code": w.code, "message": w.message} for w in dict.fromkeys(warnings)],
    }


def export_to_folder(
    path: str,
    folder: str,
    fmt: str,
    out_dir: str,
    *,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    virtual: tuple[str, ...] = (),
    configuration: str | None = None,
    name: str | None = None,
    overwrite: bool = False,
    token: str | None = None,
    outside: bool = True,
) -> dict[str, Any]:
    """File > Export for 3D Printing: the document at ``path`` (read as
    :func:`export_for_print` reads it, any format SolidSeas reads, ``outside`` too)
    as ``fmt`` (``stl``
    or ``3mf``) into ``out_dir``, a folder the user chose, named after the document.
    The command line's write guards apply (:func:`.reading.output_dir`): never the
    folder of the document or the opened ``folder`` or inside either, never a
    SOLIDWORKS file name, the document itself or a link, and an existing file only
    with ``overwrite``. It is written as :func:`part_path` (``token``) and then named,
    so a stopped export leaves no file of that name."""
    from solidseas import cli as _cli
    from solidseas.export import EXTENSIONS, print_model, write_export

    from . import reading

    t0 = time.perf_counter()
    token = token or os.urandom(8).hex()
    out = reading.output_dir(out_dir, path, folder)
    nested = tuple(nested)
    with _opened(path, within or folder, nested) as doc:
        for stored in virtual:
            doc, stream = find_virtual(doc, stored)
            nested = (*nested, stream)
        if nested and name:
            document = document_name(name)
        elif nested:
            document = reading.export_stem(path, nested)
        else:
            document = os.path.splitext(os.path.basename(path))[0]
        roots = reading.roots_for(folder) if doc.doc_type == "assembly" else None
        model = print_model(doc, configuration, name=document, roots=roots, allow_outside_roots=outside)
    target = _cli.check_output_file(
        os.path.join(out, safe_stem(document) + EXTENSIONS[fmt]),
        [path],
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder)],
    )
    part = part_path(out, token)
    result = write_export(model, part, fmt)  # created new; a failed write removes it
    try:
        if overwrite:
            os.replace(part, target)
        else:
            target = _claim(part, out, [os.path.basename(target)])
    except BaseException:
        _remove_part(part)
        raise
    warnings = [*model.warnings, *(w for o in model.objects for w in o.warnings)]
    return {
        "file": target,
        "format": fmt,
        "bytes": result.bytes,
        "out_folder": out,
        "document": document,
        "doc_type": model.doc_type,
        "configuration": model.configuration,
        "objects": len(model.objects),
        "items": len(model.items),
        "triangles": model.counts["triangles"],
        "closed": model.closed,
        "skipped": model.counts.get("skipped", 0),
        "display_mesh_objects": sum(1 for o in model.objects if o.source == "display_mesh"),
        "warnings": [{"code": w.code, "message": w.message} for w in dict.fromkeys(warnings)],
        "seconds": round(time.perf_counter() - t0, 3),
    }


# --------------------------------------------------------------------------- the export's own process
# Like the 3D view's mesh reads (.meshproc), the export runs in a child process: it can be
# stopped at once (Cancel, or the window closing), it never holds the window's interpreter,
# and on Windows a job object bounds its memory and lowers its priority. One process an
# export: starting one costs a few tenths of a second, small beside the export. What
# crosses its pipe is JSON both ways, never a pickle: the child reads a file nobody vetted.
EXPORT_MEMORY = 4 << 30
MAX_MESSAGE_BYTES = 16 << 20
CANCELLED = {"ok": False, "cancelled": True}
STOPPED = {
    "code": "print_export_stopped",
    "message": "The process preparing the 3D print stopped before it finished.",
    "exception": None,
    "retryable": True,
    "detail": None,
    "reader_message": None,
}
TOO_LARGE = {
    "code": "print_export_too_large",
    "message": f"The export needed more than the {EXPORT_MEMORY >> 30} GiB of memory the viewer lets it use. "
    "A coarser chord tolerance, through the command line's export, needs less.",
    "exception": "MemoryError",
    "retryable": False,
    "detail": None,
    "reader_message": None,
}


STEP_STOPPED = {**STOPPED, "message": "The process writing the STEP file stopped before it finished."}
CONVERT_STOPPED = {**STOPPED, "message": "The process converting the file stopped before it finished."}
CONVERT_TOO_LARGE = {
    **TOO_LARGE,
    "message": f"The conversion needed more than the {EXPORT_MEMORY >> 30} GiB of memory the viewer lets "
    "it use. The command line's convert has no such limit.",
}
STEP_TOO_LARGE = {
    **TOO_LARGE,
    "message": f"The STEP export needed more than the {EXPORT_MEMORY >> 30} GiB of memory the viewer lets "
    "it use. The command line's export --format step has no such limit.",
}
PRINT_STEP_TOO_LARGE = {
    **TOO_LARGE,
    "message": f"The STEP for 3D printing needed more than the {EXPORT_MEMORY >> 30} GiB of memory the "
    "viewer lets it use. Send it as 3MF or STL instead (Settings > 3D Print Program).",
}


def _export_job(request: Any) -> dict[str, Any]:
    """One export, from the JSON request the child received: File > Export STEP's
    (``job`` ``step``, :mod:`.stepexport`), Export for 3D Printing's (``out_dir``,
    :func:`export_to_folder`) or 3D Print's (:func:`export_for_print`)."""
    if not isinstance(request, dict):
        raise ValueError("the request is not an object")
    for key in ("nested", "virtual"):
        if key in request:
            request[key] = tuple(request[key] or ())
    if request.get("job") == "step":
        from .stepexport import export_step_file

        return export_step_file(**{k: v for k, v in request.items() if k != "job"})
    if request.get("job") == "convert":
        from .convertfile import convert_file

        return convert_file(**{k: v for k, v in request.items() if k != "job"})
    if request.get("out_dir") is not None:
        for key in ("out_base", "next_to_model", "date", "cache", "confine"):
            request.pop(key, None)
        return export_to_folder(**request)
    request.pop("out_dir", None)
    request.pop("overwrite", None)
    return export_for_print(**request)


def _export_serve(conn) -> None:
    """The child: one JSON request, its export (:func:`_export_job`), and its result sent
    back as JSON."""
    import json

    try:
        request = json.loads(conn.recv_bytes(MAX_MESSAGE_BYTES))
    except (EOFError, OSError, ValueError):
        return
    step = isinstance(request, dict) and request.get("job") == "step"
    converting = isinstance(request, dict) and request.get("job") == "convert"
    print_step = isinstance(request, dict) and not step and request.get("fmt") == STEP
    try:
        result: dict[str, Any] = {"ok": True, "data": _export_job(request)}
    except MemoryError:  # past the job object's limit
        if step or converting:
            too_large = STEP_TOO_LARGE if step else CONVERT_TOO_LARGE
        else:
            too_large = PRINT_STEP_TOO_LARGE if print_step else TOO_LARGE
        result = {"ok": False, "error": dict(too_large)}
    except Exception as exc:
        from solidseas import model

        result = {"ok": False, "error": model.error_info(exc)}
    try:
        conn.send_bytes(json.dumps(result).encode("utf-8"))
    except (EOFError, OSError, MemoryError, ValueError, TypeError):  # the window sees the pipe close
        pass


def _end(proc, conn, job, *, kill: bool) -> None:
    """Close the pipe, let the child end (at once with ``kill``) and reap it."""
    try:
        conn.close()
    except OSError:
        pass
    try:
        if proc.is_alive():
            if not kill:
                proc.join(2)
            if proc.is_alive():
                proc.kill()
        proc.join(2)
    except (OSError, ValueError, AssertionError):
        pass
    if job is not None:
        job.close()


def export_in_process(
    request: dict[str, Any], cancelled=lambda: False, *, memory: int = EXPORT_MEMORY
) -> dict[str, Any]:
    """:func:`export_for_print` of ``request`` (its keyword arguments), with ``job``
    ``step`` File > Export STEP's export, with ``job`` ``convert`` File > Convert's
    (:mod:`.convertfile`), or with ``out_dir`` :func:`export_to_folder`,
    in a child process, waiting in this thread without the interpreter lock: ``{"ok":
    True, "data": ...}``, ``{"ok": False, "error": ...}``, or :data:`CANCELLED` once
    ``cancelled()`` is true, the child then ended at once and the file it was writing
    removed: a print's next to the model or in the temporary folder, an Export STEP's or
    a Convert's beside the file chosen, an Export for 3D Printing's in the folder chosen.
    Where a job object holds the child, ``memory_peak`` is the most memory it used."""
    import json

    from .meshproc import _start

    if cancelled():
        return dict(CANCELLED)
    token = os.urandom(8).hex()
    step = request.get("job") == "step"
    converting = request.get("job") == "convert"
    journal = None
    if step or converting:
        from .stepexport import part_path as step_part

        leftovers = [step_part(request["target"], token)]
    else:
        opened = request.get("folder") or ""
        if request.get("out_dir") is not None:
            folders = [os.path.abspath(request["out_dir"])]  # where its part can be, by its random name
        else:
            sweep_abandoned(request.get("out_base"), opened)  # what a viewer that ended while writing left
            # Where the child may write its part: next to the model, or the temporary folder.
            folders = [export_folder_path(request.get("out_base"))]
            here = model_folder(request["path"])
            confine = request.get("confine")
            if (
                request.get("next_to_model", True)
                and _may_look(here, opened)
                and (not confine or inside(here, confine))
            ):
                folders.append(here)
        journal = _journal(request.get("out_base"), token, folders)
        leftovers = [part_path(folder, token) for folder in folders]
    if step or converting:
        stopped_error = STEP_STOPPED if step else CONVERT_STOPPED
        name = "SolidSeas STEP export" if step else "SolidSeas convert"
    else:
        stopped_error, name = STOPPED, "SolidSeas 3D print export"
    proc, conn, job = _start(memory, target=_export_serve, name=name)
    stopped = False
    try:
        message = {**request, "token": token}
        for key in ("nested", "virtual"):
            if key in message:
                message[key] = list(message[key] or ())
        conn.send_bytes(json.dumps(message).encode("utf-8"))
        # Polled with the child's state too: a child ended before it took its end of the
        # pipe leaves that end open here, and the pipe never breaks (see .meshproc).
        while not conn.poll(0.05):
            if cancelled():
                stopped = True
                return dict(CANCELLED)
            if not proc.is_alive():
                return {"ok": False, "error": dict(stopped_error)}
        result = json.loads(conn.recv_bytes(MAX_MESSAGE_BYTES))
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            return {"ok": False, "error": dict(stopped_error)}
        if result["ok"] and not isinstance(result.get("data"), dict):
            return {"ok": False, "error": dict(stopped_error)}
        if job is not None:
            result["memory_peak"] = job.peak()  # for the self-test's report
        return result
    except (EOFError, OSError, ValueError):
        if cancelled():
            stopped = True
            return dict(CANCELLED)
        return {"ok": False, "error": dict(stopped_error)}
    finally:
        _end(proc, conn, job, kill=stopped)
        for leftover in leftovers:  # what a stopped export left: its own part, by its random name
            _remove_part(leftover)
        _close_journal(journal)


def _remove_part(path: str) -> bool:
    """Remove a ``.part`` file a stopped export left, if it is a plain file; whether one
    was removed."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISREG(st.st_mode) and not _link(st):
        try:
            os.remove(path)
            return True
        except OSError:
            pass
    return False


# --------------------------------------------------------------------------- what a crash leaves
# While an export runs, the window keeps a record of it in the temporary folder,
# "<token>.exporting", holding the folders its part may be written in, and holds it open:
# on Windows nothing can remove a file another handle has open without sharing its
# deletion, and elsewhere the record is locked. When the viewer ends while an export is
# written (a crash, End task, power lost), the job object ends the export's process with
# it and the record is left, closed: the next 3D Print removes the part it names, by its
# random name, next to the model and in the temporary folder, and then the record.
def _journal(out_base: str | None, token: str, folders: list[str]):
    """Make and hold the record of the export ``token`` (see above): the open file and
    its path, or None when the temporary folder cannot hold it (the export runs all the
    same)."""
    try:
        temp = export_folder(out_base)
    except (OSError, OutputRefusedError):
        return None
    path = os.path.join(temp, token + JOURNAL_SUFFIX)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        return None
    f = os.fdopen(fd, "wb")
    try:
        if os.name != "nt":
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"folders": folders}, ensure_ascii=True).encode("ascii"))
        f.flush()
    except OSError:
        pass
    return f, path


def _close_journal(journal) -> None:
    if journal is None:
        return
    f, path = journal
    try:
        f.close()
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


def _journal_folders(raw: bytes) -> list[str] | None:
    """The folders a record names, each an absolute path of plain text; None when it is
    not a record SolidSeas wrote."""
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    folders = value.get("folders") if isinstance(value, dict) else None
    if not isinstance(folders, list) or len(folders) > 4:
        return None
    for f in folders:
        if not isinstance(f, str) or not f or "\x00" in f or len(f) > MAX_PATH_TEXT or not os.path.isabs(f):
            return None
    return folders


def _abandoned(path: str, opened: str, *, now: float) -> list[str] | None:
    """The folders the record at ``path`` names, removed, when its export's window has
    ended; None while it runs, or while a folder it names is on a network share or
    drive other than the one opened (the record then stays, for a week, until that one
    is opened again)."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if os.name != "nt":
            import fcntl

            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:  # its window holds it: the export runs
                return None
        raw = f.read(MAX_JOURNAL_BYTES + 1)
        try:
            old = now - os.fstat(f.fileno()).st_mtime > KEEP_SECONDS
        except OSError:
            old = False
        folders = _journal_folders(raw) or []
        if not old and not all(_may_look(d, opened) for d in folders):
            return None
        if os.name != "nt" and not _unlink(path):  # removed while it is locked
            return None
    # On Windows, once this handle is closed: refused while its window holds it open.
    if os.name == "nt" and not _unlink(path):
        return None
    return [] if old else folders


def _unlink(path: str) -> bool:
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def sweep_abandoned(out_base: str | None = None, opened: str = "", *, now: float | None = None) -> int:
    """Remove the parts of the exports a viewer that ended while writing them left, as
    their records in the temporary folder under ``out_base`` name them (see above), and
    those records: each part by its own random name, in the folders its record names,
    only a plain file. ``opened`` is the folder open now. At most
    :data:`MAX_CLEAN_ENTRIES` entries of the temporary folder are looked at. How many
    parts were removed."""
    now = time.time() if now is None else now
    try:
        entries = os.scandir(export_folder_path(out_base))
    except OSError:
        return 0
    removed = 0
    with entries:
        for k, entry in enumerate(entries):
            if k >= MAX_CLEAN_ENTRIES:
                break
            token = entry.name[: -len(JOURNAL_SUFFIX)]
            if not entry.name.endswith(JOURNAL_SUFFIX) or not _TOKEN.fullmatch(token):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _link(st) or not stat.S_ISREG(st.st_mode) or st.st_size > MAX_JOURNAL_BYTES:
                continue
            for folder in _abandoned(entry.path, opened, now=now) or []:
                removed += _remove_part(part_path(folder, token))
    return removed


# --------------------------------------------------------------------------- starting the program
_FROZEN_QT = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")


def launch_environment(environ=None, bundle: str | None = None) -> dict[str, str]:
    """The environment a started program gets: the viewer's, without what the viewer's
    own packaging set for itself. PyInstaller's ``_PYI_*`` variables are dropped, and
    in the packaged viewer (``bundle``: its unpacked folder, ``sys._MEIPASS``) so are
    the Qt plugin paths and the ``PATH`` entries that point into it: a slicer built on
    another Qt (UltiMaker Cura) would load the viewer's plugins, and any program its
    DLLs. ``PYINSTALLER_RESET_ENVIRONMENT`` tells a packaged program it is not one of
    the viewer's own processes."""
    env = dict(os.environ if environ is None else environ)
    for key in list(env):
        if key.upper().startswith("_PYI_") or key.upper() == "_MEIPASS2":
            del env[key]
    if bundle:
        root = os.path.normcase(os.path.normpath(bundle))

        def bundled(p: str) -> bool:
            p = os.path.normcase(os.path.normpath(p))
            return p == root or p.startswith(root.rstrip("\\/") + os.sep)

        for key in list(env):
            if key.upper() in _FROZEN_QT and all(bundled(p) for p in env[key].split(os.pathsep) if p):
                del env[key]
            elif key.upper() == "PATH":
                env[key] = os.pathsep.join(p for p in env[key].split(os.pathsep) if p and not bundled(p))
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


class _DefaultDllDirectory:
    """While starting a program from the packaged viewer on Windows, the default DLL
    search order: PyInstaller's start-up sets the process's DLL directory to the
    viewer's unpacked folder, and a program started inherits it, searching the
    viewer's Python and runtime DLLs before its own system's. Put back afterwards.
    Process-wide, so for the instant of the start only."""

    def __init__(self, frozen: bool) -> None:
        self.active = frozen and os.name == "nt"
        self.saved: str | None = None

    def __enter__(self):
        if self.active:
            import ctypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetDllDirectoryW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
            k32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
            buf = ctypes.create_unicode_buffer(32768)
            self.saved = buf.value if k32.GetDllDirectoryW(32768, buf) else None
            self._k32 = k32
            k32.SetDllDirectoryW(None)
        return self

    def __exit__(self, *exc) -> None:
        if self.active and self.saved:
            self._k32.SetDllDirectoryW(self.saved)


def launch(program: str, path: str) -> None:
    """Start ``program`` with ``path`` as its one argument: no shell, standard handles
    to nothing, a process group of its own, so it outlives the viewer, and the
    environment and DLL search order of the viewer's packaging left behind
    (:func:`launch_environment`). The one place the viewer starts a program; tests and
    the dry run replace it."""
    import subprocess
    import sys

    frozen = bool(getattr(sys, "frozen", False))
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "shell": False,
        "cwd": os.path.dirname(program) or None,
        "env": launch_environment(bundle=getattr(sys, "_MEIPASS", None) if frozen else None),
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    with _DefaultDllDirectory(frozen):
        subprocess.Popen([program, path], **options)  # a list and no shell: the path is one argument
