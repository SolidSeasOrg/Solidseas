# PyInstaller spec for the SolidSeas Viewer preview: one executable, no console window.
#
# Build it with scripts/build-viewer.ps1, or from the repository root with the
# requirements of the "build" extra installed:
#
#     python -m PyInstaller packaging/SolidSeasViewer.spec --noconfirm --distpath dist --workpath build/pyinstaller
#
# By default it makes one file, dist/SolidSeasViewer.exe. With the environment variable
# SOLIDSEAS_ONE_FOLDER set to 1 (scripts/build-viewer.ps1 -OneFolder sets it) it makes the
# one-folder build instead: dist/SolidSeasViewer/SolidSeasViewer.exe with its libraries and
# licence texts as plain files in dist/SolidSeasViewer/_internal. That folder is what the
# installer (packaging/SolidSeas.iss) installs: it starts faster, because nothing is unpacked
# on each start, and its LGPL libraries can be replaced in place (THIRD_PARTY_NOTICES.txt 2.2).
# Both builds carry the same files and pass the same licence checks.
#
# The viewer uses QtCore, QtGui and QtWidgets, and QtOpenGL and QtOpenGLWidgets
# for the optional 3D view, which loads them only when it is turned on. The 3D
# view reads meshes in a child process: the executable started again through
# multiprocessing, which __main__.py hands over with freeze_support(). Every
# other Qt module, the Qt plugins it does not load, the software OpenGL renderer
# (opengl32sw.dll, about 20 MB: without a graphics driver the 3D view says so
# instead) and the Qt translations are left out, which keeps the executable small
# whether PySide6-Essentials or the full PySide6 is installed.
#
# The readers of the other 3D formats (solidseas.formats.step, .stl, .alibre...)
# are imported by name only when a file of their format is opened, and the viewer's
# worker processes import their jobs by name, so both are listed as hidden imports:
# without them the executable would list every such file as a format it cannot read.
#
# The modeling assistant (Tools > Modeling Assistant, or SolidSeasViewer.exe
# --assistant) is imported only when it is opened, so its modules, the AI connector
# (solidseas.ai and every provider), the machine policy and the facade its scripts
# use (solidseas.swapi.live, in the --assistant-child runner) are hidden imports too.
# The connector reaches the AI provider the user sets up over HTTPS, so the
# executable carries ssl (OpenSSL) and, when the build environment has it (the
# "build" extra installs it), truststore, which makes TLS trust the Windows
# certificate store. Without a provider set up, nothing contacts the network.
#
# Drawings (File > New Drawing, docs/DRAWINGS.md 15.6) need no new Qt module: the sheet is
# drawn with QtWidgets' graphics view and QtGui's painter, the PDF and DXF are SolidSeas'
# own writers (QtPdf and QtPrintSupport stay out), and Email PDF opens the browser through
# QtGui. The New Drawing wizard, the drawing editor, Drawing Settings and Email PDF are
# imported when first opened, and the drawing library's stages are imported by name
# (solidseas.drawing.pipeline), so all of them are hidden imports. The drawing process and
# the Email PDF process are the executable started again, which imports their modules by
# name. The library has no data files: its font widths, line types, standards and
# defaults are Python. The self-test's --drawing-dry-run reads every PDF and DXF it writes
# with the tests' own readers, tests/pdf_reader.py and tests/dxf_reader.py (the standard
# library only, sharing no code with the writers), which the executable carries for that
# alone, as it carries the STEP checker.

import importlib.metadata
import importlib.util
import os
import re
import sys

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = os.path.dirname(SPECPATH)  # noqa: F821 (SPECPATH is set by PyInstaller)
# One folder (dist/SolidSeasViewer/) rather than one file (dist/SolidSeasViewer.exe): see above.
ONE_FOLDER = os.environ.get("SOLIDSEAS_ONE_FOLDER", "").strip().lower() in ("1", "true", "yes")
# Where the one-folder build keeps everything but the executable, beside it. Inside the program
# this folder is sys._MEIPASS, as the unpacked folder is for the one-file build, so Help >
# Licences finds licenses/ in either.
CONTENTS = "_internal"
SRC = os.path.join(ROOT, "src")
ACCEPTED = os.path.join(SRC, "solidseas_app", "extensions", "accepted.json")
# The self-test's STEP checks (--export-step, --print-format step) read the files the viewer
# writes with the tests' own STEP checker, tests/step_support.py, which shares no code with
# the writer and needs only the standard library: the executable carries it for that alone,
# so its STEP export is checked without driving its window from outside. Its drawing dry run
# (--drawing-dry-run) reads PDFs and DXFs with tests/pdf_reader.py and tests/dxf_reader.py
# in the same way.
TESTS = os.path.join(ROOT, "tests")

with open(os.path.join(SRC, "solidseas", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"', fh.read(), re.M).groups()

# The executable's icon is drawn by the same code as the window icon.
sys.path.insert(0, SRC)
from solidseas_app.viewer.icon import write_ico  # noqa: E402

os.makedirs(workpath, exist_ok=True)  # noqa: F821 (workpath is set by PyInstaller)
ICON = os.path.join(workpath, "SolidSeasViewer.ico")  # noqa: F821
write_ico(ICON)

QT_MODULES_UNUSED = [
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtAxContainer", "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization", "QtDBus",
    "QtDesigner", "QtGraphs", "QtGraphsWidgets", "QtHelp", "QtHttpServer", "QtLocation",
    "QtMultimedia", "QtMultimediaWidgets", "QtNetwork", "QtNetworkAuth", "QtNfc",
    "QtPdf", "QtPdfWidgets", "QtPositioning", "QtPrintSupport", "QtQml",
    "QtQuick", "QtQuick3D", "QtQuickControls2", "QtQuickTest", "QtQuickWidgets",
    "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort", "QtSpatialAudio",
    "QtSql", "QtStateMachine", "QtSvg", "QtSvgWidgets", "QtTest", "QtTextToSpeech", "QtUiTools",
    "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets", "QtWebSockets",
    "QtWebView", "QtXml",
]
EXCLUDES = [f"PySide6.{m}" for m in QT_MODULES_UNUSED] + [
    # Optional extras of the library that the viewer never imports.
    "PIL", "numpy", "cadquery", "httpx", "keyring", "win32com", "pythoncom",
    "tkinter", "pytest",
    # Open CASCADE runs only in the OCCT backend extension's own helper program, never in
    # the viewer (docs/OCCT.md): its bindings and its helper module stay out.
    "OCP", "solidseas_app.extensions.occt_helper",
]

# The only Qt plugins the viewer loads: the Windows platform, the offscreen
# platform its self-test runs on, and the Windows styles. PNG and BMP, the two
# preview formats, are built into QtGui, so no image format plugin is needed.
KEEP_PLUGINS = {
    "platforms/qwindows.dll",
    "platforms/qoffscreen.dll",
    "platforms/qminimal.dll",
    "styles/qmodernwindowsstyle.dll",
    "styles/qwindowsvistastyle.dll",
}
DROP_DLLS = re.compile(
    r"(opengl32sw|d3dcompiler_\d+|qt6(network|pdf|svg|qml\w*|quick\w*|virtualkeyboard\w*|dbus))\.dll$",
    re.I,
)


def wanted(dest: str) -> bool:
    d = dest.replace("\\", "/")
    low = d.lower()
    if "/translations/" in low or low.endswith(".qm"):
        return False
    if "/plugins/" in low:
        return low.split("/plugins/", 1)[1] in KEEP_PLUGINS
    return not DROP_DLLS.search(os.path.basename(d))


a = Analysis(  # noqa: F821
    [os.path.join(SRC, "solidseas_app", "__main__.py")],
    pathex=[SRC, TESTS],
    binaries=[],
    # The packages this build accepts, written by scripts\build-extensions.ps1 just before;
    # without it the viewer accepts none (docs/EXTENSIONS.md section 8).
    datas=[(p, "solidseas_app/extensions") for p in [ACCEPTED] if os.path.isfile(p)],
    hiddenimports=[
        "step_support",
        "pdf_reader",
        "dxf_reader",
        *collect_submodules("solidseas.formats"),
        "solidseas.jobs",
        "solidseas.render",
        "solidseas_app.viewer.modeljobs",
        # The modeling assistant and the AI connector, imported when the assistant opens.
        *collect_submodules("solidseas_app.assistant"),
        *collect_submodules("solidseas.ai"),
        "solidseas.policy",
        "solidseas.helpers",
        # Extensions: the page, the packages and Save Animation, imported when first wanted.
        "solidseas_app.extensions",
        "solidseas_app.viewer.extensionsdialog",
        "solidseas_app.viewer.animation",
        "solidseas_app.viewer.animationaction",
        "solidseas.swapi.live",
        # Drawings: the viewer's modules imported when first wanted, the drawing process and
        # the Email PDF process, and the library, whose pipeline imports its stages by name.
        "solidseas_app.viewer.drawingaction",
        "solidseas_app.viewer.drawingwizard",
        "solidseas_app.viewer.drawingeditor",
        "solidseas_app.viewer.drawingsettings",
        "solidseas_app.viewer.drawingscene",
        "solidseas_app.viewer.drawingproc",
        "solidseas_app.viewer.mail",
        "solidseas_app.viewer.mailproc",
        *collect_submodules("solidseas.drawing"),
        # Help > Licences, imported when first opened.
        "solidseas_app.viewer.licences",
        "ssl",
        *(["truststore"] if importlib.util.find_spec("truststore") else []),
    ],
    excludes=EXCLUDES,
    noarchive=False,
)
a.binaries = [b for b in a.binaries if wanted(b[0])]
a.datas = [d for d in a.datas if wanted(d[0])]

# Licences (THIRD_PARTY_NOTICES.txt). The executable carries, in licenses\ inside it (the
# one-folder build in _internal\licenses beside it), which Help > Licences shows: SolidSeas'
# LICENSE, NOTICE and THIRD_PARTY_NOTICES.txt, every text in licenses\ of the repository, the LICENSE.txt of the Python running this build (the Python the
# executable carries, with the terms of what that Python bundles), and BUNDLED-FILES.txt, the
# list of every library inside the executable. The build stops rather than ship without them:
# when it would carry a Python package the notices do not cover, when the notices name another
# version of a package than the one it carries, or when Python's licence lacks the terms of a
# library from Python that it carries.
NOTICES = os.path.join(ROOT, "THIRD_PARTY_NOTICES.txt")
LICENCES = os.path.join(ROOT, "licenses")
PYTHON_LICENCE = os.path.join(sys.base_prefix, "LICENSE.txt")
OWN_MODULES = {"solidseas", "solidseas_app", "step_support", "pdf_reader", "dxf_reader"}
# The third-party Python packages the executable may carry: import name, distribution name.
NOTICED = {
    "PySide6": "PySide6_Essentials",
    "shiboken6": "shiboken6",
    "olefile": "olefile",
    "truststore": "truststore",
}
# The Microsoft Visual C++ runtime, which Python and PySide6 both bring.
MSVC = r"(vcruntime|msvcp|concrt|vccorlib|vcomp|vcamp)\d+"
# Libraries from Python: for each one carried, either Python's LICENSE.txt names it (the word),
# or the repository's licenses folder holds that library's own licence (the file), as it must for
# a Python whose LICENSE.txt leaves some of them out (CPython 3.12.0's names neither OpenSSL,
# SQLite, xz nor mpdecimal).
PYTHON_PARTS = {
    r"libcrypto|libssl": ("openssl", "OpenSSL-LICENSE.txt"),
    r"libffi": ("libffi", None),
    r"sqlite3": ("sqlite", "SQLite-public-domain.txt"),
    r"_bz2": ("bzip2", None),
    r"_lzma|liblzma": ("xz", "xz-COPYING.txt"),
    r"_decimal|mpdec": ("mpdec", "mpdecimal-LICENSE.txt"),
    MSVC: ("microsoft", None),
}


def _licence_failure(reason: str) -> SystemExit:
    return SystemExit(f"Not built: {reason}. THIRD_PARTY_NOTICES.txt says what each carried file needs.")


if not os.path.isfile(PYTHON_LICENCE):
    raise _licence_failure(f"there is no LICENSE.txt in {sys.base_prefix} to carry Python's licence")
with open(NOTICES, encoding="utf-8") as fh:
    NOTICES_TEXT = fh.read()
with open(PYTHON_LICENCE, encoding="utf-8", errors="replace") as fh:
    PYTHON_LICENCE_TEXT = fh.read().lower()
carried = {name.split(".")[0] for name, *_ in a.pure}
stray = sorted(
    n
    for n in carried - set(sys.stdlib_module_names) - OWN_MODULES - set(NOTICED)
    if not n.startswith(("pyimod", "_pyi", "pyi_"))
)
if stray:
    raise _licence_failure(f"it would carry {', '.join(stray)}, which the notices do not cover")
for module, dist in NOTICED.items():
    if module in carried:
        version = importlib.metadata.version(dist)
        row = re.escape(re.sub(r"[-_.]+", "-", dist).lower()) + r"\s+" + re.escape(version) + r"\s"
        if not re.search(row, NOTICES_TEXT, re.M):
            raise _licence_failure(f"the notices do not list {dist} {version}, the version it carries")
for b in a.binaries:
    base = os.path.basename(b[0]).lower()
    for pattern, (word, own) in PYTHON_PARTS.items():
        if not re.match(pattern, base) or word in PYTHON_LICENCE_TEXT:
            continue
        if own is None or not os.path.isfile(os.path.join(LICENCES, own)):
            raise _licence_failure(f"it carries {b[0]} but {PYTHON_LICENCE} has no terms for {word}")


def _group(dest: str) -> str:
    d = dest.replace("\\", "/")
    if re.match(MSVC, os.path.basename(d).lower()):
        return "Microsoft Visual C++ runtime (Microsoft Distributable Code)"
    if d.startswith(("PySide6/", "shiboken6/")):
        return "Qt, Qt for Python and shiboken6, under the LGPL version 3: these may be replaced"
    return "Python, its extension modules and the libraries Python carries"


groups: dict[str, list[str]] = {}
for b in a.binaries:
    groups.setdefault(_group(b[0]), []).append(b[0].replace("\\", "/"))
BUNDLED = os.path.join(workpath, "BUNDLED-FILES.txt")  # noqa: F821
qt_version = importlib.metadata.version("PySide6_Essentials")
built_with = f"built with Python {sys.version.split()[0]} and PySide6-Essentials {qt_version}"
if ONE_FOLDER:
    BUNDLED_INTRO = (
        f"The libraries of SolidSeasViewer.exe {'.'.join(VERSION)}, the one-folder build,\n{built_with}.\n"
        f"They are ordinary files in the {CONTENTS} folder beside SolidSeasViewer.exe, at the paths\n"
        "below (relative to that folder), and the program loads them from there each time it starts.\n"
        "The LGPL libraries may be replaced there with another build of the same version;\n"
        "THIRD_PARTY_NOTICES.txt says how.\n"
    )
else:
    BUNDLED_INTRO = (
        f"The libraries inside SolidSeasViewer.exe {'.'.join(VERSION)}, {built_with}.\n"
        "When the program runs they are unpacked into a folder named _MEI followed by digits in\n"
        "the Windows temporary folder, and removed when it ends. THIRD_PARTY_NOTICES.txt says\n"
        "how to run SolidSeas with another build of the LGPL libraries.\n"
    )
with open(BUNDLED, "w", encoding="utf-8", newline="\r\n") as fh:
    fh.write(BUNDLED_INTRO)
    for title in sorted(groups):
        fh.write(f"\n{title}\n")
        fh.writelines(f"  {d}\n" for d in sorted(groups[title], key=str.lower))
    hooks = sorted(s[0] for s in a.scripts if s[0].startswith("pyi_rth"))
    fh.write("\nPyInstaller's run-time hooks (Apache License 2.0)\n")
    fh.writelines(f"  {h}\n" for h in hooks)
OWN_TEXTS = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt")
a.datas += [(f"licenses/{n}", os.path.join(LICENCES, n), "DATA") for n in sorted(os.listdir(LICENCES))]
a.datas += [(f"licenses/{n}", os.path.join(ROOT, n), "DATA") for n in OWN_TEXTS]
a.datas += [("licenses/Python-LICENSE.txt", PYTHON_LICENCE, "DATA")]
a.datas += [("licenses/BUNDLED-FILES.txt", BUNDLED, "DATA")]

pyz = PYZ(a.pure)  # noqa: F821

numbers = tuple(int(v) for v in VERSION) + (0,)
dotted = ".".join(VERSION)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("ProductName", "SolidSeas Viewer (preview)"),
                        StringStruct("FileDescription", "SolidSeas Viewer, a read-only preview"),
                        StringStruct("FileVersion", dotted),
                        StringStruct("ProductVersion", dotted),
                        StringStruct("OriginalFilename", "SolidSeasViewer.exe"),
                        StringStruct("LegalCopyright", "Apache License 2.0"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

# The executable is the same in both builds: the one-file build packs the libraries and data
# into it, and the one-folder build leaves them out of it for COLLECT to put beside it.
EXE_OPTIONS = dict(
    name="SolidSeasViewer",
    console=False,
    debug=False,
    strip=False,
    upx=False,
    icon=ICON,
    version=version_info if sys.platform == "win32" else None,
)
if ONE_FOLDER:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        contents_directory=CONTENTS,
        **EXE_OPTIONS,
    )
    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="SolidSeasViewer",
    )
else:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        runtime_tmpdir=None,
        **EXE_OPTIONS,
    )
