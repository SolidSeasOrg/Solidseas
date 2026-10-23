"""Self-test mode, for automation: ``--self-test FOLDER --screenshot-dir DIR [--select NAME]...``.

It opens the folder in the real window, waits for the listing, saves the
Preferences dialog, selects each named document in turn (or the first
assembly, else the first document), waits for every section of its details,
and saves the window with each details tab active as a PNG, then the Preview
tab zoomed in. With ``--3d`` it also chooses 3D on the Preview tab, waits while
OpenGL starts and the part's or the assembly's meshes are read, and saves that
too; a drawing shows its stored image with a note, and that is saved instead.
``--configuration NAME`` (repeatable) then chooses that configuration of the
assembly the ``--select`` before it names, in the 3D view's own list, waits
for the view and the Components tab to show it, and saves the 3D view again.
``--explode PERCENT[,LEVEL]`` (repeatable) then explodes that assembly as the
Explode bar does, to PERCENT at LEVEL (``top`` or ``parts``; without one, the
level the bar shows, which is Every part for an assembly of one top-level component),
waits for the animation to end and saves the 3D view, failing the run when the
view did not end at that amount. ``--pick NAME`` (repeatable) then picks the
instance whose component tree id is NAME in that 3D view, with a mouse click
where the view draws it (exploded, if it was): it saves the view and the
Components tab, failing the run unless that instance alone is picked and its
row is the Components tab's current one (for an instance with no row, one read
from a sub-assembly's own file past the rows the tab shows, unless no row is
current and the sub-assembly's row stands for it, which the report names as
``row``), then
turns the view with the Left key and zooms in toward the instance with the
wheel, double-clicks it, saves the file it opens (or the dialog that says why
it cannot be), goes Back and saves the view again, failing the run unless Back
returned to the same document, tab, row, pick and camera; the camera is then
turned back as it was before the pick, so each pick starts from the same view.
The report gives each 3D view's counts, read time, upload time and the time to
draw a frame to the end (the median of five), each explode's groups and box,
each pick's pixel and outcome, and each look's pixels and checks.

``--boxes`` checks, in each 3D view of an assembly (each configuration, and each
explode), that every instance the read gives a box for, for want of a mesh, is
drawn as a box where it belongs (:func:`box_failures`, from
:meth:`.view3d.ModelView.box_report`; one too small to cover a pixel is
counted as ``subpixel``, not failed), failing the run otherwise; for the first
view it also saves the view with every box picked, then with Settings > Boxes
for Missing Meshes turned off, checking that no box is drawn then, and turns it
back on.

``--transparent NAME[,PERCENT]``, ``--hide NAME``, ``--isolate NAME`` and
``--explode-sub NAME,on|off`` (each repeatable, run in the order given, after
the picks, with nothing picked) change how the instance or sub-assembly NAME
looks in that 3D view, as its menu does, check what is drawn by reading pixels
back, save the window, and fail the run when it does not match
(:class:`LookCheck`). A pixel at the edge of a component is blended with its
neighbours by multisampling, so each check counts shares of pixels rather than
every one. Transparent (75 percent by default): of the pixels where NAME is
drawn opaque, at least :data:`LOOK_PASS` (90 percent) must now show something
else, and as many of those where what lies behind NAME differs from it must be
nearer what is behind (:data:`GROUP_LOOK_PASS`, 75 percent, when NAME is several
instances, seen through several layers of its own); of the other pixels, those more than two pixels from
NAME, at least :data:`SAME_PASS` (99 percent) must stay exactly as they were;
and a click must still pick NAME at 90 percent of its pixels with nothing
behind it. At 0 percent NAME is opaque again, so that many of all the pixels
must be as they are with NAME drawn opaque. Hidden: no pixel of the id pass may
be NAME's. Isolated: every pixel of the id pass must be NAME's, and NAME must be
drawn. The explode switch, for a sub-assembly NAME only: the view is exploded
(fully, if it was collapsed), the instances under NAME must move as one when it
is off and as their groups say when it is on (:func:`.explode.group_of`), unless
a sub-assembly around it is chosen to stay together, and each must be drawn
inside the box its offset moves it to. After the last of them the Components
tab is saved with its marks, and Reset appearance must give the first picture
back, pixel for pixel, with the explode and the camera put back as they were.

After saving each document's 3D view it turns the model over the top with a
drag of the mouse style's rotate button, 100 degrees down from the isometric
view, and saves that too (``turned_over``). Free rotation (the default, or
``--rotation free``) must carry the view past straight above, upside down, and
a turntable (``--rotation turntable``) must stop at straight above; either way
the model must still be drawn, or the run fails. The view then goes back to the
isometric view for whatever follows.

Then, from Home and back to it (:class:`NavCheck`), every click routed to the
view cube or the view as Qt routes a real one (:func:`deliver`):
``--viewcube REGION`` (repeatable) clicks the cube on a face, an edge or a
corner (``all``: the 26 in turn), through regions that are drawn when it is
not (:func:`.viewcube.path_to`), and fails the run unless the view ends there,
upright and fitted, on exactly the frame drawn when set there at once, with
nothing picked or menued, the legend's column clear, the cube showing the
region in its middle in its own colours (:meth:`.cubewidget.ViewCube.picture`)
and, for a part whose mesh is a box, the model drawn as large as its box from
there; ``home``, ``set-home`` and ``reset-home`` (from the cube's menu), the
step and roll arrows and ``drag`` are checked likewise. ``--pivot NAME``
turns the model with a drag from where NAME is drawn and fails unless the
point read under the pointer kept its pixel (or, with ``--pivot-at centre``,
unless it moved), ``--pivot .`` unless a turn from empty space was about the
middle of the free area; ``--input-checks`` checks the sideways scroll, Ctrl
and Shift during a SOLIDWORKS middle-drag and the roll keys. Every 3D shot
reports the areas a fit may use, the cube, and whether the legend's column is
clear of the model, which fails the run when it is not. ``--configuration
NAME`` turns and zooms the view before choosing NAME (``NAME,fitted``: clicks a
fitted corner view), and the camera must stay (``kept``) or, with none of
NAME in view, be fitted from the same direction (``refit``).

``--open-component NAME`` (repeatable) then opens, from the Components tab of
the document the ``--select`` before it names (of every document, when no
``--select`` comes before it), the file of the row named NAME (an instance, a
file, a drawing view or a model) as a double-click does: it saves the window
once that file is shown (or the dialog that says why it cannot be, which it
then closes), goes Back, and saves the window again, failing the run when
Back did not return to the same document with the same row selected.

``--print-dry-run`` then presses 3D Print for each selected part or assembly, in the
configuration shown, with the window's print controller in its dry run
(:mod:`.printaction`): the document is exported as the button exports it, next to
the model in the folder under test (so run it on a copy: with this option the run
adds print files to that folder, never changing or removing one), or in the
temporary folder where the settings or the folder say so, or where the model is
outside the folder under test (a component found elsewhere: the run writes next to
no model outside it), and the program and arguments it would start are recorded in
the report (``print``) without starting anything. The export runs in its own
process, as the button's does. It saves the toolbar while the export runs (the
button is then Cancel 3D Print) and after it, the Settings > 3D Print Program menu
and Preferences, then presses 3D Print again (``print_again``). Each print is
checked (``print_checks``): the file must be next to the model (or in the temporary
folder, with the reason said), named after the document (a virtual component after
the name the window shows) with the configuration exported when it is not the active
one, and today's date, its full path in the note, the configuration exported in the
note when it is not the one asked for, and the second one numbered one higher than
the first, ``(2)`` after the first of the day. The run fails when a check fails, the
export failed or a program was found and could not be used; with no program found,
the report says the window would have asked.
``--print-row NAME`` (repeatable, with ``--print-dry-run``) then prints, twice, the
file of the row named NAME on the Components tab (an instance, or a file of the
Files table) or the BOM tab through that row's context menu, and ``--print-view
NAME`` through the 3D view's menu of the instance NAME, its part, or with
``NAME,sub`` the nearest sub-assembly it is in, and ``--print-view .`` the 3D view's
menu of empty space, 3D Print This Assembly (or This Part). With ``--3d`` and the 3D
view drawn, the view is right-clicked where it draws the instance (or where it draws
nothing) and the entry chosen in the menu that opens; otherwise the entry is chosen
in the menu the right-click would open; that menu is saved the first time
(``<document>_print_menu_<what>``). Each is checked as the button's prints are,
against the folder of the file the row stands for (a virtual component's: the
document that stores it, the assembly or a sub-assembly; a part the 3D view read
from a sub-assembly's own file: the file its mesh came from), and reported in
``print_menus``.
``--print-format FORMAT`` (``3mf``, ``stl`` or ``step``, with ``--print-dry-run``)
chooses that format for the run's program first, as Settings > 3D Print Program does
(in the run's own settings file), and fails the run when no program is found (the
window would ask, so no print is made to check) or the program does not take it.
A print sent as STEP is waited for up to the STEP export's limit and its 3MF's time
on top. Every print is then checked for it too: its extension is the format's, and a
STEP passes the tests' own independent checker (:func:`step_checker`,
``tests/step_support.py``: its syntax, its topology, and its vertices and edges on
their curves and surfaces), whose numbers the report gives (``step_check``); a print
asked for as STEP that went as 3MF must say why in its note, and an assembly, which
the STEP export does not write yet, must go as 3MF with that reason, as must a 3D
file of a format the STEP export does not write, judged by what the file holds
(the print's ``source_format``), not by its name.

``--export-step`` then exports each selected part with File > Export STEP, as the
menu does, its save dialog answered with a folder the run makes in the system's
temporary folder and its questions answered no (a file without some of its bodies is
never written), checks the file with the same checker, reports it (``export_step``)
and removes that folder. The entry must be off for a drawing, and off with its
tooltip saying why for what the STEP export does not write (an assembly, or a part of
a 3D file of another format than SOLIDWORKS and Parasolid: an STL, a STEP, an Alibre
Design part...); a part it is off for without a reason, or on for with one, fails. So a
check of the packaged viewer's STEP export needs no window automation: the packaged
viewer carries the checker for this alone.

``--drawing-dry-run`` then makes a drawing of each selected SOLIDWORKS part with File >
New Drawing, as the menu does, with the window's drawing controller in its dry run
(:mod:`.drawingaction`: it shows no dialog or message) and Drawing Settings of the
run's own (the fictional "Example Engineering Co.", two people to sign, millimetres
for parts that state no unit, and a folder the run makes in the system's temporary
folder for the files), written to ``Drawing.json`` in that folder, never the user's.
The New Drawing wizard and the drawing editor are stood in for by the run
(:class:`DryRunWizard`, :class:`DryRunEditor`), which the controller makes and hands
the drawing from one to the other as it does the real ones, and which do what they
do, through the window's drawing process (:class:`.drawingproc.DrawingWorker`) and
the drawing file's rules (``drawing.document``, ``docs/DRAWINGS.md`` 12.6), with the
answers a person would give (:func:`dry_wizard_run`, :func:`dry_editor_run`). The
wizard reads the part (page 1) and takes the unit it states, or the one it guesses;
types a title, a number of the run's own (``ST-001``, ``ST-002``...), revision A, a
material of the settings' list, a finish and the first person as DRAWN (page 2); keeps every other
default; and writes the drawing file with its PDF and DXF into that folder (page 6).
The editor then removes a dimension, restores it and undoes both; signs CHECKED and
APPROVED; saves, replacing its own drawing file and keeping its PRELIMINARY PDF and
DXF current; releases (accepting, with a typed reason, the items a release may
accept when it is first refused), writes the released PDF and DXF and saves; starts
revision B and saves; and sends Email PDF, after the PRELIMINARY question, with
stand-ins for the mail program, the file manager and the browser, so nothing is
started. Every PDF and DXF is then checked with the tests' own readers
(:func:`check_pdf_file`, :func:`check_dxf_file`: ``tests/pdf_reader.py`` and
``tests/dxf_reader.py``, which the packaged viewer carries for this): it is read as a
whole, says SolidSeas wrote it, and has the PRELIMINARY stamp exactly when it is not
a released file. So are the names, the files replaced (only the drawing's own
unchanged ones), the released files (never written again), the drawing file read
back (revision B, PRELIMINARY, every file in its record with the hash it has), the
wizard and editor the controller made (the part, configuration and folder shown, the
run's settings, one drawing process), and that nothing was written beside the part.
The report gives each step (``drawing``) and, with screenshots, saves the sheet as
the editor would show it. A failed check fails the run, and the folder is then kept
for a look (``kept_in``), else removed. An assembly is drawn the same way, without a
material or finish of its own; its drawing has no dimensions, so the editor leaves
out removing one and its undo, and its sheet must carry the parts list and a
balloon. A SOLIDWORKS drawing or a 3D file of another format must have New Drawing
off with its tooltip saying why, and is reported as not drawable; one it is on for,
or off for without a reason, fails.

It ends by writing a JSON report (counts, timings, errors, and with ``--3d``
the mesh process's start count and peak memory) and leaving the event loop
with exit code 0 when nothing failed, else 1. It runs under
``QT_QPA_PLATFORM=offscreen`` as well as on screen; offscreen there is no
OpenGL, so the 3D view shows its message.

The self-test never reads or changes your settings. It runs with a settings
file of its own, ``selftest-settings.ini`` next to its report (:func:`settings_output`),
which says whether the 3D view is on.

``--quick-filter TYPES`` (repeatable; TYPES are quick filter types or extensions,
``sldprt,step``) runs once the folder is listed, before any document is selected:
it turns those types on, the first with the keyboard (focus and Space) and the
others with a click on their buttons, and fails the run unless each has a button,
the list shows exactly the rows of those types the other filters let through, the
types on are those, and the number each button's tooltip gives is the number of
rows of its type the list then shows. It saves the window in the Details and the
Icons view, presses All, and fails the run unless every type shows again
(``quick_filters`` in the report). It does not go with ``--select-all``, whose
report names no documents.

``--select-all`` reads the details of every listed document instead, without
screenshots, and the report then gives only counts, timings and error codes,
never document names: it is meant for robustness runs over private folders.
A document with a section or tab that failed fails the run.

The self-test ships in the viewer, so its outputs pass the same write guards
as an export (:func:`outputs`): the screenshot folder and the report must lie
outside the folder under test, the report never has a SOLIDWORKS file name,
and an existing file, the report or a screenshot, is replaced only with
``--force``. A refused output stops the run before anything is opened. The print
files of ``--print-dry-run`` are the one exception, by design: they are new files
next to the models in the folder under test, as 3D Print puts them.
"""

import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
from typing import Any

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QPointF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from solidseas import __version__
from solidseas import cli as _cli

from . import printing, viewcube, viewmath
from .details import KEY_ROLE, OPEN, PARENT_ROLE, TABS
from .explode import TOP, group_of, held_by
from .preferences import PreferencesDialog
from .preview import IMAGE, MODEL
from .viewcube import STEPS
from .viewmath import DEGREES_PER_PIXEL, FREE, PITCH_LIMIT, SOLIDWORKS, WHEEL_STEP
from .window import MainWindow
from .workers import Job

DOC_TIMEOUT_S = 120.0
STEP_TIMEOUT_S = 330.0  # the STEP export stops itself at 300 seconds
EXPLODE_TIMEOUT_S = 10.0  # an animation takes half a second at most
LISTING_TIMEOUT_S = 3600.0
SETTINGS_NAME = "selftest-settings.ini"
ZOOM = 2.5  # the zoomed preview shot's magnification
TURN_OVER_DEGREES = 100.0  # from the isometric view (35 degrees up), 45 past straight above
LOOK_ACTIONS = ("transparent", "hide", "isolate", "explode-sub")
DEFAULT_TRANSPARENCY = 75
# Of the pixels a check looks at, the share that must pass it: a pixel at the edge of a
# component is blended with its neighbours by multisampling, which a few may not survive.
LOOK_PASS = 0.9
SAME_PASS = 0.99
# Made transparent, a NAME of several instances (a sub-assembly, or a file's) is seen
# through several of its own layers where its parts overlap, and each layer keeps some of
# its colour, so fewer of its pixels come nearer what is behind it than a single part's:
# 86 percent for a development corpus sub-assembly of 21 parts at 75 percent. Drawn opaque
# by mistake, none would.
GROUP_LOOK_PASS = 0.75
# --drawing-dry-run: the time one part's drawing may take, made, edited, signed, released,
# revised and sent; the run's own company and people (fictional); and what it types.
DRAWING_TIMEOUT_S = 300.0
DRY_COMPANY = "Example Engineering Co."
DRY_PEOPLE = ({"name": "Alex Drafter", "initials": "AD"}, {"name": "Casey Checker", "initials": "CC"})
DRY_TITLE = "SELF-TEST DRAWING"
DRY_NUMBER = "ST"  # each drawing's number: ST-001, ST-002...
DRY_MATERIAL = "6061-T6"  # in Drawing Settings' list of materials: ALUMINUM 6061-T6
DRY_FINISH = "Clear anodize"
DRY_REASON = "Accepted by the self-test's dry run"
DRY_REVISION = "SELF-TEST REVISION"

# Why a write guard refused a self-test output, in the self-test's own terms: the
# guards' messages name options of the solidseas command line it does not have.
_REASONS = {
    "source_folder": "that is in or below the folder under test; choose a place outside it",
    "solidworks_file": "that has a SOLIDWORKS file name",
    "exists": "that file already exists; pass --force to replace it",
    "link": "that file is a link, and writing would follow it",
    "hard_link": "that file is a hard link, and another name shares its data",
}


def _refused(what: str, path: str, exc: _cli.Refused) -> _cli.Refused:
    reason = _REASONS.get((exc.detail or {}).get("rule") or "", str(exc))
    return _cli.Refused(f"the self-test will not write its {what} to {path}: {reason}", detail=exc.detail)


def outputs(
    folder: str,
    screenshot_dir: str | None,
    report: str | None,
    *,
    select_all: bool = False,
    force: bool = False,
) -> tuple[str | None, str | None]:
    """The screenshot folder and the report path a self-test of ``folder`` may write,
    checked by the library's write guards; raises ``OutputRefusedError`` otherwise."""
    folder = os.path.abspath(folder)
    shots = None
    if screenshot_dir:
        try:
            checked = _cli.check_output_dir(screenshot_dir, [folder], allow_source_dir=False)
        except _cli.Refused as exc:
            raise _refused("screenshots", screenshot_dir, exc) from None
        shots = None if select_all else checked
    path = report or (os.path.join(screenshot_dir, "selftest.json") if screenshot_dir else None)
    if path:
        try:
            path = _cli.check_output_file(path, [], allow_source_dir=False, force=force, source_dirs=[folder])
        except _cli.Refused as exc:
            raise _refused("report", path, exc) from None
    return shots, path


def settings_output(folder: str, report: str, *, force: bool = False) -> str:
    """The self-test's own settings file, next to its ``report`` (already checked by
    :func:`outputs`), through the same write guards."""
    path = os.path.join(os.path.dirname(os.path.abspath(report)), SETTINGS_NAME)
    try:
        return _cli.check_output_file(
            path, [], allow_source_dir=False, force=force, source_dirs=[os.path.abspath(folder)]
        )
    except _cli.Refused as exc:
        raise _refused("settings", path, exc) from None


_CHECKER: list[Any] = []  # the checker, once looked for: [module or None]


def step_checker():
    """The tests' own STEP checker (``tests/step_support.py``), which reads a STEP file
    with none of the export's code: from the source tree a run from source has, or
    bundled into the packaged viewer for its self-test (``packaging``); None when this
    viewer has neither."""
    if _CHECKER:
        return _CHECKER[0]
    module = None
    if getattr(sys, "frozen", False):
        try:
            import step_support as module  # bundled by packaging/SolidSeasViewer.spec
        except ImportError:
            module = None
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "..", "..", "tests", "step_support.py"))
        spec = importlib.util.spec_from_file_location("solidseas_selftest_step_support", path)
        if spec is not None and spec.loader is not None and os.path.isfile(path):
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:  # an unreadable checker: none
                module = None
    _CHECKER.append(module)
    return module


def check_step_file(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check the STEP file at ``path`` with :func:`step_checker`, allowing for the
    deviation and tolerance its export reported in ``data``: the checker's numbers, and
    ``problems`` (empty when it passes; a checker this viewer lacks is one)."""
    checker = step_checker()
    if checker is None:
        return {
            "checker": None,
            "problems": ["the STEP checker (tests/step_support.py) is not in this viewer"],
        }
    data = data or {}
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        got = checker.file_check(
            raw, deviation_mm=data.get("max_deviation_mm"), tolerance_mm=data.get("max_tolerance_mm")
        )
    except Exception as exc:  # the checker failed on it: that is the file's problem to report
        return {
            "checker": "tests/step_support.py",
            "problems": [f"the checker failed: {type(exc).__name__}: {exc}"],
        }
    if got.get("file_name") not in (None, os.path.basename(path)):
        got["problems"] = [*got["problems"], f"its header names {got['file_name']}, not its own name"]
    return {"checker": "tests/step_support.py", **got}


# -- the drawing dry run (--drawing-dry-run) -------------------------------------------------
_READERS: dict[str, Any] = {}  # the tests' PDF and DXF readers, once looked for: module or None


def tests_reader(name: str):
    """The tests' own reader ``tests/<name>.py`` (``pdf_reader`` or ``dxf_reader``), which
    reads a file the writers made with none of their code: from the source tree a run
    from source has, or bundled into the packaged viewer for its self-test
    (``packaging``); None when this viewer has neither."""
    if name in _READERS:
        return _READERS[name]
    module = None
    if getattr(sys, "frozen", False):
        try:
            module = importlib.import_module(name)  # bundled by packaging/SolidSeasViewer.spec
        except ImportError:
            module = None
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "..", "..", "tests", f"{name}.py"))
        spec = importlib.util.spec_from_file_location(f"solidseas_selftest_{name}", path)
        if spec is not None and spec.loader is not None and os.path.isfile(path):
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module  # its dataclasses look their module up by name
            try:
                spec.loader.exec_module(module)
            except Exception:  # an unreadable reader: none
                sys.modules.pop(spec.name, None)
                module = None
    _READERS[name] = module
    return module


def check_pdf_file(path: str, *, stamped: bool) -> dict[str, Any]:
    """Check the PDF at ``path`` with the tests' PDF reader: the whole file read (the
    header, the cross-reference table with every offset checked, the trailer, every
    object and the page's content), one page with its catalog, ``/Producer`` naming
    SolidSeas, its layers, and the PRELIMINARY stamp exactly when ``stamped``. The
    reader's counts and ``problems`` (empty when it passes)."""
    reader = tests_reader("pdf_reader")
    if reader is None:
        return {"checker": None, "problems": ["the PDF checker (tests/pdf_reader.py) is not in this viewer"]}
    out: dict[str, Any] = {"checker": "tests/pdf_reader.py"}
    problems: list[str] = []
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        doc = reader.PdfDocument(data)
        runs = [r.text for r in doc.text_runs()]
        out.update(
            bytes=len(data),
            version=doc.version,
            objects=len(doc.objects),
            paths=len(doc.paths()),
            text_runs=len(runs),
            layers=doc.ocg_names(),
        )
        if doc.get(doc.catalog, "Type") != "Catalog" or doc.get(doc.page, "Type") != "Page":
            problems.append("it has no catalog and page")
        box = doc.media_box()
        if len(box) != 4 or not (box[2] > box[0] and box[3] > box[1]):
            problems.append(f"its page has no size ({box})")
        if not str(doc.info().get("Producer") or "").startswith("SolidSeas"):
            problems.append("it does not say SolidSeas wrote it")
        if not runs:
            problems.append("it has no text")
        stamp = any("PRELIMINARY" in t for t in runs)
        if stamp != stamped:
            problems.append("it has the PRELIMINARY stamp" if stamp else "it lacks the PRELIMINARY stamp")
    except Exception as exc:  # the reader refused it: that is the file's problem to report
        problems.append(f"the reader refused it: {type(exc).__name__}: {exc}")
    out["problems"] = problems
    return out


def check_dxf_file(path: str, *, stamped: bool) -> dict[str, Any]:
    """Check the DXF at ``path`` with the tests' DXF reader: its sections in order with
    one line ending, a ``999`` comment naming SolidSeas, every handle unique and every
    reference resolving, every layer, line type and text style used defined in its
    tables, every DIMENSION with its block and measured text (the checks the DXF tests
    make of every part), and the PRELIMINARY stamp, its TEXT on layer STAMP (which also
    holds the plot stamp), exactly when ``stamped``. The reader's counts and
    ``problems`` (empty when it passes)."""
    reader = tests_reader("dxf_reader")
    if reader is None:
        return {"checker": None, "problems": ["the DXF checker (tests/dxf_reader.py) is not in this viewer"]}
    out: dict[str, Any] = {"checker": "tests/dxf_reader.py"}
    problems: list[str] = []
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        doc = reader.read(data)
        drawn = reader.drawn(doc)
        dims = doc.find("DIMENSION")
        out.update(bytes=len(data), sections=doc.sections, entities=len(drawn), dimensions=len(dims))
        if not doc.comments or not doc.comments[0].startswith("SolidSeas"):
            problems.append("it does not say SolidSeas wrote it")
        handles = doc.handles()
        if len(handles) != len(set(handles)):
            problems.append("a handle is given twice")
        known = set(handles)
        if any(v != "0" and v not in known for _r, _c, v in doc.references()):
            problems.append("a reference names no record")
        for what, used, table in (
            ("layer", {n.upper() for n in reader.used_layers(doc)}, "LAYER"),
            ("line type", {n.upper() for n in reader.used_linetypes(doc)}, "LTYPE"),
            ("text style", {n.upper() for n in reader.used_styles(doc) if n}, "STYLE"),
        ):
            defined = {n.upper() for n in doc.tables[table].names()} if table in doc.tables else set()
            if not used <= defined:
                problems.append(f"a {what} it uses is not defined ({', '.join(sorted(used - defined))})")
        for d in dims:
            if "<>" not in (d.get(1) or "") or d.get(2) not in doc.blocks:
                problems.append("a DIMENSION lacks its measured text or its block")
                break
        stamp = any(
            e.layer == "STAMP" and e.type in ("TEXT", "MTEXT") and "PRELIMINARY" in e.text for e in drawn
        )
        if stamp != stamped:
            problems.append("it has the PRELIMINARY stamp" if stamp else "it lacks the PRELIMINARY stamp")
    except Exception as exc:  # the reader refused it: that is the file's problem to report
        problems.append(f"the reader refused it: {type(exc).__name__}: {exc}")
    out["problems"] = problems
    return out


def dry_run_settings(folder: str) -> Any:
    """The dry run's Drawing Settings: the defaults, the fictional company and two people
    to sign, millimetres for a part that states no unit, and the files in ``folder``."""
    from solidseas.drawing import settings as drawing_settings

    s = drawing_settings.DrawingSettings()
    for group, key, value in (
        ("company", "name", DRY_COMPANY),
        ("people", "people", [dict(p) for p in DRY_PEOPLE]),
        ("standard", "unit_for_unstated", "mm"),
        ("files", "folder", folder),
    ):
        s = drawing_settings.with_value(s, group, key, value)
    return s


def _write_exports(worker: Any, drawing: Any, folder: str, kinds) -> tuple[Any, list[dict[str, Any]]]:
    """Export ``drawing`` as each of ``kinds`` (``pdf``, ``dxf``) into ``folder`` as the
    wizard and the editor do: the bytes from the drawing process, the name and what may
    be replaced from ``document.export_target``, written by ``write_output`` and
    recorded in the drawing's outputs. The drawing with them, and what was written."""
    from solidseas.drawing import document

    files = []
    for kind in kinds:
        data = worker.export(drawing, kind).data
        target = document.export_target(drawing, folder, kind)
        saved = document.write_output(target.path, lambda fh, d=data: fh.write(d), replaces=target.replaces)
        name = os.path.basename(saved.path)
        drawing = document.record_output(drawing, kind, name, saved.sha256)
        files.append(
            {
                "kind": kind,
                "name": name,
                "bytes": saved.size,
                "replaced": target.replaces is not None,
                "released": drawing.status == "RELEASED",
            }
        )
    return drawing, files


def dry_wizard_run(
    worker: Any, part: str, configuration: str | None, settings: Any, opened: str | None, number: str
) -> dict[str, Any]:
    """What the New Drawing wizard does, with the answers the dry run gives (see the
    module notes), run in a worker thread: the part read, the drawing made, its folder
    checked, and the drawing file, PDF and DXF written there under 12.6's rules. Its
    record: ``ok``, ``path`` (the drawing file), what each page did, and ``problems``."""
    from solidseas.drawing import document, locate
    from solidseas.drawing.types import DrawingOptions

    rec: dict[str, Any] = {"ok": False, "problems": []}
    t = time.perf_counter()
    probe = worker.probe(part, configuration)
    rec["probe"] = {
        "configuration": probe.configuration,
        "unit": probe.unit,
        "unit_origin": probe.unit_origin,
        "size_mm": None if probe.size_mm is None else [round(v, 4) for v in probe.size_mm],
        "counts": dict(probe.counts),
        "refused": probe.refused,
        "warnings": list(probe.warnings),
    }
    asm = getattr(probe, "assembly", None)
    if asm is not None:
        rec["probe"]["assembly"] = {
            "items": asm.items,
            "instances": asm.instances,
            "left_out": list(asm.left_out),
        }
    if probe.refused:
        rec["problems"].append(f"the part was refused: {probe.refused}")
        return rec
    # Page 1: the unit the part states; for one that states none, the guess is clicked.
    units = "part" if probe.unit_origin == "file" else (probe.unit or settings.standard.unit_for_unstated)
    fields = {
        "title": DRY_TITLE,
        "number": number,
        "revision": "A",
        "material": DRY_MATERIAL,
        "finish": DRY_FINISH,
        "drawn_by": DRY_PEOPLE[0]["name"],
    }
    if asm is not None:  # an assembly's materials and finishes are its parts'
        del fields["material"], fields["finish"]
    answer = worker.make(part, DrawingOptions(units=units, configuration=configuration), fields, settings)
    made = answer.drawing
    levels: dict[str, int] = {}
    for c in answer.checks:
        levels[c.level] = levels.get(c.level, 0) + 1
    rec["make"] = {
        "units": units,
        "number": number,
        "status": made.status,
        "revision": document.current_revision(made),
        "dimensions": sum(1 for d in made.dimensions if d.state == "shown"),
        "checks": levels,
        "seconds": round(answer.seconds.get("wall", 0.0), 3),
    }
    if made.status != "PRELIMINARY":
        rec["problems"].append(f"a new drawing is {made.status}, not PRELIMINARY")
    # Page 6: the folder Drawing Settings name (next to the part when none), checked first.
    folder = settings.files.folder or os.path.dirname(os.path.abspath(part))
    problem = document.folder_problem(folder, opened)
    if problem is not None:
        rec["problems"].append(f"the folder was refused: {problem}")
        return rec
    path = os.path.join(folder, document.drawing_file_name(made))
    drawing = locate.with_model_path(made, part, path)
    drawing, files = _write_exports(worker, drawing, folder, ("pdf", "dxf"))
    target = document.save_target(drawing, path)
    saved = document.save(drawing, target.path, replaces=target.replaces)
    rec["files"] = [*files, {"kind": "ssdrw", "name": os.path.basename(saved.path), "bytes": saved.size}]
    rec["seconds"] = round(time.perf_counter() - t, 3)
    rec.update(ok=not rec["problems"], path=saved.path)
    return rec


def dry_editor_run(worker: Any, path: str, settings: Any) -> dict[str, Any]:
    """What the drawing editor does with the drawing at ``path`` in the dry run (see the
    module notes), run in a worker thread: each step's status and revision, the files
    written, the release and Email PDF with stand-ins that start nothing. Its record:
    ``ok``, ``steps``, ``email``, the drawing's ``number`` and ``problems``; for an
    assembly ``parts``, its parts list's items and the balloons on its sheet."""
    from solidseas.drawing import display as D
    from solidseas.drawing import document
    from solidseas.drawing.assembly import is_assembly
    from solidseas.errors import ModelNotFoundError

    rec: dict[str, Any] = {"ok": False, "steps": [], "problems": []}
    problems: list[str] = rec["problems"]
    folder = os.path.dirname(os.path.abspath(path))
    loaded = document.read(path)
    current, sha = loaded.drawing, loaded.sha256
    t = time.perf_counter()

    def edit(d: Any, op: str, args: Any) -> Any:
        try:
            return worker.edit(d, op, args)
        except ModelNotFoundError:  # a drawing process started again: the model attached first
            worker.attach(d, drawing_path=path)
            return worker.edit(d, op, args)

    def state(d: Any, ident: str) -> str | None:
        return next((x.state for x in d.dimensions if x.id == ident), None)

    def step(name: str, d: Any, **extra: Any) -> None:
        rec["steps"].append(
            {"step": name, "status": d.status, "revision": document.current_revision(d), **extra}
        )

    def save(d: Any, *, keep_current: bool = True) -> Any:
        """Save as the editor saves: its own unchanged file replaced, and the current
        revision's PRELIMINARY exports rewritten to keep them current."""
        nonlocal sha
        written: list[dict[str, Any]] = []
        rev = document.current_revision(d)
        kinds = sorted({o.kind for o in d.outputs if not o.released and o.revision == rev})
        if keep_current and kinds and d.status != "RELEASED" and settings.files.keep_preliminary_current:
            d, written = _write_exports(worker, d, folder, kinds)
        target = document.save_target(d, path, loaded_sha256=sha)
        if target.path != os.path.abspath(path) or target.replaces != sha:
            problems.append(f"Save did not replace the drawing's own file: {target.words}")
        saved = document.save(d, target.path, replaces=target.replaces)
        sha = saved.sha256
        step("save", saved.drawing, files=written)
        return saved.drawing

    if is_assembly(current):
        sheet = current.sheet.annotations if current.sheet is not None else ()
        if not any(isinstance(a, D.PartsList) for a in sheet):
            problems.append("the assembly's drawing has no parts list")
        if not any(isinstance(a, D.Balloon) for a in sheet):
            problems.append("the assembly's drawing has no balloon")
        rec["parts"] = {
            "items": sum(len(a.rows) for a in sheet if isinstance(a, D.PartsList)),
            "balloons": sum(1 for a in sheet if isinstance(a, D.Balloon)),
        }
        return _signed_released_revised(rec, current, edit, step, save, worker, folder, settings, t)
    shown = [x.id for x in current.dimensions if x.state == "shown"]
    if not shown:
        problems.append("the drawing shows no dimension")
        return rec
    ident = shown[0]
    undo = [current]
    removed = edit(current, "remove", [ident])
    undo.append(removed.drawing)
    step("remove", removed.drawing, dimension=ident, state=state(removed.drawing, ident))
    restored = edit(removed, "restore", [ident])
    undo.append(restored.drawing)
    step("restore", restored.drawing, dimension=ident, state=state(restored.drawing, ident))
    if state(removed.drawing, ident) != "removed" or state(restored.drawing, ident) != "shown":
        problems.append(f"remove and restore did not take {ident} off the sheet and back")
    undo.pop()  # Undo, as the editor's stack gives back the drawing it had
    once = undo[-1]
    undo.pop()
    current = undo[-1]  # and again: the drawing as it was opened
    step("undo", once, dimension=ident, state=state(once, ident))
    step("undo", current, dimension=ident, state=state(current, ident))
    if state(once, ident) != "removed":
        problems.append("undo did not give back the drawing with the dimension removed")
    if [(x.id, x.state) for x in restored.drawing.dimensions] != [
        (x.id, x.state) for x in current.dimensions
    ]:
        problems.append("remove and restore did not give back the dimensions the drawing had")
    return _signed_released_revised(rec, current, edit, step, save, worker, folder, settings, t)


def _signed_released_revised(
    rec: dict[str, Any],
    current: Any,
    edit: Any,
    step: Any,
    save: Any,
    worker: Any,
    folder: str,
    settings: Any,
    t: float,
) -> dict[str, Any]:
    """The editor's dry run from signing on (see :func:`dry_editor_run`): sign CHECKED and
    APPROVED, save, release, write the released files, save, start revision B, save,
    and Email PDF."""
    from types import SimpleNamespace

    from solidseas.drawing import document
    from solidseas.drawing.release import ReleaseRefusedError

    from . import mail

    problems: list[str] = rec["problems"]
    for row, person in (("CHECKED", DRY_PEOPLE[1]), ("APPROVED", DRY_PEOPLE[0])):
        current = edit(current, "sign", [row, person["name"]]).drawing
        step(f"sign {row}", current, signatures=[s.row for s in current.signatures])
    if current.status != "CHECKED":
        problems.append(f"signing CHECKED left the drawing {current.status}")
    current = save(current)
    release: dict[str, Any] = {"accepted": {}}
    try:
        answer = worker.release(current)
    except ReleaseRefusedError as exc:
        release["refused"] = list(exc.reasons)
        accepted = {"material": DRY_REASON}
        for c in worker.checks(current, at_release=True):
            if c.code in ("COV.unclaimed", "R2.override"):
                accepted[c.item or c.code] = DRY_REASON
        release["accepted"] = accepted
        try:
            answer = worker.release(current, accepted)
        except ReleaseRefusedError as again:
            problems.append("the release was refused: " + "; ".join(again.reasons))
            rec["release"] = {**release, "refused_again": list(again.reasons)}
            return rec
    rec["release"] = release
    current = answer.drawing
    step("release", current)
    if current.status != "RELEASED":
        problems.append(f"the release left the drawing {current.status}")
    current, released = _write_exports(worker, current, folder, ("pdf", "dxf"))
    if any(f["replaced"] for f in released):
        problems.append("a released file replaced another file")
    current = save(current)
    hashes = {o.name: o.sha256 for o in current.outputs if o.released}
    current = edit(
        current, "start_revision", {"description": DRY_REVISION, "drawn_by": DRY_PEOPLE[0]["name"]}
    )
    current = current.drawing
    step("start revision", current, revisions=[r.rev for r in current.revisions])
    current = save(current)
    # Email PDF: the PRELIMINARY question answered yes, the PDF made current, then sent with
    # stand-ins for the mail program, the file manager and the browser.
    question = mail.preliminary_question(current.status)
    current, pdfs = _write_exports(worker, current, folder, ("pdf",))
    current = save(current, keep_current=False)
    pdf = os.path.join(folder, pdfs[0]["name"])
    shown_files: list[str] = []
    opened: list[str] = []
    attached: list[str] = []

    def attach(p: str, name: str, subject: str = "") -> Any:
        attached.append(os.path.basename(p))
        return SimpleNamespace(code=0, reason=None, cancelled=False)

    route = mail.choose_route(settings.email.method)
    number, title = document.title_text(current, "number"), document.title_text(current, "title")
    delivery = mail.email_pdf(
        pdf,
        number,
        title,
        settings.email,
        route=route,
        attach=attach,
        show=lambda p: shown_files.append(os.path.basename(p)) or True,
        open_url=opened.append,
    )
    rec["email"] = {
        "question": question,
        "pdf": os.path.basename(pdf),
        "route": route.kind,
        "delivered": delivery.route,
        "status": delivery.status,
        "url": delivery.url,
        "shown": shown_files,
        "opened": opened,
        "attached": attached,
    }
    for name, recorded in hashes.items():
        if document.file_sha256(os.path.join(folder, name)) != recorded:
            problems.append(f"the released {name} was written again")
    rec["number"] = number
    rec["released"] = sorted(hashes)
    rec["seconds"] = round(time.perf_counter() - t, 3)
    rec["ok"] = not problems
    return rec


class DryRunWizard(QObject):
    """The New Drawing wizard, stood in for by the dry run: made by the drawing
    controller with the wizard's arguments, it runs :func:`dry_wizard_run` when shown
    (``on_show``) and then says ``drawing_written(path, True)``, as Finish does with
    Open in the Editor ticked."""

    drawing_written = Signal(str, bool)

    def __init__(
        self,
        on_show: Any,
        parent: Any,
        worker: Any,
        part: str,
        *,
        configuration: str | None = None,
        settings: Any = None,
        settings_path: str | None = None,
        folder: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.worker, self.part, self.configuration = worker, part, configuration
        self.settings, self.settings_path, self.folder = settings, settings_path, folder
        self._on_show = on_show
        self.visible = False

    def show(self) -> None:
        self.visible = True
        self._on_show(self)

    def isVisible(self) -> bool:
        return self.visible

    def close(self) -> bool:
        self.visible = False
        return True


class DryRunEditor:
    """The drawing editor, stood in for by the dry run: made by the drawing controller
    with the editor's arguments, it runs :func:`dry_editor_run` when shown
    (``on_show``)."""

    def __init__(
        self,
        on_show: Any,
        worker: Any,
        path: str,
        *,
        settings: Any = None,
        settings_path: str | None = None,
        parent: Any = None,
    ) -> None:
        self.worker, self.path, self.settings = worker, path, settings
        self.settings_path, self.parent = settings_path, parent
        self._on_show = on_show
        self.visible = False

    def show(self) -> None:
        self.visible = True
        self._on_show(self)

    def isVisible(self) -> bool:
        return self.visible

    def close(self) -> bool:
        self.visible = False
        return True

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


def _drawing_files(folder: str) -> set[str]:
    """The drawing files, PDFs and DXFs in ``folder``, by name."""
    try:
        return {n for n in os.listdir(folder) if n.lower().endswith((".ssdrw", ".pdf", ".dxf"))}
    except OSError:
        return set()


def _slug(text: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return keep.strip("_") or "document"


def _mouse(
    widget: QWidget,
    kind: QEvent.Type,
    point: tuple[float, float],
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
) -> None:
    """Send ``widget`` a mouse event of ``button`` (the left one by default) at ``point``,
    as Qt delivers a real one: a move carries the button held, without a button of its own."""
    local = QPointF(*point)
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
    event = QMouseEvent(kind, local, widget.mapToGlobal(local), pressed, held, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def click(widget: QWidget, point: tuple[float, float]) -> None:
    _mouse(widget, QEvent.Type.MouseButtonPress, point)
    _mouse(widget, QEvent.Type.MouseButtonRelease, point)


def double_click(widget: QWidget, point: tuple[float, float]) -> None:
    """Press, release, double-click and release, the events of a real double-click."""
    click(widget, point)
    _mouse(widget, QEvent.Type.MouseButtonDblClick, point)
    _mouse(widget, QEvent.Type.MouseButtonRelease, point)


def drag(
    widget: QWidget, button: Qt.MouseButton, start: tuple[float, float], end: tuple[float, float]
) -> None:
    """Press ``button`` at ``start``, move to ``end`` in ten steps and release it there."""
    _mouse(widget, QEvent.Type.MouseButtonPress, start, button)
    for k in range(1, 11):
        at = (start[0] + (end[0] - start[0]) * k / 10, start[1] + (end[1] - start[1]) * k / 10)
        _mouse(widget, QEvent.Type.MouseMove, at, button)
    _mouse(widget, QEvent.Type.MouseButtonRelease, end, button)


def covered(view: QWidget) -> float:
    """The share of the 3D view's pixels, sampled every fourth, that are not its background
    (taken from the top-left pixel)."""
    img = view.grabFramebuffer()  # type: ignore[attr-defined]
    bg = img.pixelColor(0, 0)
    samples = [
        img.pixelColor(x, y) != bg for y in range(0, img.height(), 4) for x in range(0, img.width(), 4)
    ]
    return sum(samples) / max(len(samples), 1)


def _turn_and_zoom(view: QWidget, point: tuple[float, float]) -> tuple[float, float] | None:
    """Turn the 3D view 15 degrees with the Left key and zoom in two wheel steps toward the
    instance drawn at ``point``; where that instance is drawn then, or None."""
    index = view.instance_at(*point)  # type: ignore[attr-defined]
    none = Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, none))
    p = view.pixel_of(index, clear=True) if index is not None else None  # type: ignore[attr-defined]
    if p is None:
        return None
    at = QPointF(*p)
    wheel = QWheelEvent(
        at,
        view.mapToGlobal(at),
        QPoint(),
        QPoint(0, 240),
        Qt.MouseButton.NoButton,
        none,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view, wheel)
    return view.pixel_of(index, clear=True)  # type: ignore[attr-defined]


def same_camera(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """Whether two :meth:`.view3d.ModelView.camera_state` values are the same view."""
    if a is None or b is None:
        return False

    def close(x: float, y: float) -> bool:
        return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))

    # The axes (a free camera's orientation) as one list each; a state without them (a
    # stand-in view's) compares by its yaw and pitch alone, and one without a lens shift by
    # the rest.
    axes_a, axes_b = ([v for axis in s.get("axes") or () for v in axis] for s in (a, b))
    shifts = (
        "shift" not in a
        or "shift" not in b
        or all(close(x, y) for x, y in zip(a["shift"], b["shift"], strict=True))
    )
    return (
        shifts
        and a["fitted"] == b["fitted"]
        and close(a["yaw"], b["yaw"])
        and close(a["pitch"], b["pitch"])
        and close(a["half_height"], b["half_height"])
        and all(close(x, y) for x, y in zip(a["target"], b["target"], strict=True))
        and len(axes_a) == len(axes_b)
        and all(close(x, y) for x, y in zip(axes_a, axes_b, strict=True))
    )


def box_failures(expected: list[str], drawn: list[str], report: dict[str, Any] | None) -> list[str]:
    """The instances with a box that the 3D view does not draw, for ``--boxes``: of
    ``expected`` (the ids the read gives a box for), those the view has no box for
    (``drawn``, the ids of its boxes, in order), and those its
    :meth:`.view3d.ModelView.box_report` finds missing or off the view (numbered over
    the view's instances, the boxes last, so the k-th box is ``report["boxes"]`` from
    the end); every one when there is no report but boxes are expected. A box too small
    to cover a pixel (``subpixel``) is not a failure. In time linear in the boxes."""
    if report is None:  # nothing drawn to check
        return list(expected)
    on_view = set(drawn)
    missing = [i for i in expected if i not in on_view]
    seen = set(missing)
    first = report.get("first", 0)
    for k in (*report.get("missing", []), *report.get("outside", [])):
        if 0 <= k - first < len(drawn) and drawn[k - first] not in seen:
            seen.add(drawn[k - first])
            missing.append(drawn[k - first])
    return missing


def _rgb(img) -> tuple[int, int, list[tuple[int, int, int]]]:
    """An image's width, height and pixels, red, green, blue, row by row from the top."""
    from PySide6.QtGui import QImage

    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, row = img.width(), img.height(), img.bytesPerLine()
    data = bytes(img.constBits())
    out = []
    for y in range(h):
        line = data[y * row : y * row + 4 * w]
        out.extend((line[i], line[i + 1], line[i + 2]) for i in range(0, 4 * w, 4))
    return w, h, out


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


class LookCheck:
    """One ``--transparent``, ``--hide``, ``--isolate`` or ``--explode-sub`` in the 3D view
    of ``pane`` (``view``): done as the menu does it, then checked against pixels read
    back from the view (its picture and its id pass). :meth:`run` gives the report's
    record, with ``failed`` saying why when what is drawn does not match."""

    def __init__(self, pane, view) -> None:
        self.pane, self.view = pane, view

    def run(self, action: str, name: str, value: Any) -> dict[str, Any]:
        rec: dict[str, Any] = {"action": action, "name": name}
        if value is not None:
            rec["value"] = value
        indices = self.pane.indices_of(("instance", name))
        rec["instances"] = len(indices)
        if not indices:
            rec["failed"] = "the 3D view draws no instance of that name"
            return rec
        try:
            getattr(self, "_" + action.replace("-", "_"))(rec, name, set(indices), value)
        except Exception as exc:  # recorded, so one bad check does not end the run
            rec["failed"] = f"{type(exc).__name__}: {exc}"
        return rec

    def _held_camera(self) -> dict[str, Any]:
        """The camera as it is, held still: a fitted one would fit again when what is shown
        changes, and the pictures compared must be of the same view."""
        state = self.view.camera_state()
        self.view.set_camera_state({**state, "fitted": False})
        return state

    def _picture(self, opacity: list[float] | None = None):
        view = self.view
        if opacity is not None:
            view.set_looks(opacity, [look.hidden for look in self.pane.instance_looks])
        QApplication.processEvents()
        return _rgb(view.grabFramebuffer()), view.ids_drawn()

    def _transparent(self, rec: dict[str, Any], name: str, mine: set[int], value: Any) -> None:
        percent = DEFAULT_TRANSPARENCY if value is None else int(value)
        pane = self.pane
        camera = self._held_camera()
        base = [look.opacity for look in pane.instance_looks]
        opaque = [1.0 if g in mine else a for g, a in enumerate(base)]
        clear = [0.0 if g in mine else a for g, a in enumerate(base)]
        (w, h, o_px), o_ids = self._picture(opaque)  # drawn opaque
        (_w, _h, h_px), _ = self._picture(clear)  # not drawn at all, all else the same: what is behind
        pane.set_transparency(("instance", name), percent)  # as its menu does
        QApplication.processEvents()
        (_w, _h, t_px), t_ids = self._picture()
        renderer = getattr(self.view, "renderer", None)
        rec["sorted"] = getattr(renderer, "sorted_items", None)
        rec["sort_ms"] = round(1000 * getattr(renderer, "sort_seconds", 0.0), 4)
        if o_ids is None or t_ids is None:
            rec["failed"] = "the 3D view could not draw its id pass"
            return
        bg = h_px[0]
        own = [k for k, i in enumerate(o_ids) if i in mine]
        near = set()
        for k in own:  # its pixels and their neighbours: the edges are blended
            x, y = k % w, k // w
            rows, cols = range(max(0, y - 2), min(h, y + 3)), range(max(0, x - 2), min(w, x + 3))
            near.update(yy * w + xx for yy in rows for xx in cols)
        others = [k for k in range(w * h) if k not in near]
        differ = sum(1 for k in own if _distance(t_px[k], o_px[k]) > 3)
        apart = [k for k in own if _distance(o_px[k], h_px[k]) > 12]
        between = sum(1 for k in apart if _distance(t_px[k], h_px[k]) < _distance(o_px[k], h_px[k]))
        same = sum(1 for k in others if t_px[k] == o_px[k])
        alone = [k for k in own if h_px[k] == bg]
        picked = sum(1 for k in alone if t_ids[k] in mine)
        rec.update(
            {
                "percent": percent,
                "pixels": len(own),
                "changed": round(differ / max(len(own), 1), 4),
                "toward_behind": round(between / max(len(apart), 1), 4),
                "others_same": round(same / max(len(others), 1), 4),
                "picked_alone": round(picked / max(len(alone), 1), 4),
            }
        )
        self.view.set_camera_state(camera)
        if not own:
            rec["failed"] = "it is drawn nowhere in the view"
        elif not percent:  # opaque again: drawn as it is drawn opaque, everywhere
            kept = sum(1 for k in range(w * h) if t_px[k] == o_px[k])
            rec["same"] = round(kept / max(w * h, 1), 4)
            if kept < SAME_PASS * w * h:
                rec["failed"] = "made opaque, it is not drawn as an opaque one"
        elif differ < LOOK_PASS * len(own):
            rec["failed"] = "made transparent, it is still drawn as it was"
        elif apart and between < (LOOK_PASS if len(mine) == 1 else GROUP_LOOK_PASS) * len(apart):
            rec["failed"] = "made transparent, it does not show what is behind it"
        elif same < SAME_PASS * len(others):
            rec["failed"] = "made transparent, other pixels changed"
        elif alone and picked < LOOK_PASS * len(alone):
            rec["failed"] = "made transparent, a click no longer picks it where nothing is behind it"

    def _hide(self, rec: dict[str, Any], name: str, mine: set[int], value: Any) -> None:
        _before, ids = self._picture()
        was = sum(1 for i in ids or () if i in mine)
        self.pane.set_hidden(("instance", name), True)
        _after, ids = self._picture()
        left = sum(1 for i in ids or () if i in mine)
        rec.update({"pixels_before": was, "pixels_after": left})
        if ids is None:
            rec["failed"] = "the 3D view could not draw its id pass"
        elif left:
            rec["failed"] = f"hidden, it is still picked at {left} pixels"
        elif any(self.view.pixel_of(g) is not None for g in mine):
            rec["failed"] = "hidden, it is still found in the view"

    def _isolate(self, rec: dict[str, Any], name: str, mine: set[int], value: Any) -> None:
        self.pane.isolate(("instance", name))
        _px, ids = self._picture()
        drawn = {i for i in ids or () if i is not None}
        rec.update({"drawn": len(drawn), "others": len(drawn - mine)})
        if ids is None:
            rec["failed"] = "the 3D view could not draw its id pass"
        elif not drawn & mine:
            rec["failed"] = "isolated, it is not drawn"
        elif drawn - mine:
            rec["failed"] = f"isolated, {len(drawn - mine)} other instances are still drawn"

    def _explode_sub(self, rec: dict[str, Any], name: str, mine: set[int], value: Any) -> None:
        pane, view = self.pane, self.view
        on = value == "on"
        if not pane.is_subassembly(name):
            rec["failed"] = "it is not a sub-assembly: the view draws no part under it to explode"
            return
        if not pane.explode_value:
            pane.set_explode(100)  # the switch shows only in an exploded view
        pane.set_subassembly_explodes(name, on)
        view.finish_animation()
        QApplication.processEvents()
        explosion, scene = view.explosion, view.scene
        if explosion is None:
            rec["failed"] = "the view is not exploded"
            return
        where: list[tuple[int, int]] = []
        for m, ids in enumerate(scene.ids):
            where.extend((m, k) for k in range(len(ids)))
        shown = [g for g in sorted(mine) if not pane._hidden(g)]
        groups = {group_of(pane.instance_ids[g], pane.explode_level, pane.explode_choices) for g in shown}
        offsets = {explosion.offset(*where[g]) for g in shown}
        rec.update({"explode": round(view.explode, 4), "groups": len(groups), "offsets": len(offsets)})
        # A sub-assembly around it chosen to stay together keeps it together whatever its own
        # switch says, as it should: the report names it.
        held = held_by(name, pane.explode_choices)
        if held is not None:
            rec["held_by"] = held
        if not on and len(offsets) > 1:
            rec["failed"] = f"switched off, its instances move by {len(offsets)} offsets, not as one"
            return
        if on and held is None and (name in groups or len(offsets) != len(groups)):
            rec["failed"] = f"switched on, its {len(groups)} groups move by {len(offsets)} offsets"
            return
        ids = view.ids_drawn()
        w, h = max(view.width(), 1), max(view.height(), 1)
        inside = total = 0
        from array import array

        for g in shown:
            m, k = where[g]
            b = array("f")
            b.frombytes(scene.bounds[m])
            d = explosion.offset(m, k)
            lo = [b[6 * k + i] + view.explode * d[i] for i in range(3)]
            hi = [b[6 * k + 3 + i] + view.explode * d[i] for i in range(3)]
            xs, ys = [], []
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        nx, ny, _nz = view.camera.project((x, y, z))
                        xs.append((nx + 1) * w / 2)
                        ys.append((1 - ny) * h / 2)
            x0, x1, y0, y1 = min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2
            for j, i in enumerate(ids or ()):
                if i == g:
                    total += 1
                    inside += x0 <= j % w + 0.5 <= x1 and y0 <= j // w + 0.5 <= y1
        rec.update({"pixels": total, "inside": round(inside / max(total, 1), 4)})
        if ids is None:
            rec["failed"] = "the 3D view could not draw its id pass"
        elif not total:
            rec["failed"] = "nothing under it is drawn"
        elif inside < SAME_PASS * total:
            rec["failed"] = "its instances are not drawn where their offsets move them"


# --------------------------------------------------------------------------- the cube, the pivot, the input
MOVE_TIMEOUT_S = 5.0  # a camera move takes half a second at most
SILHOUETTE_PX = 2  # a box part's drawn size against its box seen from there, in device pixels


def deliver(view: QWidget, kind: QEvent.Type, point: tuple[float, float], button=None, mods=None) -> None:
    """Send the 3D view a mouse event as Qt routes a real one: to the child under ``point``
    (the view cube, the legend), mapped to it, which passes on to the view what it does not
    take; else to the view itself."""
    button = button or Qt.MouseButton.LeftButton
    mods = mods or Qt.KeyboardModifier.NoModifier
    x, y = point
    child = view.childAt(QPoint(int(x), int(y)))
    target = child if child is not None else view
    local = target.mapFrom(view, QPointF(x, y)) if child is not None else QPointF(x, y)
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
    event = QMouseEvent(kind, local, view.mapToGlobal(QPointF(x, y)), pressed, held, mods)
    QApplication.sendEvent(target, event)


def _key(view: QWidget, key, mods=None, kind: QEvent.Type = QEvent.Type.KeyPress) -> None:
    QApplication.sendEvent(view, QKeyEvent(kind, key, mods or Qt.KeyboardModifier.NoModifier))


def _wheel(view: QWidget, point: tuple[float, float], across: int, down: int) -> None:
    at = QPointF(*point)
    event = QWheelEvent(
        at,
        view.mapToGlobal(at),
        QPoint(),
        QPoint(across, down),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view, event)


def _turned(degrees: float, want: float) -> bool:
    """Whether an angle is ``want`` degrees, whole turns apart."""
    return abs((degrees - want + 180.0) % 360.0 - 180.0) < 1e-6


def _close(a, b, tol: float = 1e-9) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _unit(v) -> tuple[float, ...]:
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _extent(img) -> tuple[int, int]:
    """The width and height, in device pixels, of what a frame draws: its pixels that differ
    from the corner's colour."""
    w, h, px = _rgb(img)
    bg = px[0]
    xs, ys = [], []
    for k, c in enumerate(px):
        if c != bg:
            xs.append(k % w)
            ys.append(k // w)
    return (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) if xs else (0, 0)


def _centroid(img) -> tuple[float, float] | None:
    w, _h, px = _rgb(img)
    bg = px[0]
    sx = sy = n = 0
    for k, c in enumerate(px):
        if c != bg:
            sx, sy, n = sx + k % w, sy + k // w, n + 1
    return (sx / n, sy / n) if n else None


def _on_edge(img) -> bool:
    """Whether the model is drawn on the frame's edge, so part of it may lie beyond."""
    w, h, px = _rgb(img)
    bg = px[0]
    edge = [*range(w), *range(w * (h - 1), w * h), *range(0, w * h, w), *range(w - 1, w * h, w)]
    return any(px[k] != bg for k in edge)


class NavCheck:
    """``--viewcube``, ``--pivot`` and ``--input-checks`` in the 3D view of ``pane``
    (``view``): each done with events as a person does it, routed as Qt routes them, then
    checked against the camera and the pixels read back. Each starts from Home and the
    view is left at Home; :meth:`run_cube`, :meth:`run_pivot` and :meth:`run_input` give
    the report's records, with ``failed`` saying why when something does not match."""

    def __init__(self, test: "SelfTest", pane, view) -> None:
        self.test, self.pane, self.view = test, pane, view
        self.events: list[tuple[str, int]] = []
        view.picked.connect(self._picked)
        view.menuRequested.connect(self._menu)

    def detach(self) -> None:
        """Stop counting the view's picks and menus."""
        self.view.picked.disconnect(self._picked)
        self.view.menuRequested.disconnect(self._menu)

    def close(self) -> None:
        """Done: the view is left at Home."""
        self.detach()
        self.view.go_home(animate=False)

    def _picked(self, index: int) -> None:
        self.events.append(("picked", index))

    def _menu(self, index: int, _where) -> None:
        self.events.append(("menu", index))

    # -- doing it ------------------------------------------------------------------------
    def settle(self) -> float:
        """Wait while the camera moves (an animation takes half a second at most); seconds."""
        t0 = time.perf_counter()
        view = self.view
        while view.moving and time.perf_counter() - t0 < MOVE_TIMEOUT_S:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        QApplication.processEvents()
        return time.perf_counter() - t0

    def cube_point(self, local: tuple[float, float]) -> tuple[float, float]:
        cube = self.view.cube
        return (cube.x() + local[0], cube.y() + local[1])

    def click(self, point: tuple[float, float]) -> None:
        deliver(self.view, QEvent.Type.MouseButtonPress, point)
        deliver(self.view, QEvent.Type.MouseButtonRelease, point)

    def click_region(self, region) -> bool:
        cube = self.view.cube
        p = viewcube.point_of(cube.axes, region, cube.width())
        if p is None:
            return False
        self.click(self.cube_point(p))
        return True

    def click_control(self, name: str) -> bool:
        cube = self.view.cube
        if name not in cube.shown:
            return False
        x, y, w, h = viewcube.control_rects(cube.width())[name]
        self.click(self.cube_point((x + w / 2, y + h / 2)))
        return True

    def cube_menu(self, text: str) -> str | None:
        """Right-click the cube's front-most region and choose ``text`` from the menu that
        opens, as a person does; why not, when it was not there."""
        view, cube = self.view, self.view.cube
        region = viewcube.region_at(cube.axes, cube.width() / 2, cube.width() / 2, cube.width())
        point = self.cube_point(viewcube.point_of(cube.axes, region, cube.width()))
        offered: list[str] = []
        chosen: list[str] = []
        state = {"running": True, "looks": 0}

        def choose() -> None:
            if not state["running"]:
                return
            popup = QApplication.activePopupWidget()
            if popup is None:
                state["looks"] += 1
                if state["looks"] < 25:
                    QTimer.singleShot(200, choose)
                return
            offered.extend(a.text() for a in popup.actions() if a.text())
            for action in popup.actions():
                if action.text() == text and action.isEnabled():
                    chosen.append(text)
                    action.trigger()
                    break
            popup.close()

        QTimer.singleShot(200, choose)
        deliver(view, QEvent.Type.MouseButtonPress, point, Qt.MouseButton.RightButton)
        deliver(view, QEvent.Type.MouseButtonRelease, point, Qt.MouseButton.RightButton)
        q = QPoint(int(point[0]), int(point[1]))
        target = view.childAt(q) or view
        local = target.mapFrom(view, q) if target is not view else q
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, local, view.mapToGlobal(q))
        QApplication.sendEvent(target, event)
        state["running"] = False
        if chosen:
            return None
        return (
            f"the cube's menu offered no {text!r}: {offered}" if offered else "the cube's menu did not open"
        )

    # -- the checks ------------------------------------------------------------------------
    def frame(self):
        self.view.repaint()
        return self.view.grabFramebuffer()

    def legend_clear(self, img=None) -> bool | None:
        """No model pixel in the column the legend (and the cube over it) takes, when the
        legend is shown and the camera fitted; None when that does not apply."""
        return legend_clear(self.pane, self.view, img)

    def check_region(self, rec: dict[str, Any], region) -> None:
        """The view looks from ``region`` after its click: exactly there, fitted, the frame
        the view draws when set there at once, the model as large as it should be, the
        legend's column empty, and the cube showing that region in its middle."""
        view, cam = self.view, self.view.camera
        yaw, pitch = viewmath.region_angles(region)
        right, up, back = viewmath.turntable_axes(yaw, pitch)
        problems = []
        if view.moving:
            problems.append("still moving")
        if not (_close(cam.back, _unit(region)) and _close(cam.up, up) and _close(cam.right, right)):
            problems.append(f"looks from {[round(v, 6) for v in cam.back]}")
        if not cam.fitted:
            problems.append("not fitted")
        eased = self.frame()
        view.set_camera_state({"yaw": yaw, "pitch": pitch, "fitted": True})
        if eased != self.frame():
            problems.append("its frame is not the one drawn when set there at once")
        silhouette = self.silhouette()
        if silhouette is not None:
            rec["silhouette"] = silhouette
            (gw, gh), (ww, wh) = silhouette["got"], silhouette["want"]
            if abs(gw - ww) > SILHOUETTE_PX or abs(gh - wh) > SILHOUETTE_PX:
                problems.append(f"drawn {gw} x {gh} device pixels, not {ww:.1f} x {wh:.1f}")
        clear = self.legend_clear(eased)
        if clear is not None:
            rec["legend_clear"] = clear
            if not clear:
                problems.append("the model is drawn under the legend")
        cube = view.cube
        size = cube.width()
        if viewcube.region_at(cube.axes, size / 2, size / 2, size) != tuple(region):
            problems.append("the cube does not show it in its middle")
        colour = self.cube_colour(region)
        if colour is not None:
            problems.append(colour)
        if problems:
            rec.setdefault("problems", []).extend(problems)

    def silhouette(self) -> dict[str, Any] | None:
        """For a part whose mesh is a box (12 triangles: o02 is 10 x 20 x 30 mm, every side
        different), its drawn size and its box's size from the camera's direction, in
        device pixels; None for anything else."""
        view, cam = self.view, self.view.camera
        mesh = getattr(view, "mesh", None)
        if mesh is None or mesh.n_triangles != 12:
            return None
        (x0, y0, z0), (x1, y1, z1) = mesh.bbox
        dims = (x1 - x0, y1 - y0, z1 - z0)
        upp = 2 * cam.half_height / (view.height() * view.devicePixelRatioF())
        want = [sum(abs(axis[i]) * dims[i] for i in range(3)) / upp for axis in (cam.right, cam.up)]
        return {"want": [round(v, 2) for v in want], "got": list(_extent(self.frame()))}

    def cube_colour(self, region) -> str | None:
        """The cube's own picture at the region, off its label: opaque, in its face's colour
        or the highlight's; why not, else."""
        cube = self.view.cube
        size = cube.width()
        p = viewcube.point_of(cube.axes, region, size, off_label=True)
        if p is None:
            return "the cube does not draw it"
        img = cube.picture()
        dpr = img.devicePixelRatio()
        got = img.pixelColor(int(p[0] * dpr), int(p[1] * dpr))
        if got.alpha() != 255:
            return f"the cube's picture is not opaque there (alpha {got.alpha()})"
        cell = max(
            (
                c
                for c in viewcube.cells(cube.axes, size, facing=viewcube.HIT_FACING)
                if c.region == tuple(region)
            ),
            key=lambda c: c.area,
        )
        want = [cube.cell_color(cell, lit) for lit in (False, True)]
        if min(_distance(got.getRgb()[:3], w.getRgb()[:3]) for w in want) > 9:
            return f"the cube's picture there is {got.name()}, not {want[0].name()} or {want[1].name()}"
        return None

    # -- --viewcube ----------------------------------------------------------------------
    def run_cube(self, what: str) -> list[dict[str, Any]]:
        if what == "all":
            out = []
            for region in viewmath.REGIONS:
                out.extend(self.run_cube(viewmath.region_name(region)))
            return out
        self.events = []
        before_pick = self.pane.highlight
        rec: dict[str, Any] = {"viewcube": what}
        try:
            region = viewmath.parse_region(what)
            if region is not None:
                self._region(rec, region)
            elif what in STEPS:
                self._step(rec, what)
            elif what in ("roll-cw", "roll-ccw"):
                self._roll(rec, 1 if what == "roll-ccw" else -1)
            else:
                {
                    "home": self._home,
                    "set-home": self._set_home,
                    "reset-home": self._reset_home,
                    "drag": self._drag,
                }[what](rec)
        except Exception as exc:  # recorded, so one bad check does not end the run
            rec.setdefault("problems", []).append(f"{type(exc).__name__}: {exc}")
        if self.events:
            rec.setdefault("problems", []).append(f"the view picked or asked for a menu: {self.events}")
        if self.pane.highlight != before_pick:
            rec.setdefault("problems", []).append("the pick changed")
        if rec.get("problems"):
            rec["failed"] = "; ".join(rec["problems"])
        return [rec]

    def _region(self, rec: dict[str, Any], region) -> None:
        cube = self.view.cube
        path = viewcube.path_to(cube.axes, region, cube.width())
        rec["path"] = [viewmath.region_name(r) for r in path]
        seconds = []
        for step in path:
            if not self.click_region(step):
                rec.setdefault("problems", []).append(f"{viewmath.region_name(step)} is not drawn")
                return
            seconds.append(round(self.settle(), 3))
            self.check_region(rec, step)
        rec["seconds"] = seconds

    def _home_state(self) -> dict[str, Any]:
        return self.view.home or {"yaw": viewmath.ISO_YAW, "pitch": viewmath.ISO_PITCH, "fitted": True}

    def _home(self, rec: dict[str, Any]) -> None:
        view = self.view
        view.camera.turn_model(40, 25)  # somewhere else first
        view.update()
        self.click_control(viewcube.HOME)
        rec["seconds"] = round(self.settle(), 3)
        want = view.camera.copy()
        want.set_state(self._home_state())
        rec["home"] = "set" if view.home else "isometric"
        if not same_camera(view.camera_state(), want.state()):
            rec.setdefault("problems", []).append("Home did not go to the home view")

    def _set_home(self, rec: dict[str, Any]) -> None:
        view = self.view
        self.click_region((1, 1, 0))
        self.settle()
        view.camera.zoom(1.4)
        view.update()
        state = view.camera_state()
        why = self.cube_menu("Set Current View as Home")
        if why:
            rec.setdefault("problems", []).append(why)
            return
        kept = self.pane._homes_by_document.get(self.pane.document_key)
        if not same_camera(view.home, state) or not same_camera(kept, state):
            rec.setdefault("problems", []).append("Home is not the view set")
        self._home(rec)

    def _reset_home(self, rec: dict[str, Any]) -> None:
        why = self.cube_menu("Reset Home to Isometric")
        if why:
            rec.setdefault("problems", []).append(why)
            return
        if self.view.home is not None:
            rec.setdefault("problems", []).append("Home is still set")
        self._home(rec)

    def _face_on(self, rec: dict[str, Any], *, top: bool = False) -> bool:
        """Look at a face square on (Front, or Top) by clicking it, unless it already does."""
        cube = self.view.cube
        if viewcube.square_on(cube.axes) is not None and not top:
            return True
        want = (0, 1, 0) if top else (0, 0, 1)
        for step in viewcube.path_to(cube.axes, want, cube.width()):
            self.click_region(step)
            self.settle()
        rec.setdefault("first", []).append(viewmath.region_name(want))
        return viewcube.square_on(cube.axes) is not None

    def _roll(self, rec: dict[str, Any], sign: int) -> None:
        view, cam = self.view, self.view.camera
        name = "roll-ccw" if sign > 0 else "roll-cw"
        self._face_on(rec)
        if cam.mode != viewmath.FREE and viewcube.face_on(cam.axes)[1] == 0:
            rec["roll_arrows_on_a_side_face"] = name in view.cube.shown  # a turntable cannot roll there
            if rec["roll_arrows_on_a_side_face"]:
                rec.setdefault("problems", []).append("a turntable shows roll arrows on a side face")
            self._face_on(rec, top=True)
        right, back, yaw = cam.right, cam.back, cam.yaw
        if not self.click_control(name):
            rec.setdefault("problems", []).append("the roll arrow is not shown")
            return
        rec["seconds"] = round(self.settle(), 3)
        if cam.mode == viewmath.FREE:
            want_up = right if sign > 0 else tuple(-v for v in right)
            ok = _close(cam.back, back) and _close(cam.up, want_up)
        else:
            ok = _close(cam.back, back) and _turned(cam.yaw - yaw, -90 if sign > 0 else 90)
        rec["up"] = [round(v, 9) for v in cam.up]
        if not ok or not cam.fitted:
            rec.setdefault("problems", []).append(f"{name} did not roll the view 90 degrees that way")

    def _step(self, rec: dict[str, Any], side: str) -> None:
        cam = self.view.camera
        self._face_on(rec)
        right, up, back = cam.axes
        want_back = {
            "step-up": up,
            "step-down": tuple(-v for v in up),
            "step-left": tuple(-v for v in right),
            "step-right": right,
        }[side]
        if not self.click_control(side):
            rec.setdefault("problems", []).append("the step arrow is not shown")
            return
        rec["seconds"] = round(self.settle(), 3)
        rec["back"] = [round(v, 9) for v in cam.back]
        ok = _close(cam.back, want_back) and cam.fitted
        if cam.mode == viewmath.FREE:
            want_up = {"step-up": tuple(-v for v in back), "step-down": back}.get(side, up)
            ok = ok and _close(cam.up, want_up)
        else:
            ok = ok and abs(cam.right[1]) < 1e-9  # upright
        if not ok:
            rec.setdefault("problems", []).append(f"{side} did not bring the next face to the front")

    def _drag(self, rec: dict[str, Any]) -> None:
        view = self.view
        cube = view.cube
        size = cube.width()
        start = view.camera.copy()
        before = self.frame()
        p = self.cube_point((size / 2, size / 2))
        moving = False
        deliver(view, QEvent.Type.MouseButtonPress, p)
        for k in range(1, 11):
            deliver(view, QEvent.Type.MouseMove, (p[0] + 6 * k, p[1] + 3 * k))
            moving = moving or view.moving
        deliver(view, QEvent.Type.MouseButtonRelease, (p[0] + 60, p[1] + 30))
        start.turn_model(24, 12)
        cam = view.camera
        if not (_close(cam.right, start.right) and _close(cam.up, start.up) and _close(cam.back, start.back)):
            rec.setdefault("problems", []).append(
                "the drag did not turn the model as a drag on the view does"
            )
        if moving or view.moving:
            rec.setdefault("problems", []).append("the drag eased")
        if self.frame() == before:
            rec.setdefault("problems", []).append("the frame did not change")

    # -- --pivot -------------------------------------------------------------------------
    def run_pivot(self, name: str) -> dict[str, Any]:
        view, pane = self.view, self.pane
        view.go_home(animate=False)
        QApplication.processEvents()
        rec: dict[str, Any] = {"pivot": name or ".", "setting": "pointer" if view.about_pointer else "centre"}
        if name:
            point = self.model_pixel(name)
            if point is None:
                rec["failed"] = "the 3D view draws no instance of that name clear of its overlays"
                return rec
        else:
            point = self.test._empty_pixel(view)
            if point is None:
                rec["failed"] = "the 3D view has no empty pixel"
                return rec
        rec["pixel"] = [round(point[0], 1), round(point[1], 1)]
        x, y = point
        cam = view.camera
        target_before = cam.project(cam.target)[:2]
        under = view.surface_at(x, y) if name else None  # read as the view reads it, to follow it
        button = Qt.MouseButton.MiddleButton if pane.mouse_style == SOLIDWORKS else Qt.MouseButton.LeftButton
        deliver(view, QEvent.Type.MouseButtonPress, point, button)
        about = None
        for k in range(1, 11):
            deliver(view, QEvent.Type.MouseMove, (x + 5 * k, y + 2.5 * k), button)
            if k == 1:
                about = view.turning_about
                rec["mark"] = view.pivot_mark.isVisible()
        deliver(view, QEvent.Type.MouseButtonRelease, (x + 50, y + 25), button)
        rec["about"] = None if about is None else [round(v, 9) for v in about]
        w, h = view.width(), view.height()
        problems = []
        if not name:
            after = cam.project(cam.target)[:2]
            rec["target"] = [[round(v, 9) for v in target_before], [round(v, 9) for v in after]]
            if about is not None or not (_close(target_before, cam.shift) and _close(after, cam.shift)):
                problems.append("over empty space the model did not turn about the middle of the free area")
            return self._done(rec, problems)
        point3 = about if about is not None else under
        if point3 is None:
            problems.append("nothing was found under the pointer")
            return self._done(rec, problems)
        nx, ny, _ = cam.project(point3)
        px, py = (nx + 1) / 2 * w, (1 - ny) / 2 * h
        rec["kept"] = [round(px - x, 4), round(py - y, 4)]
        kept = abs(px - x) <= 0.5 and abs(py - y) <= 0.5
        if not view.about_pointer:
            rec["moved"] = not kept  # the setting is off: the point moves, which shows it acts
            if kept or about is not None:
                problems.append("with the setting off it still turned about the point under the pointer")
            return self._done(rec, problems)
        if about is None:
            problems.append("no point was read under the pointer")
        elif not kept:
            problems.append("the point turned about left its pixel")
        if not rec.get("mark"):
            problems.append("no mark showed the point")
        index = pane.instance_ids.index(name) if view.can_pick else None
        front = view.instance_at(x, y, 0) if view.can_pick else None
        if view.can_pick:
            rec["front"] = None if front is None else pane.instance_ids[front]
        again = view.surface_at(x, y)
        if again is not None:
            gap = math.dist(again, point3)
            rec["depth_gap"] = round(gap / cam.radius, 6)
            if front != index:
                rec["occluded"] = True  # something turned in front of it: nearer, as it should be
            elif gap > 0.01 * cam.radius:
                problems.append("the surface read there again is not the point turned about")
        return self._done(rec, problems)

    def _done(self, rec: dict[str, Any], problems: list[str]) -> dict[str, Any]:
        if problems:
            rec["failed"] = "; ".join(problems)
        self.view.go_home(animate=False)
        return rec

    def model_pixel(self, name: str) -> tuple[float, float] | None:
        """Where ``name`` (an instance's id; for a part, anything) is drawn, clear of the
        view's overlays."""
        view, pane = self.view, self.pane
        if view.can_pick:
            if name not in pane.instance_ids:
                return None
            return view.pixel_of(pane.instance_ids.index(name), clear=True)
        img = self.frame()
        w, h, px = _rgb(img)
        scale = w / max(view.width(), 1)
        bg = px[0]
        best = None
        for k, c in enumerate(px):
            if c == bg:
                continue
            x, y = (k % w + 0.5) / scale, (k // w + 0.5) / scale
            if view.overlay_at(x, y) is not None:
                continue
            d = (x - view.width() / 2) ** 2 + (y - view.height() / 2) ** 2
            if best is None or d < best[0]:
                best = (d, (int(x) + 0.5, int(y) + 0.5))
        return None if best is None else best[1]

    # -- --input-checks --------------------------------------------------------------------
    def run_input(self) -> dict[str, Any]:
        view, cam = self.view, self.view.camera
        rec: dict[str, Any] = {}
        problems: list[str] = []
        mid = (view.width() / 3, view.height() / 2)
        # A sideways scroll turns as the arrow key does; a quarter notch a quarter as far.
        view.go_home(animate=False)
        _wheel(view, mid, 120, 0)
        swiped, swiped_frame = cam.view_matrix(), self.frame()
        view.go_home(animate=False)
        _key(view, Qt.Key.Key_Right)
        keyed = cam.view_matrix()
        rec["wheel_is_arrow_key"] = swiped == keyed and swiped_frame == self.frame()
        view.go_home(animate=False)
        for _ in range(4):
            _wheel(view, mid, 30, 0)
        rec["wheel_quarters"] = all(
            abs(a - b) < 1e-12 for a, b in zip(cam.view_matrix(), swiped, strict=True)
        )
        view.go_home(animate=False)
        half = cam.half_height
        _wheel(view, mid, 120, 20)
        rec["wheel_mostly_across_turns_only"] = cam.half_height == half and cam.view_matrix() == swiped
        for key in ("wheel_is_arrow_key", "wheel_quarters", "wheel_mostly_across_turns_only"):
            if not rec[key]:
                problems.append(key.replace("_", " ") + ": no")
        # Ctrl and Shift during a SOLIDWORKS middle-drag, zoomed out a step first: the pan is
        # measured by the drawn pixels' centroid, which a model pushed past the frame's edge
        # (a wide part fitted across the view) would hold back.
        style = view.mouse_style
        view.mouse_style = SOLIDWORKS
        view.go_home(animate=False)
        cam.zoom(1 / WHEEL_STEP)
        view.update()
        middle = Qt.MouseButton.MiddleButton
        ctrl, shift = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
        x, y = self.test._empty_pixel(view) or (8.0, view.height() - 8.0)
        x, y = min(max(x, 60.0), view.width() - 60), min(max(y, 60.0), view.height() - 60)
        deliver(view, QEvent.Type.MouseButtonPress, (x, y), middle)
        axes = cam.axes
        deliver(view, QEvent.Type.MouseMove, (x + 20, y), middle)
        turned = cam.axes != axes
        _key(view, Qt.Key.Key_Control, ctrl)
        before = _centroid(self.frame())
        for k in range(1, 5):
            deliver(view, QEvent.Type.MouseMove, (x + 20 + 10 * k, y + 7.5 * k), middle, ctrl)
        after_frame = self.frame()
        after = _centroid(after_frame)
        rec["pan_within_frame"] = not _on_edge(after_frame)
        dpr = view.devicePixelRatioF()
        moved = None
        if before is not None and after is not None:
            moved = [(after[0] - before[0]) / dpr, (after[1] - before[1]) / dpr]
        rec["ctrl_pans"] = moved
        _key(view, Qt.Key.Key_Control, Qt.KeyboardModifier.NoModifier, QEvent.Type.KeyRelease)
        axes = cam.axes
        deliver(view, QEvent.Type.MouseMove, (x + 70, y + 30), middle)
        turned_again = cam.axes != axes
        _key(view, Qt.Key.Key_Shift, shift)
        half = cam.half_height
        deliver(view, QEvent.Type.MouseMove, (x + 70, y + 10), middle, shift)
        zoomed = cam.half_height < half
        deliver(view, QEvent.Type.MouseButtonRelease, (x + 70, y + 10), middle, shift)
        _key(view, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier, QEvent.Type.KeyRelease)
        view.mouse_style = style
        rec.update({"middle_rotates": turned, "ctrl_released_rotates": turned_again, "shift_zooms": zoomed})
        if not (turned and turned_again and zoomed):
            problems.append("Ctrl or Shift during a middle-drag did not switch it")
        if moved is None or abs(moved[0] - 40) > 0.5 or abs(moved[1] - 30) > 0.5:
            problems.append(f"Ctrl during a middle-drag did not pan 40, 30: {moved}")
        # The roll keys.
        view.go_home(animate=False)
        if cam.mode == viewmath.FREE:
            view.set_view("front")
            _key(view, Qt.Key.Key_PageDown)
            a = math.radians(15)
            ok = _close(cam.up, (-math.sin(a), math.cos(a), 0.0))
            _key(view, Qt.Key.Key_PageDown, shift)
            ok = ok and _close(cam.up, (-math.cos(a), -math.sin(a), 0.0)) and _close(cam.back, (0, 0, 1))
            _key(view, Qt.Key.Key_PageUp, shift)
            _key(view, Qt.Key.Key_PageUp)
            ok = ok and _close(cam.up, (0.0, 1.0, 0.0))
        else:
            view.set_view("top")
            yaw = cam.yaw
            _key(view, Qt.Key.Key_PageDown)
            ok = _turned(cam.yaw - yaw, 15) and cam.pitch == viewmath.PITCH_LIMIT
            _key(view, Qt.Key.Key_PageUp)
            ok = ok and _turned(cam.yaw - yaw, 0)
        rec["roll_keys"] = ok
        if not ok:
            problems.append("Page Up and Page Down did not roll the view")
        view.go_home(animate=False)
        if problems:
            rec["failed"] = "; ".join(problems)
        return rec


def legend_clear(pane, view, img=None) -> bool | None:
    """Whether no model pixel lies in the column over the 3D view's right that the legend
    (and the view cube over it) takes, when the legend is shown and the camera fitted;
    None when that does not apply."""
    legend = getattr(pane, "legend", None)
    if legend is None or not legend.isVisibleTo(view) or not view.camera.fitted:
        return None
    img = img if img is not None else view.grabFramebuffer()
    w, h, px = _rgb(img)
    scale = w / max(view.width(), 1)
    left = legend.x()
    if view.cube.isVisibleTo(view):
        left = min(left, view.cube.x())
    x0, y1 = int(left * scale), min(h, int((legend.geometry().bottom() + 1) * scale))
    bg = px[0]
    return not any(px[y * w + x] != bg for y in range(y1) for x in range(x0, w))


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 4),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4),
        "max": round(ordered[-1], 4),
    }


class SelfTest(QObject):
    def __init__(
        self,
        window: MainWindow,
        folder: str,
        *,
        screenshot_dir: str | None,
        select: list[str] | None,
        select_all: bool = False,
        report: str | None = None,
        force: bool = False,
        view_3d: bool = False,
        open_components: dict[str | None, list[str]] | list[str] | None = None,
        configurations: dict[str | None, list[str]] | None = None,
        explodes: dict[str | None, list[tuple[int, str | None]]] | None = None,
        picks: dict[str | None, list[str]] | None = None,
        boxes: bool = False,
        looks: dict[str | None, list[tuple[str, str, Any]]] | None = None,
        print_dry_run: bool = False,
        print_menus: dict[str | None, list[tuple[str, str, str]]] | None = None,
        viewcubes: dict[str | None, list[str]] | None = None,
        pivots: dict[str | None, list[str]] | None = None,
        input_checks: bool = False,
        print_format: str | None = None,
        export_step: bool = False,
        quick_filters: list[tuple[str, ...]] | None = None,
        drawing_dry_run: bool = False,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.view_3d = view_3d
        self.boxes = boxes and not select_all  # check the boxes drawn for instances without a mesh
        # The configurations to draw in 3D besides the first, by the document they belong to.
        self.configurations = {} if select_all else dict(configurations or {})
        self.config_queue: list[str] = []
        # The explode amounts to save, by the assembly they belong to: (percent, level), the
        # level None for the one the Explode bar shows.
        self.explodes = {} if select_all else dict(explodes or {})
        self.explode_queue: list[tuple[int, str | None]] = []
        # The instances to pick in the 3D view, by the assembly they belong to.
        self.picks = {} if select_all else dict(picks or {})
        self.pick_queue: list[str] = []
        # How to show instances in the 3D view, by the assembly they belong to: (action of
        # LOOK_ACTIONS, component tree id, its value), in the order given.
        self.looks = {} if select_all else dict(looks or {})
        self.print_dry_run = print_dry_run and not select_all
        # The 3D Prints to make from a menu, by the document they belong to: ("row", NAME, ""),
        # ("view", NAME, "part" or "sub") or ("view", "", "space"); None: every document's.
        self.print_menus = dict(print_menus or {}) if self.print_dry_run else {}
        self.print_queue: list[tuple[str, str, str]] = []
        self.print_wait: tuple[dict[str, Any], Any] | None = None  # a print waited for
        # The format every print of the run is sent in (None: the program's own), and
        # whether to export each selected part with File > Export STEP.
        self.print_format = print_format if self.print_dry_run else None
        self.export_step = export_step and not select_all
        self.step_wait: tuple[dict[str, Any], Any] | None = None  # an Export STEP waited for
        # Whether to make a drawing of each selected part (--drawing-dry-run), the one waited
        # for, and the pool its stand-ins for the wizard and the editor work in.
        self.drawing_dry_run = drawing_dry_run and not select_all
        self.drawing_wait: dict[str, Any] | None = None
        self.drawings_made = 0  # each drawing's number is the next (ST-001...)
        self.drawing_base: str | None = (
            None  # where its folders are made (None: the system's temporary folder)
        )
        self.drawing_pool = QThreadPool(self)
        self.drawing_pool.setMaxThreadCount(1)
        self.look_queue: list[tuple[str, str, Any]] = []
        # The view cube's regions and buttons to click, the points to turn about, by the
        # document they belong to, and whether to check the wheel, keys and modifiers.
        self.viewcubes = {} if select_all else dict(viewcubes or {})
        self.pivots = {} if select_all else dict(pivots or {})
        self.input_checks = input_checks and not select_all
        self.quick_filters = [] if select_all else list(quick_filters or [])  # each a set of types
        # The rows to open, by the document they belong to; None: every document's.
        plan = open_components or {}
        self.open_components = {} if select_all else dict(plan if isinstance(plan, dict) else {None: plan})
        self.component_queue: list[str] = []
        self.nav: dict[str, Any] | None = None
        self.folder = os.path.abspath(folder)
        self.force = force
        self.shots, self.report_path = outputs(
            self.folder, screenshot_dir, report, select_all=select_all, force=force
        )
        self.select = list(select or [])
        self.select_all = select_all
        self.t0 = time.perf_counter()
        self.report: dict[str, Any] = {
            "solidseas": __version__,
            "platform": QApplication.platformName(),
            "settings": window.store.path,
            "view_3d": view_3d,
            "rotation": window.settings.rotation_mode,
            "view_cube": window.settings.view_cube,
            "pivot_at": "pointer" if window.settings.turn_about_pointer else "centre",
            "print_format": self.print_format,
            "listing": None,
            "documents": [],
            "screenshots": [],
            "errors": [],
        }
        self.queue: list[tuple[str, int | None]] = []
        self.current: dict[str, Any] | None = None
        self.started_doc = 0.0
        self.shot_no = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timed_out)
        self.section_times: dict[str, list[float]] = {}
        self.doc_times: list[float] = []
        self.error_codes: dict[str, int] = {}
        self.read = 0
        self.documents_with_errors = 0
        self.pending_3d: dict[str, Any] | None = None

    # -- flow ------------------------------------------------------------------------
    def start(self) -> None:
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
        self.window.listingFinished.connect(self._listed)
        self.window.detailsFinished.connect(self._details_done)
        self.timer.start(int(LISTING_TIMEOUT_S * 1000))
        self.window.open_folder(self.folder)
        if self.window.folder is None:
            self._fail("open_folder", "the folder could not be opened")
            self._finish()

    def _listed(self, result: dict[str, Any]) -> None:
        self.timer.stop()
        info = {k: v for k, v in result.items() if k != "error"}
        info["error"] = result.get("error")
        info["since_start_s"] = round(time.perf_counter() - self.t0, 3)
        rows = self.window.model.rows
        info["rows"] = len(rows)
        info["thumbnails"] = sum(1 for r in rows if r.thumb is not None)
        self.report["listing"] = info
        if not result.get("ok"):
            self._fail("listing", (result.get("error") or {}).get("code"))
            self._finish()
            return
        self._settle()
        if self.shots:
            self.window.set_view("icons")
            self._shot("listing_icons")
            self.window.set_view("details")
            self._shot("listing_details")
            self._preferences_shot()
        if self.quick_filters:
            self.report["quick_filters"] = [self._quick_filter(keys) for keys in self.quick_filters]
        if self.view_3d:
            from .view3d import gl_status

            ok, why = gl_status()
            self.report["opengl"] = {"available": ok, "detail": why}
        if self.select_all:
            self.queue = [
                (r.entry["path"], i)
                for i, r in enumerate(rows)
                if r.entry["type"] == "file" and r.entry["status"] == "ok"
            ]
        else:
            names = self.select or [self._default()]
            self.queue = [(n, None) for n in names if n]
            if not self.queue:
                self._fail("select", "the folder holds no document")
        self._next()

    def _default(self) -> str | None:
        rows = sorted(self.window.model.rows, key=lambda r: r.entry["path"].casefold())
        ok = [r for r in rows if r.entry["type"] == "file" and r.entry["status"] == "ok"]
        for r in ok:
            if r.doc_type == "assembly":
                return r.entry["path"]
        return ok[0].entry["path"] if ok else None

    def _next(self) -> None:
        if not self.queue:
            self._finish()
            return
        name, _row = self.queue.pop(0)
        self.current = {"name": None if self.select_all else name, "errors": []}
        self.started_doc = time.perf_counter()
        self.timer.start(int(DOC_TIMEOUT_S * 1000))
        if not self.window.select_document(name):
            self.timer.stop()
            self._fail("select", f"no document named {name!r}" if not self.select_all else "not found")
            self.current = None
            QTimer.singleShot(0, self._next)

    def _details_done(self, generation: int) -> None:
        if self.current is None or generation != self.window.generation:
            return
        self.timer.stop()
        doc = self.current
        self.current = None
        elapsed = time.perf_counter() - self.started_doc
        doc["seconds"] = round(elapsed, 4)
        doc["sections"] = {k: round(v, 4) for k, v in self.window.details_seconds.items()}
        for name, section in self.window.details.sections.items():
            if not section.get("ok"):
                code = (section.get("error") or {}).get("code")
                doc["errors"].append({"section": name, "code": code})
        for name, page in self.window.details.pages.items():
            if page.message_text and "could not" in page.message_text:
                doc["errors"].append({"tab": name, "message": page.message_text.splitlines()[0]})
        if self.select_all:
            self.read += 1
            self.documents_with_errors += bool(doc["errors"])
            self.doc_times.append(elapsed)
            for k, v in self.window.details_seconds.items():
                self.section_times.setdefault(k, []).append(v)
            for e in doc["errors"]:
                key = f"{e.get('section') or e.get('tab')}:{e.get('code') or 'message'}"
                self.error_codes[key] = self.error_codes.get(key, 0) + 1
        else:
            if self.shots:
                doc["screenshots"] = self._tab_shots(doc["name"])
            self._preview_shots(doc)
            return
        QTimer.singleShot(0, self._next)

    def _preview_shots(self, doc: dict[str, Any]) -> None:
        """The Preview tab zoomed in, and with ``--3d`` the 3D view of a part, once its
        mesh has been read."""
        pane = self.window.details.preview
        tabs = self.window.details.tabs
        stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
        tabs.setCurrentIndex(TABS.index("Preview"))
        pane.set_mode(IMAGE)
        if self.shots and pane.image.pixmap is not None:
            self._settle()
            pane.image.zoom_by(ZOOM)
            path = self._shot(f"{stem}_preview_zoomed")
            if path:
                doc.setdefault("screenshots", []).append(path)
            pane.image.fit()
        if self.view_3d and pane.enabled_3d:  # an assembly or a drawing shows its image and says why
            self.pending_3d = doc
            self.window.mesh_result = None
            pane.set_mode(MODEL)
            self.timer.start(int(DOC_TIMEOUT_S * 1000))
            self._await_3d()
            return
        self._document_done(doc)

    def _await_3d(self) -> None:
        """Wait while OpenGL starts and the mesh is read (and, after a configuration was
        chosen, the Components tab shows it), then save the 3D view."""
        if self.pending_3d is None:
            return  # timed out
        w = self.window
        state = w.details.preview.mesh_state
        wanted = self.pending_3d.get("_configuration")
        if state in ("starting", "loading") or (
            wanted and (w.busy or w.details.configuration_shown() != wanted)
        ):
            QTimer.singleShot(50, self._await_3d)
            return
        self.timer.stop()
        QTimer.singleShot(300 if state == "ready" else 0, self._model_shot)  # let it draw its first frame

    def _model_shot(self) -> None:
        doc, self.pending_3d = self.pending_3d, None
        if doc is None:
            return
        pane = self.window.details.preview
        result = self.window.mesh_result or {}
        configuration = doc.pop("_configuration", None)
        info: dict[str, Any] = {"state": pane.mesh_state}
        if configuration:
            info["chosen"] = configuration
            info["components_tab"] = self.window.details.configuration_shown()
        if pane.mesh_info:
            info.update({k: v for k, v in pane.mesh_info.items() if k != "seconds"})
        if pane.status.text():
            info["status"] = pane.status.text()
        info["read_s"] = {k: round(v, 4) for k, v in (result.get("seconds") or {}).items()}
        if result.get("wall") is not None:
            info["wall_s"] = round(result["wall"], 4)
        view = pane.view
        if view is not None and pane.mesh_state == "ready":
            self._settle()
            view.repaint()
            renderer = getattr(view, "renderer", None)
            info["upload_s"] = round(getattr(renderer, "upload_seconds", 0.0), 4)
            info["instanced"] = getattr(renderer, "instanced", None)
            frames = []
            view.measure_frames = True
            for _ in range(5):
                view.repaint()
                frames.append(getattr(view, "frame_seconds", 0.0))
            view.measure_frames = False
            info["frame_s"] = round(statistics.median(frames), 5)
            self._overlays(doc, view, info)
        if pane.mesh_state in ("error", "gl_failed"):
            doc["errors"].append({"tab": "Preview 3D", "message": pane.model_message.text().splitlines()[0]})
        if configuration:
            doc.setdefault("mesh_configurations", []).append(info)
            if info.get("components_tab") != configuration or info.get("configuration") != configuration:
                doc["errors"].append({"tab": "Preview 3D", "message": f"{configuration} was not shown"})
        else:
            doc["mesh"] = info
        stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
        label = f"{stem}_preview_3d" + (f"_{_slug(configuration)}" if configuration else "")
        if self.shots:
            path = self._shot(label)
            if path:
                doc.setdefault("screenshots", []).append(path)
        if configuration and view is not None and pane.mesh_state == "ready":
            self._camera_after(doc, view, info)  # then Home, as before the camera was kept
        if self.boxes and pane.doc_type == "assembly":
            info["boxes"] = self._check_boxes(doc, label, first=not configuration)
        if not configuration and view is not None and pane.mesh_state == "ready":
            self._turn_over(doc, view)
            self._navigation(doc, view)
        if self._next_configuration(doc):
            return
        self._after_model(doc)

    def _turn_over(self, doc: dict[str, Any], view: QWidget) -> None:
        """Turn the model over the top with a drag of the rotate button, save the view and
        check it: past straight above and upside down when rotation is free, stopped at
        straight above for a turntable, and the model drawn either way. Then back to the
        isometric view."""
        pane = self.window.details.preview
        mode = pane.rotation_mode
        button = Qt.MouseButton.MiddleButton if pane.mouse_style == SOLIDWORKS else Qt.MouseButton.LeftButton
        view.reset_view()  # type: ignore[attr-defined]
        self._settle()
        pixels = TURN_OVER_DEGREES / DEGREES_PER_PIXEL
        x, y = view.width() / 2, max(view.height() / 2 - pixels / 2, 1.0)
        drag(view, button, (x, y), (x, y + pixels))
        camera = view.camera  # type: ignore[attr-defined]
        self._settle()
        info: dict[str, Any] = {
            "rotation": mode,
            "degrees": TURN_OVER_DEGREES,
            "up_y": round(camera.up[1], 4),
            "pitch": round(camera.pitch, 4),
            "covered": round(covered(view), 4),
        }
        info["past_top"] = camera.up[1] < 0  # the model's top now points down the screen
        if mode == FREE:
            ok = info["past_top"]
        else:
            ok = abs(camera.pitch - PITCH_LIMIT) < 1e-9 and not info["past_top"]
        if not ok or not info["covered"]:
            why = "the model is not drawn" if not info["covered"] else f"{mode} rotation turned it wrong"
            doc["errors"].append({"tab": "Preview 3D", "message": f"turned over the top, {why}"})
        doc["turned_over"] = info
        if self.shots:
            stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
            view.repaint()
            path = self._shot(f"{stem}_turned_over")
            if path:
                doc.setdefault("screenshots", []).append(path)
        view.reset_view()  # type: ignore[attr-defined]
        self._settle()

    # -- the view cube, the pivot, the input, and the camera across configurations ------
    def _overlays(self, doc: dict[str, Any], view, info: dict[str, Any]) -> None:
        """Each 3D shot reports the areas a fit may use, whether the legend's column is clear
        of the model (when the legend is shown and the camera fitted: the run fails
        otherwise), and the cube: shown, its size, and the region it shows in its middle."""
        if not hasattr(view, "cube"):
            return
        pane = self.window.details.preview
        info["free_area"] = [[round(v, 4) for v in a] for a in view.camera.free]
        clear = legend_clear(pane, view)
        if clear is not None:
            info["legend_clear"] = clear
            if not clear:
                doc["errors"].append({"tab": "Preview 3D", "message": "the model is drawn under the legend"})
        cube = view.cube
        size = cube.width()
        facing = viewcube.region_at(cube.axes, size / 2, size / 2, size)
        info["cube"] = {
            "shown": cube.isVisibleTo(view),
            "size": size,
            "facing": None if facing is None else viewmath.region_name(facing),
        }

    def _navigation(self, doc: dict[str, Any], view) -> None:
        """``--viewcube``, ``--pivot`` and ``--input-checks`` on the first 3D view of ``doc``,
        right after the turn over the top: from Home, and back to Home after (:class:`NavCheck`)."""
        name = doc["name"]
        cubes = [*self.viewcubes.get(name, []), *self.viewcubes.get(None, [])]
        pivots = [*self.pivots.get(name, []), *self.pivots.get(None, [])]
        if not (cubes or pivots or self.input_checks) or not hasattr(view, "cube"):
            return
        pane = self.window.details.preview
        stem = _slug(os.path.splitext(os.path.basename(name or ""))[0])
        check = NavCheck(self, pane, view)
        view.go_home(animate=False)
        self._settle()
        try:
            for what in cubes:
                for rec in check.run_cube(what):
                    doc.setdefault("viewcube", []).append(rec)
                    if rec.get("failed"):
                        doc["errors"].append({"viewcube": rec["viewcube"], "message": rec["failed"]})
                if self.shots and what != "all":
                    view.repaint()
                    path = self._shot(f"{stem}_viewcube_{_slug(what)}")
                    if path:
                        doc.setdefault("screenshots", []).append(path)
            for what in pivots:
                rec = check.run_pivot("" if what == "." else what)
                doc.setdefault("pivot", []).append(rec)
                if rec.get("failed"):
                    doc["errors"].append({"pivot": rec["pivot"], "message": rec["failed"]})
            if self.input_checks:
                rec = check.run_input()
                doc["input_checks"] = rec
                if rec.get("failed"):
                    doc["errors"].append({"input": "checks", "message": rec["failed"]})
        finally:
            check.close()
            self._settle()

    def _camera_before_configuration(self, view, fitted: bool) -> dict[str, Any]:
        """Before another configuration is chosen: the view turned by a drag of the rotate
        button and zoomed two notches a third of the way across, as someone looking at it
        would; or, ``fitted``, a fitted corner view reached by a click on the cube's back,
        top and left corner. The camera then, which the next configuration must keep."""
        pane = self.window.details.preview
        check = NavCheck(self, pane, view)
        try:
            if fitted:
                for step in viewcube.path_to(view.cube.axes, (-1, 1, -1), view.cube.width()):
                    check.click_region(step)
                    check.settle()
            else:
                button = (
                    Qt.MouseButton.MiddleButton
                    if pane.mouse_style == SOLIDWORKS
                    else Qt.MouseButton.LeftButton
                )
                x, y = self._empty_pixel(view) or (view.width() / 2, view.height() / 2)
                x, y = min(max(x, 40.0), view.width() - 40), min(max(y, 40.0), view.height() - 40)
                drag(view, button, (x, y), (x + 30, y + 20))
                for _ in range(2):
                    _wheel(view, (view.width() / 3, view.height() / 2), 0, 120)
                self._settle()
        finally:
            check.detach()
        return view.camera_state()

    def _camera_after(self, doc: dict[str, Any], view, info: dict[str, Any]) -> None:
        """After another configuration is drawn: the camera as it was (``kept``), or, where
        the camera as it was had lost the new model (none of its box in the free area as it
        was, or zoomed out too far for it: :meth:`.viewmath.OrbitCamera.lost`), fitted from
        the same direction (``refit``, with the new box); the model drawn either way. A
        refit where the camera had not lost it fails. The view then goes Home, so what
        follows (the boxes, an explode, the picks) starts from where it always did."""
        before = doc.pop("_camera_before", None)
        if before is None:
            return
        fitted, state, free = before
        after = view.camera_state()
        was = view.camera.copy()  # the camera as it was, over the new model
        was.set_state(state)
        was.free = free
        same_way = all(abs(x - y) < 1e-9 for x, y in zip(was.back, view.camera.back, strict=True))
        if fitted:
            info["camera"] = "kept, fitted" if after["fitted"] and same_way else "changed"
        elif same_camera(after, state):
            info["camera"] = "kept"
        elif after["fitted"] and same_way:
            info["camera"] = "refit" if was.lost() else "refit with the model in view"
            info["camera_box"] = [[round(v, 6) for v in corner] for corner in view.camera.bbox]
        else:
            info["camera"] = "changed"
        info["covered"] = round(covered(view), 4)
        why = {
            "changed": "the camera changed",
            "refit with the model in view": "the camera was fitted again though it still showed the model",
        }.get(info["camera"]) or ("" if info["covered"] else "the model is not drawn")
        if why:
            doc["errors"].append({"configuration": info.get("chosen"), "message": why})
        view.go_home(animate=False)
        self._settle()

    def _after_model(self, doc: dict[str, Any]) -> None:
        """The 3D view is saved: explode it, pick in it and change how its instances look
        as asked, then go on."""
        if self._next_explode(doc) or self._next_pick(doc) or self._next_look(doc):
            return
        self.window.details.preview.set_mode(IMAGE)
        self.window.details.tabs.setCurrentIndex(0)
        self._document_done(doc)

    def _next_explode(self, doc: dict[str, Any]) -> bool:
        """Explode ``doc`` to its next ``--explode`` as the Explode bar does; False when
        none is left."""
        if "explode_done" not in doc:
            doc["explode_done"] = True
            self.explode_queue = list(self.explodes.get(doc["name"], []))
        if not self.explode_queue:
            return False
        pane = self.window.details.preview
        if not pane.can_explode:
            for percent, _level in self.explode_queue:
                doc["errors"].append({"explode": percent, "message": "the 3D view shows no assembly"})
            self.explode_queue = []
            return False
        percent, asked = self.explode_queue.pop(0)
        pane.set_explode(percent, asked)  # no level: the one the bar shows, as the slider alone
        level = pane.explode_level
        deadline = time.perf_counter() + EXPLODE_TIMEOUT_S
        QTimer.singleShot(30, lambda: self._await_explode(doc, percent, level, deadline))
        return True

    def _await_explode(self, doc: dict[str, Any], percent: int, level: str, deadline: float) -> None:
        pane = self.window.details.preview
        view = pane.view
        if view is not None and getattr(view, "animating", False) and time.perf_counter() < deadline:
            QTimer.singleShot(30, lambda: self._await_explode(doc, percent, level, deadline))
            return
        info: dict[str, Any] = {"percent": percent, "level": level, "groups": pane.explode_groups.get(level)}
        drawn = getattr(view, "explode", None)
        info["drawn"] = None if drawn is None else round(drawn, 4)
        explosion = getattr(view, "explosion", None)
        if explosion is not None and drawn is not None:
            info["moving"] = explosion.moving
            info["bbox"] = [[round(v, 6) for v in corner] for corner in explosion.bbox_at(drawn)]
        if drawn is None or abs(drawn - percent / 100) > 1e-6 or getattr(view, "animating", False):
            doc["errors"].append({"explode": percent, "message": f"the view ended at {drawn}"})
        if self.boxes:
            info["boxes"] = self._box_counts(doc, f"explode {percent} {level}")
        doc.setdefault("explode", []).append(info)
        if self.shots:
            stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
            label = f"{stem}_explode_{percent}" + ("" if level == TOP else f"_{_slug(level)}")
            self._settle()
            if view is not None:
                view.repaint()
            path = self._shot(label)
            if path:
                doc.setdefault("screenshots", []).append(path)
        self._after_model(doc)

    # -- the boxes drawn for instances without a mesh ---------------------------------
    def _box_counts(self, doc: dict[str, Any], where: str) -> dict[str, Any]:
        """Check that every instance the read gives a box for is drawn as one where it
        belongs, now; an error on ``doc`` for those that are not."""
        pane = self.window.details.preview
        view = pane.view
        geometry = (self.window.mesh_result or {}).get("geometry") or {}
        ph = geometry.get("placeholders") or {}
        expected = list(ph.get("ids") or [])
        drawn = pane.instance_ids[pane.box_from :]
        self._settle()
        report = view.box_report() if hasattr(view, "box_report") else None  # type: ignore[union-attr]
        if report is not None:
            report["first"] = len(pane.instance_ids) - report["boxes"]
        failed = box_failures(expected, drawn, report)
        rec: dict[str, Any] = {
            "with_box": ph.get("count", 0),
            "drawn": len(drawn),
            "visible": (report or {}).get("visible"),
            "not_drawn": len(failed),
        }
        if report is not None and report.get("subpixel"):
            rec["subpixel"] = len(report["subpixel"])
        if failed:
            doc["errors"].append(
                {
                    "boxes": where,
                    "message": f"{len(failed)} instances with a box are not drawn as one, "
                    f"first {', '.join(failed[:5])}",
                }
            )
        return rec

    def _check_boxes(self, doc: dict[str, Any], label: str, *, first: bool) -> dict[str, Any]:
        """``--boxes`` in the 3D view just saved: every box drawn where it belongs. For the
        document's first view, save it with every box picked and with the boxes turned off
        (none may be drawn then), and turn them back on."""
        w = self.window
        pane = w.details.preview
        rec = self._box_counts(doc, label)
        if not first or not rec["drawn"]:
            return rec
        if self.shots:
            pane.highlight_boxes()
            pane.view.repaint()  # type: ignore[union-attr]
            path = self._shot(f"{label}_boxes")
            if path:
                doc.setdefault("screenshots", []).append(path)
        w.change_settings(draw_boxes=False)
        self._settle()
        off = view_boxes = len(pane.instance_ids) - pane.box_from
        report = pane.view.box_report() if hasattr(pane.view, "box_report") else None  # type: ignore[union-attr]
        if report is not None:
            view_boxes = report["boxes"]
        rec["drawn_when_off"] = max(off, view_boxes)
        if rec["drawn_when_off"]:
            doc["errors"].append({"boxes": label, "message": "boxes are drawn with the setting off"})
        if self.shots:
            if pane.view is not None and pane.mesh_state == "ready":
                pane.view.repaint()
            path = self._shot(f"{label}_boxes_off")
            if path:
                doc.setdefault("screenshots", []).append(path)
        w.change_settings(draw_boxes=True)
        self._settle()
        pane.set_pick(None)
        again = self._box_counts(doc, f"{label} on again")
        rec["drawn_on_again"] = again["drawn"]
        return rec

    def _next_configuration(self, doc: dict[str, Any]) -> bool:
        """Choose the next ``--configuration`` of ``doc`` in the 3D view's own list, and
        wait for it; False when none is left."""
        if "configurations_done" not in doc:
            doc["configurations_done"] = True
            self.config_queue = list(self.configurations.get(doc["name"], []))
        pane = self.window.details.preview
        if not self.config_queue or pane.mesh_state not in ("ready", "no_mesh", "too_large", "error"):
            return False
        name, fitted = self.config_queue.pop(0)
        known = [pane.config_combo.itemText(i) for i in range(pane.config_combo.count())]
        if name not in known:
            doc["errors"].append({"configuration": name, "message": "no configuration of that name"})
            return self._next_configuration(doc)
        if pane.mesh_state == "ready" and hasattr(pane.view, "cube"):
            state = self._camera_before_configuration(pane.view, fitted)
            doc["_camera_before"] = (fitted, state, pane.view.camera.free)
        doc["_configuration"] = name
        self.pending_3d = doc
        self.window.mesh_result = None
        self.timer.start(int(DOC_TIMEOUT_S * 1000))
        pane.config_combo.setCurrentText(name)
        pane.choose_configuration(name)  # as choosing it in the list does
        QTimer.singleShot(50, self._await_3d)
        return True

    def _document_done(self, doc: dict[str, Any]) -> None:
        if self.print_dry_run and "print" not in doc:
            self._print(doc)
            return
        if self.print_dry_run and "print_menus" not in doc:
            doc["print_menus"] = []
            self.print_queue = [*self.print_menus.get(doc["name"], []), *self.print_menus.get(None, [])]
            if self.print_queue:
                QTimer.singleShot(0, lambda: self._next_print_menu(doc))
                return
        if self.export_step and "export_step" not in doc:
            self._export_step(doc)
            return
        if self.drawing_dry_run and "drawing" not in doc:
            self._drawing(doc)
            return
        names = [*self.open_components.get(doc["name"], []), *self.open_components.get(None, [])]
        if names and "components_opened" not in doc:
            doc["components_opened"] = []
            self.component_queue = names
            QTimer.singleShot(0, lambda: self._open_component(doc))
            return
        self.report["documents"].append(doc)
        QTimer.singleShot(0, self._next)

    # -- 3D Print, as a dry run ------------------------------------------------------------
    def _dry_run(self):
        """The window's print controller in its dry run: it exports and never starts a
        program; should it try, the run fails and nothing starts. It writes no file next
        to a model outside the folder under test (``confine``): such a print goes to the
        temporary folder, which says why."""
        printer = self.window.printer
        printer.dry_run = True
        printer.confine = self.folder
        printer.launch = lambda program, path: self._fail("print", "the dry run tried to start a program")
        if self.print_format:
            # As Settings > 3D Print Program chooses it. With no program found the window
            # would ask, so no print is made in any format: that fails the run, which would
            # otherwise pass having checked nothing.
            choice, program = printer.current()
            label = printing.FORMAT_LABELS[self.print_format]
            if program is None:
                self._fail_once("print_format", f"no 3D print program found to send {label} to")
            elif self.print_format not in program.formats:
                self._fail_once("print_format", f"{program.name} does not take {label}")
            elif printing.format_for(program, choice) != self.print_format:
                printer.set_format(self.print_format)
        return printer

    def _print_timeout(self) -> float:
        """How long a print may take, in seconds: a STEP's may run to the STEP export's
        limit and then be made as 3MF (:func:`.printing.export_for_print`)."""
        choice, program = self.window.printer.current()
        if program is not None and printing.format_for(program, choice) == printing.STEP:
            return STEP_TIMEOUT_S + DOC_TIMEOUT_S
        return DOC_TIMEOUT_S

    def _await_print(self, doc: dict[str, Any], press, then) -> None:
        """Call ``press``, which starts a print (False: it could not), and hand ``then``
        the print's outcome once it ends."""
        printer = self.window.printer

        def finished(outcome: dict[str, Any]) -> None:
            printer.finished.disconnect(finished)
            self.timer.stop()
            self.print_wait = None
            then(outcome)

        self.print_wait = (doc, finished)
        printer.finished.connect(finished)
        self.timer.start(int(self._print_timeout() * 1000))
        why = press()
        if isinstance(why, str) and self.print_wait is not None and self.print_wait[1] is finished:
            finished({"ok": False, "not_started": why})

    def _check_print(
        self,
        doc: dict[str, Any],
        via: str,
        outcome: dict[str, Any],
        folder: str | None,
        first: dict[str, Any] | None = None,
        document: str | None = None,
    ) -> dict[str, Any]:
        """Check a dry run's print, made ``via`` the button or a menu: the file is next to
        the model, in ``folder`` (never outside the folder under test), or in the
        temporary folder with the reason said; it is named after the document (a nested
        one after ``document``, the name the window shows), with the configuration
        exported when it is not the active one, and today's date, its full path is in the
        note, and so is the configuration exported when it is not the one asked for; with
        ``first``, the check of the same print made just before, its number is one
        higher. A failed check fails the run."""
        printer = self.window.printer
        rec: dict[str, Any] = {"via": via, "ok": bool(outcome.get("ok"))}
        kept = (
            "file",
            "place",
            "fallback",
            "note",
            "configuration",
            "requested_configuration",
            "doc_type",
            "format",
            "requested_format",
            "format_fallback",
        )
        for key in kept:
            if key in outcome:
                rec[key] = outcome[key]
        problems: list[str] = []
        if outcome.get("would_ask"):
            rec["would_ask"] = True
            if self.print_format:  # nothing was written, so the format went unchecked
                rec["problems"] = ["no 3D print program found: the window would ask, and no file was made"]
                doc["errors"].append({"print": via, "problems": rec["problems"]})
            return rec
        if not outcome.get("ok"):
            problems.append(
                outcome.get("cannot")
                or outcome.get("not_started")
                or outcome.get("problem")
                or (outcome.get("error") or {}).get("code")
                or "the print failed"
            )
        else:
            file = outcome["file"]
            where, name = os.path.split(file)
            if outcome.get("place") == printing.MODEL:
                if folder is None or os.path.normcase(where) != os.path.normcase(folder):
                    problems.append(f"written in {where}, not next to the model in {folder}")
                if not printing.inside(where, self.folder):
                    problems.append(f"written in {where}, outside the folder under test")
            else:
                temp = printing.export_folder_path(printer.out_base)
                if os.path.normcase(where) != os.path.normcase(temp):
                    problems.append(f"written in {where}, neither next to the model nor in {temp}")
                if outcome.get("next_to_model") and not outcome.get("fallback"):
                    problems.append("written in the temporary folder without a reason")
            stem, date = outcome.get("stem") or "", outcome.get("date") or ""
            ext = os.path.splitext(name)[1]
            m = re.fullmatch(re.escape(stem) + r"(?: \(([0-9]+)\))?" + re.escape(ext), name)
            named = outcome.get("named_configuration")
            made = outcome.get("document") or ""
            own = os.path.basename(outcome.get("source") or "")
            # a nested document's name, else the file's name without its extension, whatever
            # its format (box.stl prints as box ...), as the export names it
            if outcome.get("nested") and document:
                expected = printing.document_name(document)
            else:
                expected = os.path.splitext(own)[0]
            mark = outcome.get("format_mark")
            if mark and mark != printing.format_mark(own):
                problems.append(f"{name} is marked {mark}, not with its document's extension")
            label = printing.print_label(
                made, named, assembly=bool(outcome.get("assembly_mark")), source=mark
            )
            if (
                m is None
                or date != printer.today()
                or made.casefold() != expected.casefold()
                or named not in (None, outcome.get("configuration"))
                or stem != printing.print_stem(label, date)
            ):
                problems.append(f"{name} is not named after the document {expected} and today's date")
            else:
                rec["number"] = int(m.group(1) or 1)
            if file not in (outcome.get("note") or ""):
                problems.append("the note does not give the file's full path")
            problems += self._check_format(rec, outcome, ext)
            asked, exported = outcome.get("requested_configuration"), outcome.get("configuration")
            if (
                asked
                and exported
                and asked != exported
                and f"in configuration {exported}" not in (outcome.get("note") or "")
            ):
                problems.append(f"the note does not say {exported} was exported, not {asked}")
            if first is not None and first.get("number") is not None:
                if rec.get("number") != first["number"] + 1:
                    problems.append(f"the second print the same day is not numbered ({first['number'] + 1})")
                if os.path.dirname(first.get("file") or "") != where:
                    problems.append("the second print went to another folder")
        if problems:
            rec["problems"] = problems
            doc["errors"].append({"print": via, "problems": problems})
        return rec

    def _check_format(self, rec: dict[str, Any], outcome: dict[str, Any], ext: str) -> list[str]:
        """What is wrong with the format of a print that was made: its extension is the
        format's; it is the format asked for (``--print-format``), or 3MF with the reason
        said in the note for a STEP that could not be made, which a 3D file of a format
        the STEP export does not write never can be (:func:`.printing.step_unavailable`);
        a STEP, an assembly's included, passes the checker
        (``rec["step_check"]``)."""
        problems: list[str] = []
        fmt, asked = outcome.get("format"), outcome.get("requested_format")
        want = self.print_format
        labels = printing.FORMAT_LABELS
        if ext.lower() != printing.EXTENSIONS.get(fmt or ""):
            problems.append(f"{os.path.basename(outcome['file'])} does not end in {fmt}'s extension")
        if want and asked != want:
            problems.append(f"asked for as {labels.get(asked or '', asked)}, not {labels[want]}")
        why = outcome.get("format_fallback")
        if fmt != asked:
            if asked != printing.STEP or fmt != printing.STEP_FALLBACK or not why:
                problems.append(f"sent as {fmt}, not {asked}, without a reason")
            elif why not in (outcome.get("note") or ""):
                problems.append("the note does not say why the STEP went as 3MF")
        # a 3D file of a format the STEP export does not write goes as 3MF, for its format: what
        # the file holds, which the export read (a STEP saved as .SLDPRT, a Parasolid file as .step)
        content = outcome.get("source_format") or "solidworks"
        model_format = None if outcome.get("nested") or content == "solidworks" else content
        unavailable = printing.step_unavailable(model_format, outcome.get("doc_type"))
        if asked == printing.STEP and unavailable and why != unavailable:
            problems.append(f"a {model_format} file asked for as STEP did not go as 3MF for its format")
        if fmt == printing.STEP:
            check = check_step_file(outcome["file"], outcome.get("step"))
            rec["step_check"] = check
            problems += [f"STEP check: {p}" for p in check["problems"]]
        return problems

    def _print(self, doc: dict[str, Any]) -> None:
        """Press 3D Print with the controller in its dry run, wait for the export, record
        what it would start, save the button, the program menu and Preferences, then press
        it again; check both prints (:meth:`_check_print`)."""
        printer = self._dry_run()
        doc["print"] = None
        target = self.window.print_target()
        if target is None:
            doc["print"] = {"ok": False, "printable": False}
            QTimer.singleShot(0, lambda: self._document_done(doc))
            return
        folder = printing.model_folder(target.source.path)
        checks: list[dict[str, Any]] = doc.setdefault("print_checks", [])
        stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])

        def second(outcome: dict[str, Any]) -> None:
            doc["print_again"] = outcome
            checks.append(self._check_print(doc, "button again", outcome, folder, checks[0], target.name))
            QTimer.singleShot(0, lambda: self._document_done(doc))

        def first(outcome: dict[str, Any]) -> None:
            doc["print"] = outcome
            checks.append(self._check_print(doc, "button", outcome, folder, document=target.name))
            self._settle()
            path = self._shot(f"{stem}_print_button", self.window.toolbar)
            if path:
                doc.setdefault("screenshots", []).append(path)
            menu = printer.menu
            printer.fill_menu()
            menu.popup(self.window.mapToGlobal(QPoint(self.window.width() // 3, 80)))
            path = self._shot(f"{stem}_print_program_menu", menu)
            menu.hide()
            if path:
                doc.setdefault("screenshots", []).append(path)
            self._preferences_shot(f"{stem}_print_preferences")
            if outcome.get("ok"):
                QTimer.singleShot(0, lambda: self._await_print(doc, printer.print_selection, second))
            else:
                QTimer.singleShot(0, lambda: self._document_done(doc))

        self._await_print(doc, printer.print_selection, first)
        if printer.busy:  # the export's process is starting: the button is Cancel 3D Print meanwhile
            doc["print_busy_button"] = printer.action.text().replace("&", "")
            path = self._shot(f"{stem}_print_busy", self.window.toolbar)
            if path:
                doc.setdefault("screenshots", []).append(path)

    # -- File > Export STEP, into a temporary folder ------------------------------------
    def _export_step(self, doc: dict[str, Any]) -> None:
        """Export the part shown with File > Export STEP as the menu does, its save dialog
        answered with a folder of the run's own in the system's temporary folder and its
        questions with no; check the file with the checker, report it and remove the
        folder. The entry must be off for a drawing, and off with its tooltip saying why
        for what the STEP export does not write (:meth:`.window.MainWindow.step_unavailable`:
        a 3D file of a format other than SOLIDWORKS and Parasolid), whose
        reason the report gives; a part it is off for without a reason fails, and so does
        one it is on for with a reason."""
        w = self.window
        step = w.step
        w._update_actions()
        doc_type = (w.details.summary or {}).get("doc_type")
        why = w.step_unavailable()
        doc["export_step"] = None
        if not w.act_step.isEnabled():
            rec: dict[str, Any] = {"available": False, "doc_type": doc_type}
            if why:
                rec["reason"] = why
                rec["tooltip"] = w.act_step.toolTip()
                if why[1:] not in rec["tooltip"]:
                    doc["errors"].append({"export_step": "Export STEP is off, its tooltip not saying why"})
            elif doc_type == "part":
                doc["errors"].append({"export_step": "File > Export STEP is off for a part, with no reason"})
            doc["export_step"] = rec
            QTimer.singleShot(0, lambda: self._document_done(doc))
            return
        if why:
            doc["errors"].append({"export_step": f"File > Export STEP is on, though {why}"})
        if doc_type not in ("part", "assembly"):
            doc["errors"].append({"export_step": f"File > Export STEP is on for a {doc_type}"})
        folder = tempfile.mkdtemp(prefix="solidseas-selftest-step-")
        asked: list[str] = []
        questions: list[str] = []
        said: list[str] = []
        saved = (step.ask_path, step.confirm, step.message)
        step.ask_path = lambda suggested: (
            asked.append(suggested) or os.path.join(folder, os.path.basename(suggested))
        )
        step.confirm = lambda text: questions.append(text) or False  # never a file without bodies
        step.message = lambda icon, text: said.append(text)

        def finished(outcome: dict[str, Any]) -> None:
            if self.step_wait is None or self.step_wait[1] is not finished:
                return
            self.step_wait = None
            self.timer.stop()
            step.finished.disconnect(finished)
            step.ask_path, step.confirm, step.message = saved
            rec = self._check_export_step(doc, outcome, folder, asked, questions, said)
            doc["export_step"] = rec
            if not rec.get("problems") and not outcome.get("timeout"):
                shutil.rmtree(folder, ignore_errors=True)  # the run's own folder, its one STEP file
            else:
                rec["kept_in"] = folder  # for a look at what failed
            QTimer.singleShot(0, lambda: self._document_done(doc))

        self.step_wait = (doc, finished)
        step.finished.connect(finished)
        self.timer.start(int(STEP_TIMEOUT_S * 1000))
        w.act_step.trigger()
        if not step.busy and self.step_wait is not None and self.step_wait[1] is finished and not asked:
            finished({"ok": False, "not_started": True})

    def _check_export_step(
        self,
        doc: dict[str, Any],
        outcome: dict[str, Any],
        folder: str,
        asked: list[str],
        questions: list[str],
        said: list[str],
    ) -> dict[str, Any]:
        """Check what Export STEP did: a file of the name it suggested, in ``folder``, that
        passes the checker, with its result said; or, for an assembly with instances the
        export cannot write, the question whether to write it without them, answered no."""
        rec: dict[str, Any] = {"available": True, "ok": bool(outcome.get("ok"))}
        problems: list[str] = []
        if questions:
            rec["questions"] = [q.split("\n", 1)[0] for q in questions]
        if said:
            rec["message"] = said[-1]
        err = outcome.get("error") or {}
        left_out = (err.get("detail") or {}).get("rule") == "instances_left_out"
        if outcome.get("declined") and left_out and questions:
            rec["declined"] = "instances_left_out"  # asked, and answered no: nothing written, as it should be
        elif not outcome.get("ok"):
            problems.append(
                "timed out"
                if outcome.get("timeout")
                else "it did not start"
                if outcome.get("not_started")
                else err.get("code") or "the export failed"
            )
        else:
            file = outcome["file"]
            rec.update(
                {k: outcome.get(k) for k in ("bytes", "solids", "sheets", "faces", "exact", "partial")}
            )
            rec.update({k: outcome.get(k) for k in ("max_deviation_mm", "uncertainty_mm", "seconds")})
            rec["file"] = os.path.basename(file)
            if os.path.normcase(os.path.dirname(file)) != os.path.normcase(folder):
                problems.append(f"written to {file}, not into the folder the dialog gave")
            if not asked or os.path.basename(asked[0]) != os.path.basename(file):
                problems.append("not written under the name the save dialog suggested")
            if not file.lower().endswith(".step"):
                problems.append(f"{os.path.basename(file)} does not end in .step")
            if outcome.get("partial"):
                problems.append("bodies were left out")
            if not said or not said[-1].startswith(f"Wrote {file}"):
                problems.append("the result does not say where the file was written")
            if sorted(os.listdir(folder)) != [os.path.basename(file)]:
                problems.append("the folder holds more than the STEP file")
            check = check_step_file(file, outcome)
            rec["step_check"] = check
            problems += [f"STEP check: {p}" for p in check["problems"]]
        if problems:
            rec["problems"] = problems
            doc["errors"].append({"export_step": problems})
        return rec

    # -- File > New Drawing, as a dry run ------------------------------------------------
    def _drawing(self, doc: dict[str, Any]) -> None:
        """Make a drawing of the part shown with File > New Drawing, as the menu does, with
        the drawing controller in its dry run, the run's own Drawing Settings and its
        stand-ins for the wizard and the editor; check what they did once the editor is
        done (:meth:`_drawing_done`). For what cannot be drawn the entry must be off with
        its tooltip saying why."""
        w = self.window
        drawings = w.drawings
        w._update_actions()
        action = drawings.new_action
        target = w.print_target()
        why = drawings.shown_refusal()
        doc["drawing"] = None
        entry = {"enabled": action.isEnabled(), "tooltip": action.statusTip()}
        if target is None or why is not None or not action.isEnabled():
            rec: dict[str, Any] = {"drawable": False, "entry": entry}
            problems = []
            if why is not None:
                rec["reason"] = why[1]
                if action.isEnabled():
                    problems.append(f"File > New Drawing is on, though {why[0]}")
                elif why[1] not in action.statusTip():
                    problems.append("File > New Drawing is off, its tooltip not saying why")
            elif target is not None:
                problems.append("File > New Drawing is off for a SOLIDWORKS part")
            elif action.isEnabled():
                problems.append("File > New Drawing is on with no part shown")
            if problems:
                rec["problems"] = problems
                doc["errors"].append({"drawing": problems})
            doc["drawing"] = rec
            QTimer.singleShot(0, lambda: self._document_done(doc))
            return
        from solidseas.drawing.settings import save_settings

        folder = tempfile.mkdtemp(prefix="solidseas-selftest-drawing-", dir=self.drawing_base)
        out = os.path.join(folder, "drawings")
        os.mkdir(out)
        settings_path = save_settings(dry_run_settings(out), os.path.join(folder, "Drawing.json"))
        part_folder = os.path.dirname(os.path.abspath(target.source.path))
        self.drawings_made += 1
        run: dict[str, Any] = {
            "doc": doc,
            "number": f"{DRY_NUMBER}-{self.drawings_made:03d}",
            "folder": folder,
            "out": out,
            "target": target,
            "settings_path": settings_path,
            "beside": _drawing_files(part_folder),
            "part_folder": part_folder,
            "rec": {"drawable": True, "entry": entry, "ok": False},
            "wizards": [],
            "editors": [],
            "jobs": [],
            "saved": (drawings.dry_run, drawings.settings_path, drawings.make_wizard, drawings.make_editor),
        }
        drawings.dry_run = True
        drawings.settings_path = settings_path
        drawings.make_wizard = lambda *a, **k: self._dry_wizard(run, *a, **k)
        drawings.make_editor = lambda *a, **k: self._dry_editor(run, *a, **k)
        drawings.said.clear()
        drawings.last = None
        self.drawing_wait = run
        self.timer.start(int(DRAWING_TIMEOUT_S * 1000))
        action.trigger()  # File > New Drawing, as the menu does
        if not run["wizards"] and self.drawing_wait is run:  # the controller opened no wizard
            outcome = drawings.last or {}
            why_not = outcome.get("cannot") or outcome.get("note") or "File > New Drawing opened no wizard"
            self._drawing_done(run, {"ok": False, "problems": [why_not]})

    def _dry_wizard(self, run: dict[str, Any], *args: Any, **kw: Any) -> DryRunWizard:
        wizard = DryRunWizard(lambda wz: self._run_dry(run, wz, self._wizard_done), *args, **kw)
        run["wizards"].append(wizard)
        return wizard

    def _dry_editor(self, run: dict[str, Any], *args: Any, **kw: Any) -> DryRunEditor:
        editor = DryRunEditor(lambda ed: self._run_dry(run, ed, self._editor_done), *args, **kw)
        run["editors"].append(editor)
        return editor

    def _run_dry(self, run: dict[str, Any], stand_in: Any, then: Any) -> None:
        """Run the wizard's or the editor's work in the run's own thread, never the UI
        thread, and hand ``then`` its record."""
        if isinstance(stand_in, DryRunWizard):

            def work(_emit, _cancelled):
                return dry_wizard_run(
                    stand_in.worker,
                    stand_in.part,
                    stand_in.configuration,
                    stand_in.settings,
                    stand_in.folder,
                    run["number"],
                )
        else:

            def work(_emit, _cancelled):
                return dry_editor_run(stand_in.worker, stand_in.path, stand_in.settings)

        job = Job(work)
        run["jobs"].append(job)  # kept until it has finished, then let go of on the UI thread

        def finished(result: dict[str, Any]) -> None:
            QTimer.singleShot(0, lambda: run["jobs"].remove(job))
            then(run, stand_in, result)

        job.signals.finished.connect(finished)
        self.drawing_pool.start(job)

    def _wizard_done(self, run: dict[str, Any], wizard: DryRunWizard, result: dict[str, Any]) -> None:
        if self.drawing_wait is not run:  # timed out meanwhile
            return
        run["rec"]["wizard"] = result
        if not result.get("ok"):
            self._drawing_done(run, None)
            return
        wizard.visible = False  # Finish closes the wizard
        wizard.drawing_written.emit(result["path"], True)  # Open in the Editor: the controller opens it
        if not run["editors"] and self.drawing_wait is run:
            self._drawing_done(run, {"ok": False, "problems": ["the controller opened no editor"]})

    def _editor_done(self, run: dict[str, Any], _editor: DryRunEditor, result: dict[str, Any]) -> None:
        if self.drawing_wait is run:
            self._drawing_done(run, result)

    def _drawing_done(self, run: dict[str, Any], editor: dict[str, Any] | None) -> None:
        """Check what the dry run's wizard and editor did (:meth:`_check_drawing`), report
        it, and remove the run's folder, or keep it when a check failed."""
        if self.drawing_wait is not run:
            return
        self.drawing_wait = None
        self.timer.stop()
        drawings = self.window.drawings
        drawings.dry_run, drawings.settings_path, drawings.make_wizard, drawings.make_editor = run["saved"]
        doc, rec = run["doc"], run["rec"]
        if editor is not None:
            rec["editor"] = editor
        problems = self._check_drawing(run, rec.get("wizard") or {}, editor or {})
        rec["said"] = list(drawings.said)
        rec["ok"] = not problems
        if problems:
            rec["problems"] = problems
            rec["kept_in"] = run["folder"]  # for a look at what failed
            doc["errors"].append({"drawing": problems})
        else:
            shutil.rmtree(run["folder"], ignore_errors=True)  # the run's own folder and its files
        doc["drawing"] = rec
        QTimer.singleShot(0, lambda: self._document_done(doc))

    def _check_drawing(
        self, run: dict[str, Any], wizard: dict[str, Any], editor: dict[str, Any]
    ) -> list[str]:
        """What is wrong with what the dry run did (see the module notes); empty when
        nothing is."""
        from solidseas.drawing import document

        from . import mail

        problems: list[str] = []
        for part in (wizard, editor):
            problems += list(part.get("problems") or [])
            err = part.get("error")
            if err:
                problems.append(f"{err.get('code')}: {err.get('message')}")
        if not wizard.get("ok") or not editor.get("ok"):
            return problems or ["the dry run did not finish"]
        target = run["target"]
        drawings = self.window.drawings
        (wiz,) = run["wizards"]
        if len(run["editors"]) != 1:
            problems.append(f"the controller opened {len(run['editors'])} editors, not one")
        ed = run["editors"][0]
        made_with = {
            "part": (wiz.part, target.source.path),
            "configuration": (wiz.configuration, target.configuration),
            "folder": (wiz.folder, target.folder),
            "settings": (wiz.settings_path, run["settings_path"]),
            "window": (wiz.parent(), self.window),
            "drawing process": (wiz.worker, drawings.worker),
            "editor's drawing": (ed.path, wizard.get("path")),
            "editor's drawing process": (ed.worker, drawings.worker),
            "editor's settings": (ed.settings_path, run["settings_path"]),
            "editor's window": (ed.parent, None),
        }
        for what, (got, want) in made_with.items():
            if got is not want and got != want:
                problems.append(f"the controller gave the wrong {what}")
        path = wizard["path"]
        out = run["out"]
        try:
            loaded = document.read(path)
        except Exception as exc:  # the drawing file itself does not read back
            return [*problems, f"the drawing file does not read back: {exc}"]
        d = loaded.drawing
        number = editor.get("number") or ""
        if d.status != "PRELIMINARY" or [r.rev for r in d.revisions] != ["A", "B"]:
            problems.append(
                f"the drawing file is {d.status} at {document.current_revision(d)}, not B PRELIMINARY"
            )
        expected = {
            f"{number} A PRELIMINARY.pdf",
            f"{number} A PRELIMINARY.dxf",
            f"{number} A.pdf",
            f"{number} A.dxf",
            f"{number} B PRELIMINARY.pdf",
        }
        names = {o.name for o in d.outputs}
        if names != expected:
            problems.append(f"the drawing records {sorted(names)}, not {sorted(expected)}")
        present = set(os.listdir(out))
        if present != names | {os.path.basename(path)}:
            problems.append(f"the folder holds {sorted(present)}")
        checks: dict[str, Any] = {}
        for o in d.outputs:
            file = os.path.join(out, o.name)
            if document.file_sha256(file) != o.sha256:
                problems.append(f"{o.name} does not have the hash the drawing records")
            if o.released == ("PRELIMINARY" in o.name):
                problems.append(f"{o.name} is named as {'PRELIMINARY' if o.released else 'released'} wrongly")
            check = (check_pdf_file if o.kind == "pdf" else check_dxf_file)(file, stamped=not o.released)
            checks[o.name] = check
            problems += [f"{o.name}: {p}" for p in check["problems"]]
        run["rec"]["checks"] = checks
        saves = [s for s in editor.get("steps", []) if s["step"] == "save" and s.get("files")]
        if not saves or not all(f["replaced"] for s in saves for f in s["files"]):
            problems.append("Save did not keep the PRELIMINARY PDF and DXF current by replacing them")
        if _drawing_files(run["part_folder"]) != run["beside"]:
            problems.append("a drawing file was written beside the part")
        email = editor.get("email") or {}
        pdf = f"{number} B PRELIMINARY.pdf"
        if email.get("question") != mail.PRELIMINARY_QUESTION or email.get("pdf") != pdf:
            problems.append("Email PDF did not ask about the PRELIMINARY drawing and send its stamped PDF")
        delivered = email.get("delivered")
        if delivered == mail.WEBMAIL:
            url = email.get("url") or ""
            if not url.startswith("https://") or email.get("opened") != [url] or email.get("shown") != [pdf]:
                problems.append("Email PDF's webmail route did not show the PDF and open one https page")
            if run["folder"] in url or number not in url:
                problems.append("the webmail address carries more than the drawing number and title")
        elif delivered == mail.ATTACH:
            if email.get("attached") != [pdf]:
                problems.append("Email PDF's attach route did not attach the PDF")
        elif delivered == mail.SHOW:
            if email.get("shown") != [pdf]:
                problems.append("Email PDF did not show the PDF")
        else:
            problems.append(f"Email PDF took no route ({delivered})")
        if self.shots and d.sheet is not None:
            self._sheet_shot(run, d.sheet)
        return problems

    def _sheet_shot(self, run: dict[str, Any], sheet: Any) -> None:
        """Save the drawing's sheet as the editor shows it (:mod:`.drawingscene`)."""
        from .drawingscene import SheetScene

        stem = _slug(os.path.splitext(os.path.basename(run["doc"]["name"] or ""))[0])
        self.shot_no += 1
        name = f"{self.shot_no:02d}_{stem}_drawing_sheet.png"
        try:
            path = _cli.check_output_file(
                os.path.join(self.shots or "", name),
                [],
                allow_source_dir=False,
                force=self.force,
                source_dirs=[self.folder],
            )
        except _cli.Refused as exc:
            self._fail("screenshot", str(_refused("screenshot", name, exc)))
            return
        import shiboken6

        scene = SheetScene(sheet, editable=False)
        try:
            data = scene.render_png(1600)
        except Exception as exc:  # the sheet would not draw: said, the files are checked apart
            run["rec"]["sheet_png"] = f"not drawn: {exc}"
            return
        finally:
            # Deleted here, on the UI thread: its items refer to it, and a scene left to the
            # garbage collector could be deleted from whichever thread collects.
            shiboken6.delete(scene)
        _cli._write(path, data)
        self.report["screenshots"].append(path)
        run["rec"]["sheet_png"] = path

    def _expected(self, key: str, parent: str = "") -> tuple[str | None, str]:
        """The folder a print of the referenced file ``key`` goes next to, and the name the
        window shows for it: the file's folder, found as Go to file finds it, or for a
        virtual component the document's that stores it (the assembly, or the
        sub-assembly ``parent`` for one that sub-assembly stores); None when it is not
        found or several files fit."""
        w = self.window
        t = w.details.target(key)
        got = w.print_source(key, parent, ask=False)  # several files that fit: none expected
        if isinstance(got, tuple):
            return printing.model_folder(got[0].path), t.name
        return None, t.name

    def _print_entry(self, kind: str, name: str, which: str) -> tuple[Any, str, str | None, Any, str | None]:
        """For one ``--print-row`` or ``--print-view``: the menu the right-click opens (or
        None, with why), the start of its 3D Print entry's text, the folder the print
        must go next to, the 3D view's point to right-click (None: choose in the menu)
        and the name the window shows for what it prints."""
        w = self.window
        details, pane = w.details, w.details.preview
        if kind == "row":
            item = next(
                (
                    details.find_item(t, name)
                    for t in ("instances", "files", "bom")
                    if details.find_item(t, name)
                ),
                None,
            )
            if item is None:
                return None, "no row of that name on the Components or BOM tab", None, None, None
            folder, shown = self._expected(item.data(0, KEY_ROLE), item.data(0, PARENT_ROLE) or "")
            return details.component_menu(item), "3D Print ", folder, None, shown
        view = pane.view
        drawn = (
            self.view_3d and pane.mode == MODEL and pane.mesh_state == "ready" and hasattr(view, "pixel_of")
        )
        if which == "space":
            target = w.print_target()
            folder = printing.model_folder(target.source.path) if target is not None else None
            point = self._empty_pixel(view) if drawn else None
            return pane.space_menu(), "3D Print This ", folder, point, target.name if target else None
        parts = name.split("/")
        probes = [name] if which == "part" else ["/".join(parts[:k]) for k in range(len(parts) - 1, 0, -1)]
        link = next((details.instance_link(p) for p in probes if details.instance_link(p) is not None), None)
        folder, shown = self._expected(link[0], link[1]) if link is not None else (None, None)
        own = pane.instance_documents.get(name) if which == "part" else None
        if link is None and own is not None:  # read from a sub-assembly's own file: no row
            folder, shown = printing.model_folder(own["path"]), own["name"]
        prefix = "3D Print Part " if which == "part" else "3D Print Sub-assembly "
        point = None
        if drawn and name in pane.instance_ids:
            point = view.pixel_of(pane.instance_ids.index(name), clear=True)  # type: ignore[union-attr]
        menu = details.instance_menu(name)
        if menu is None:
            return None, "the 3D view has no menu for that instance", None, None, None
        return menu, prefix, folder, point, shown

    @staticmethod
    def _empty_pixel(view) -> tuple[float, float] | None:
        """A point of the 3D view where it draws nothing, near a corner; None if none is."""
        w, h = view.width(), view.height()
        for x, y in ((4, 4), (w - 5, 4), (4, h - 5), (w - 5, h - 5)):
            if view.instance_at(x, y, 0) is None and (
                not hasattr(view, "overlay_at") or view.overlay_at(x, y) is None
            ):
                return (float(x), float(y))
        return None

    def _right_click_choose(
        self, view, point: tuple[float, float], prefix: str, shot: list[str] | None = None
    ) -> str | None:
        """Right-click the 3D view at ``point`` as a person does (press and release without
        moving, then the context menu event) and choose the first entry of the menu that
        opens whose text starts with ``prefix``; why not, when no such entry opened. With
        ``shot`` (a label), the menu is saved first, and its path put in ``shot``. The
        menu is looked for while the right-click's own menu runs, for up to five seconds,
        and never after: a look left over from one right-click once closed the next one's
        menu. When no menu was seen at all (on a desktop in use, another window taking
        the focus closes a menu as it opens), the view is right-clicked once more."""
        chosen: list[str] = []
        opened: list[str] = []  # the entries of the menu that opened, to say what it offered
        for _attempt in range(2):
            state = {"running": True, "looks": 0}

            def choose(state=state) -> None:
                if not state["running"]:
                    return  # this right-click is over: a later menu is not its to choose in
                popup = QApplication.activePopupWidget()
                if popup is None:
                    state["looks"] += 1
                    if state["looks"] < 25:
                        QTimer.singleShot(200, choose)
                    return
                if shot:
                    path = self._shot(shot.pop(), popup)
                    if path:
                        shot.append(path)
                opened.extend(a.text() for a in popup.actions() if a.text())
                for action in popup.actions():
                    if action.text().startswith(prefix) and action.isEnabled():
                        chosen.append(action.text())
                        action.trigger()
                        break
                popup.close()

            QTimer.singleShot(200, choose)
            _mouse(view, QEvent.Type.MouseButtonPress, point, Qt.MouseButton.RightButton)
            _mouse(view, QEvent.Type.MouseButtonRelease, point, Qt.MouseButton.RightButton)
            q = QPoint(int(point[0]), int(point[1]))
            QApplication.sendEvent(
                view, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, q, view.mapToGlobal(q))
            )
            state["running"] = False
            if chosen or opened:
                break
            self._settle()
        if chosen:
            return None
        if opened:
            return f"the right-click opened a menu with no entry starting {prefix.strip()!r}: {opened}"
        return f"the right-click, twice, opened no menu with an entry starting {prefix.strip()!r}"

    def _next_print_menu(self, doc: dict[str, Any]) -> None:
        """Make ``doc``'s next ``--print-row`` or ``--print-view`` print, twice, through
        its menu, and check both; then go on."""
        w = self.window
        pane = w.details.preview
        if not self.print_queue:
            if pane.mode == MODEL:
                pane.set_mode(IMAGE)
            w.details.tabs.setCurrentIndex(0)
            QTimer.singleShot(0, lambda: self._document_done(doc))
            return
        kind, name, which = self.print_queue.pop(0)
        label = f"{kind} {name or '.'}" + (f",{which}" if kind == "view" and which != "space" else "")
        self._dry_run()
        if kind == "view" and self.view_3d and pane.enabled_3d:
            w.details.tabs.setCurrentIndex(TABS.index("Preview"))
            pane.set_mode(MODEL)  # the scene read before: shown again, not read again
            self._settle()
        records: list[dict[str, Any]] = doc["print_menus"]
        menu, prefix, folder, point, shown = self._print_entry(kind, name, which)
        action = None
        if menu is not None:
            action = next((a for a in menu.actions() if a.text().startswith(prefix) and a.isEnabled()), None)
        if action is None:
            why = prefix if menu is None else f"its menu has no entry starting {prefix.strip()!r}"
            records.append({"via": label, "ok": False, "problems": [why]})
            doc["errors"].append({"print": label, "problems": [why]})
            if menu is not None:
                menu.deleteLater()
            QTimer.singleShot(0, lambda: self._next_print_menu(doc))
            return
        view = pane.view
        stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
        shots = [f"{stem}_print_menu_{_slug(label)}"]  # the menu, saved the first time it opens

        def saved() -> None:
            if shots and shots[-1].endswith(".png"):
                doc.setdefault("screenshots", []).append(shots.pop())
            shots.clear()

        if point is not None:
            label += " (right-click)"

            def press():
                why = self._right_click_choose(view, point, prefix, shots)
                saved()
                return why

        else:

            def press():
                if shots:
                    menu.popup(self.window.mapToGlobal(QPoint(self.window.width() // 3, 120)))
                    path = self._shot(shots.pop(), menu)
                    menu.hide()
                    shots.append(path or "")
                    saved()
                action.trigger()
                return None

        def second(outcome: dict[str, Any], first_rec: dict[str, Any]) -> None:
            records.append(self._check_print(doc, label + " again", outcome, folder, first_rec, shown))
            menu.deleteLater()
            QTimer.singleShot(0, lambda: self._next_print_menu(doc))

        def first(outcome: dict[str, Any]) -> None:
            rec = self._check_print(doc, label, outcome, folder, document=shown)
            records.append(rec)
            if outcome.get("ok"):
                QTimer.singleShot(0, lambda: self._await_print(doc, press, lambda o: second(o, rec)))
            else:
                menu.deleteLater()
                QTimer.singleShot(0, lambda: self._next_print_menu(doc))

        self._await_print(doc, press, first)

    # -- picking in the 3D view ---------------------------------------------------------
    def _next_pick(self, doc: dict[str, Any]) -> bool:
        """Click ``doc``'s next ``--pick`` in the 3D view, check what it picked, then
        double-click it; False when none is left."""
        if "pick_done" not in doc:
            doc["pick_done"] = True
            self.pick_queue = list(self.picks.get(doc["name"], []))
        if not self.pick_queue:
            return False
        name = self.pick_queue.pop(0)
        rec: dict[str, Any] = {"name": name}
        doc.setdefault("picked", []).append(rec)
        w = self.window
        details, pane = w.details, w.details.preview
        details.tabs.setCurrentIndex(TABS.index("Preview"))
        self._settle()
        view = pane.view
        index = pane.instance_ids.index(name) if name in pane.instance_ids else None
        point = None
        if index is not None and pane.can_explode and hasattr(view, "pixel_of"):
            point = view.pixel_of(index, clear=True)  # type: ignore[union-attr]
        if point is None:
            why = "the 3D view draws no instance of that name" if index is None else "it is hidden from view"
            doc["errors"].append({"pick": name, "message": why})
            QTimer.singleShot(0, lambda: self._after_model(doc))
            return True
        rec["pixel"] = [round(point[0], 1), round(point[1], 1)]
        click(view, point)  # type: ignore[arg-type]
        self._settle()
        current = details.instances.currentItem()
        rec["components_tab"] = details.selection().get("instances") if current is not None else None
        rec["picked"] = [pane.instance_ids[g] for g in sorted(view.selected)]  # type: ignore[union-attr]
        # An instance read from a sub-assembly's own file has a row once the 3D view's read
        # gives it one; past the rows the tab shows it has none, the click leaves no row
        # current, and the nearest sub-assembly's row stands for it.
        rec["row"] = details.row_of(name)
        own_row = rec["row"] == name
        if rec["picked"] != [name] or (rec["components_tab"] != name if own_row else rec["components_tab"]):
            doc["errors"].append({"pick": name, "message": "the click did not pick that instance alone"})
        elif rec["row"] is None:
            doc["errors"].append({"pick": name, "message": "no row of the Components tab stands for it"})
        slug, stem = _slug(name), _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
        for label, tab in ((f"pick_{slug}", "Preview"), (f"pick_{slug}_components", "Components")):
            details.tabs.setCurrentIndex(TABS.index(tab))
            path = self._shot(f"{stem}_{label}")
            if path:
                doc.setdefault("screenshots", []).append(path)
        details.tabs.setCurrentIndex(TABS.index("Preview"))
        self._settle()
        # Turn the view a step and zoom in toward the instance, as someone looking closer
        # would, so Back has a camera of the user's own to put back.
        before = view.camera_state()  # type: ignore[union-attr]
        turned = _turn_and_zoom(view, point)  # type: ignore[arg-type]
        if turned is None:
            doc["errors"].append({"pick": name, "message": "turned and zoomed in, it is hidden from view"})
            QTimer.singleShot(0, lambda: self._after_model(doc))
            return True
        point = turned
        self.nav = {
            "doc": doc,
            "rec": rec,
            "stage": "open",
            "generation": w.generation,
            "title": details.title.text(),
            "selection": details.selection(),
            "calling": True,
            "tab": TABS.index("Preview"),
            "labels": (f"pick_{slug}_open", f"pick_{slug}_back"),
            "picked": rec["picked"],
            "camera": view.camera_state(),  # type: ignore[union-attr]
            "camera_before": before,
            "next": lambda: self._after_model(doc),
        }
        self.timer.start(int(DOC_TIMEOUT_S * 1000))
        QTimer.singleShot(50, self._catch_dialog)
        double_click(view, point)  # type: ignore[arg-type]
        if self.nav is not None:
            self.nav["calling"] = False
            QTimer.singleShot(0, self._nav_poll)
        return True

    # -- how the instances look --------------------------------------------------------------
    def _next_look(self, doc: dict[str, Any]) -> bool:
        """Do ``doc``'s next ``--transparent``, ``--hide``, ``--isolate`` or
        ``--explode-sub`` in the 3D view, check what is drawn and save the window; after
        the last, Reset appearance and check that the first picture comes back. False
        when none is left."""
        pane = self.window.details.preview
        view = pane.view
        if "looks_done" not in doc:
            doc["looks_done"] = True
            self.look_queue = list(self.looks.get(doc["name"], []))
            if not self.look_queue:
                return False
            if not pane.can_explode or not hasattr(view, "ids_drawn"):
                for action, name, _value in self.look_queue:
                    doc["errors"].append({action: name, "message": "the 3D view shows no assembly"})
                self.look_queue = []
                return False
            self.window.details.tabs.setCurrentIndex(TABS.index("Preview"))
            # Nothing picked, so the screenshots show the looks rather than a pick's fading.
            self.window.details.select_instance("")
            pane.set_pick(None)
            self._settle()
            self.look_start = {
                "image": view.grabFramebuffer(),  # type: ignore[union-attr]
                "camera": view.camera_state(),  # type: ignore[union-attr]
                "explode": pane.explode_value,
            }
        if not self.look_queue:
            self._look_reset(doc)
            return False
        action, name, value = self.look_queue.pop(0)
        check = LookCheck(pane, view)
        rec = check.run(action, name, value)
        doc.setdefault("looks", []).append(rec)
        if rec.get("failed"):
            doc["errors"].append({action: name, "message": rec["failed"]})
        if self.shots:
            stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
            label = f"{stem}_{_slug(action)}_{_slug(name)}"
            if value is not None:
                label += f"_{_slug(str(value))}"
            view.repaint()  # type: ignore[union-attr]
            path = self._shot(label)
            if path:
                doc.setdefault("screenshots", []).append(path)
        QTimer.singleShot(0, lambda: self._after_model(doc))
        return True

    def _look_reset(self, doc: dict[str, Any]) -> None:
        """Reset appearance after the looks: with the explode and the camera put back, the
        view must draw what it drew before the first of them."""
        pane = self.window.details.preview
        view = pane.view
        start = self.look_start
        tabs = self.window.details.tabs
        if self.shots:  # the Components tab marking what is hidden or transparent
            stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
            tabs.setCurrentIndex(TABS.index("Components"))
            path = self._shot(f"{stem}_looks_components")
            if path:
                doc.setdefault("screenshots", []).append(path)
            tabs.setCurrentIndex(TABS.index("Preview"))
            self._settle()
        pane.reset_appearance()
        if pane.explode_value != start["explode"]:
            pane.set_explode(start["explode"])
        if hasattr(view, "finish_animation"):
            view.finish_animation()  # type: ignore[union-attr]
        view.set_camera_state(start["camera"])  # type: ignore[union-attr]
        self._settle()
        after = view.grabFramebuffer()  # type: ignore[union-attr]
        a, b = _rgb(start["image"]), _rgb(after)
        if a[:2] != b[:2]:
            doc["looks_reset"] = {"pixels": a[0] * a[1], "resized": [list(a[:2]), list(b[:2])]}
            doc["errors"].append({"looks": "reset", "message": "the 3D view changed size"})
        else:
            differ = sum(1 for x, y in zip(a[2], b[2], strict=True) if x != y)
            doc["looks_reset"] = {"pixels": a[0] * a[1], "differ": differ}
            if differ:
                why = f"Reset appearance left {differ} pixels changed"
                doc["errors"].append({"looks": "reset", "message": why})
        if self.shots:
            stem = _slug(os.path.splitext(os.path.basename(doc["name"] or ""))[0])
            path = self._shot(f"{stem}_looks_reset")
            if path:
                doc.setdefault("screenshots", []).append(path)

    # -- opening a component's file, and Back ----------------------------------------
    def _open_component(self, doc: dict[str, Any]) -> None:
        """Open the next ``--open-component`` row of ``doc`` as a double-click does."""
        if not self.component_queue:
            self._document_done(doc)
            return
        name = self.component_queue.pop(0)
        rec: dict[str, Any] = {"name": name}
        doc["components_opened"].append(rec)
        details = self.window.details
        details.tabs.setCurrentIndex(TABS.index("Components"))
        item = None
        for tree in ("instances", "files", "sheets", "models"):
            item = details.find_item(tree, name)
            if item is not None:
                details.linked_trees[tree].setCurrentItem(item)
                break
        if item is None:
            doc["errors"].append({"component": name, "message": "no row of that name on the Components tab"})
            QTimer.singleShot(0, lambda: self._open_component(doc))
            return
        self._settle()
        self.nav = {
            "doc": doc,
            "rec": rec,
            "stage": "open",
            "generation": self.window.generation,
            "title": details.title.text(),
            "selection": details.selection(),
            "calling": True,
            "tab": TABS.index("Components"),
            "labels": (f"open_{_slug(name)}", f"back_from_{_slug(name)}"),
            "next": lambda: self._open_component(doc),
        }
        self.timer.start(int(DOC_TIMEOUT_S * 1000))
        QTimer.singleShot(50, self._catch_dialog)
        details.request(item, OPEN)  # as a double-click does
        if self.nav is not None:
            self.nav["calling"] = False
            QTimer.singleShot(0, self._nav_poll)

    def _catch_dialog(self) -> None:
        """While the window is asking (which file, or why it cannot be opened), save the
        dialog and close it."""
        nav = self.nav
        if nav is None or not nav["calling"]:
            return
        widget = QApplication.activeModalWidget()
        if widget is None:
            QTimer.singleShot(50, self._catch_dialog)
            return
        rec = nav["rec"]
        rec["dialog"] = widget.windowTitle()
        path = self._shot(f"{self._stem(nav)}_{nav['labels'][0]}_dialog", widget)
        if path:
            nav["doc"].setdefault("screenshots", []).append(path)
        if isinstance(widget, QDialog):
            widget.reject()
        else:
            widget.close()

    @staticmethod
    def _stem(nav: dict[str, Any]) -> str:
        return _slug(os.path.splitext(os.path.basename(nav["doc"]["name"] or ""))[0])

    def _nav_poll(self) -> None:
        """Wait while the file opened (or the document Back returned to) is read, then
        save it and go on."""
        nav = self.nav
        if nav is None:
            return  # timed out
        w = self.window
        pane = w.details.preview
        view = pane.view
        if (
            w.busy
            or (pane.mode == "3d" and pane.mesh_state in ("starting", "loading"))
            or getattr(view, "animating", False)
        ):
            QTimer.singleShot(50, self._nav_poll)
            return
        rec, doc = nav["rec"], nav["doc"]
        opened, back = nav["labels"]
        if nav["stage"] == "open":
            if w.generation == nav["generation"]:  # nothing opened: a dialog said why, or nothing happened
                rec["outcome"] = "dialog" if "dialog" in rec else "none"
                if rec["outcome"] == "none":
                    doc["errors"].append({"component": rec["name"], "message": "nothing was opened"})
                self._camera_before(nav, view)
                self._next_component()
                return
            rec["outcome"] = "apart" if w.apart is not None else "listed"
            rec["shown"] = w.details.title.text()
            on_preview = w.details.tabs.currentIndex() == TABS.index("Preview")
            if "picked" in nav and pane.mode == "3d" and on_preview:
                info = pane.mesh_info
                rec["opened_3d"] = {
                    "state": pane.mesh_state,
                    "stored_in": info.get("stored_in"),
                    "triangles": info.get("triangles"),
                }
            self._settle()
            if view is not None:
                view.repaint()
            path = self._shot(f"{self._stem(nav)}_{opened}")
            if path:
                doc.setdefault("screenshots", []).append(path)
            nav["stage"] = "back"
            if not w.go_back():
                doc["errors"].append({"component": rec["name"], "message": "Back did nothing"})
                self._next_component()
                return
            QTimer.singleShot(0, self._nav_poll)
            return
        rec["back"] = (
            w.details.title.text() == nav["title"]
            and w.details.selection() == nav["selection"]
            and w.details.tabs.currentIndex() == nav["tab"]
        )
        if "picked" in nav:  # and the 3D view picks the same instance, exploded and turned as it was
            selected = getattr(view, "selected", set())
            rec["picked_after_back"] = [pane.instance_ids[g] for g in sorted(selected)]
            rec["explode_after_back"] = pane.explode_value
            camera = view.camera_state() if hasattr(view, "camera_state") else None  # type: ignore[union-attr]
            rec["camera_after_back"] = same_camera(nav["camera"], camera)
            same_pick = rec["picked_after_back"] == nav["picked"]
            rec["back"] = rec["back"] and same_pick and rec["camera_after_back"]
        if not rec["back"]:
            doc["errors"].append({"component": rec["name"], "message": "Back did not restore the document"})
        self._settle()
        if view is not None:
            view.repaint()
        path = self._shot(f"{self._stem(nav)}_{back}")
        if path:
            doc.setdefault("screenshots", []).append(path)
        self._camera_before(nav, view)
        self._next_component()

    @staticmethod
    def _camera_before(nav: dict[str, Any], view: QWidget | None) -> None:
        """A pick is done: turn the camera back as it was before the pick turned and zoomed
        it, so the next pick starts where this one did and finds its instance in view."""
        if "camera_before" in nav and view is not None and hasattr(view, "set_camera_state"):
            view.set_camera_state(nav["camera_before"])

    def _next_component(self) -> None:
        """This row or pick is done: on to the next."""
        self.timer.stop()
        nav, self.nav = self.nav, None
        if nav is not None:
            QTimer.singleShot(0, nav["next"])

    def _timed_out(self) -> None:
        if self.current is None and self.report["listing"] is None:
            self._fail("listing", "timeout")
            self._finish()
            return
        if self.print_wait is not None:
            doc, finished = self.print_wait
            self.print_wait = None
            printer = self.window.printer
            printer.finished.disconnect(finished)
            printer.cancel()
            doc["errors"].append({"print": "timeout"})
            doc.setdefault("print", {"ok": False, "timeout": True})
            doc.setdefault("print_menus", [])
            self.print_queue = []
            QTimer.singleShot(0, lambda: self._document_done(doc))
            return
        if self.step_wait is not None:
            doc, finished = self.step_wait
            finished({"ok": False, "timeout": True})
            self.window.step.cancel()
            return
        if self.drawing_wait is not None:
            run = self.drawing_wait
            worker = self.window.drawings.worker
            if worker is not None:
                worker.cancel()  # its child ends at once; the stand-in's thread then stops
            self._drawing_done(run, {"ok": False, "problems": ["timed out"]})
            return
        if self.nav is not None:
            nav, self.nav = self.nav, None
            nav["doc"]["errors"].append({"component": nav["rec"]["name"], "code": "timeout"})
            QTimer.singleShot(0, nav["next"])
            return
        if self.pending_3d is not None:
            doc, self.pending_3d = self.pending_3d, None
            doc.pop("_configuration", None)
            doc["errors"].append({"section": "mesh", "code": "timeout"})
            self._document_done(doc)
            return
        if self.current is not None:
            self.current["errors"].append({"section": "all", "code": "timeout"})
            if not self.select_all:
                self.report["documents"].append(self.current)
            else:
                self.error_codes["all:timeout"] = self.error_codes.get("all:timeout", 0) + 1
                self.documents_with_errors += 1
            self.current = None
        QTimer.singleShot(0, self._next)

    # -- the quick filter -----------------------------------------------------------
    def _quick_filter(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """``--quick-filter``: turn ``keys`` on, check the list, save it, and press All."""
        w = self.window
        bar, proxy = w.quick, w.proxy
        rec: dict[str, Any] = {"types": list(keys), "screenshots": [], "problems": []}
        problems = rec["problems"]
        base = [r for r in w.model.rows if proxy.accepts(r, types=False)]
        expected = {r.entry["path"] for r in base if r.file_type in keys}
        for i, key in enumerate(keys):
            button = bar.buttons.get(key)
            if button is None:
                problems.append(f"no button for {key}")
                continue
            if i == 0:  # the keyboard: focus, then Space
                button.setFocus(Qt.FocusReason.TabFocusReason)
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    _key(button, Qt.Key.Key_Space, kind=kind)
            else:
                click(button, (button.width() / 2, button.height() / 2))
            if not button.isChecked():
                problems.append(f"{key} did not turn on")
        self._settle()
        rows = [w.model.rows[proxy.mapToSource(proxy.index(i, 0)).row()] for i in range(proxy.rowCount())]
        shown = {r.entry["path"] for r in rows}
        rec["expected"], rec["shown"] = len(expected), len(shown)
        if shown != expected:
            problems.append(
                {"missing": sorted(expected - shown)[:5], "unexpected": sorted(shown - expected)[:5]}
            )
        for key in keys:  # the count each tooltip gives, against the rows of its type the list shows
            if key in bar.buttons:
                want = sum(1 for r in rows if r.file_type == key)
                line = bar.tooltip_text(key).splitlines()[1]
                said = re.match(r"([\d,]+) files? in the folder shown", line)
                if said is None or int(said.group(1).replace(",", "")) != want:
                    problems.append(f"the tooltip of {key} says {line!r}, not {want:,}")
        if set(bar.selected()) != set(keys) & set(bar.buttons):
            problems.append(f"the types on are {sorted(bar.selected())}")
        stem = "quick_filter_" + _slug("_".join(keys))
        if self.shots:
            for view in ("details", "icons"):
                w.set_view(view)
                path = self._shot(f"{stem}_{view}")
                if path:
                    rec["screenshots"].append(path)
            w.set_view("details")
        click(bar.all_button, (bar.all_button.width() / 2, bar.all_button.height() / 2))
        self._settle()
        if bar.selected() or not bar.all_button.isChecked() or proxy.rowCount() != len(base):
            problems.append("All did not show every type again")
        rec["ok"] = not problems
        if problems:
            self._fail("quick_filter", {"types": list(keys), "problems": problems})
        return rec

    # -- screenshots ------------------------------------------------------------------
    def _settle(self) -> None:
        for _ in range(3):
            QApplication.processEvents()

    def _shot(self, label: str, widget: QWidget | None = None) -> str | None:
        """Save ``widget`` (the window) as the next numbered PNG; its path, or None."""
        if not self.shots:
            return None
        self.shot_no += 1
        name = f"{self.shot_no:02d}_{label}.png"
        try:
            path = _cli.check_output_file(
                os.path.join(self.shots, name),
                [],
                allow_source_dir=False,
                force=self.force,
                source_dirs=[self.folder],
            )
        except _cli.Refused as exc:
            self._fail("screenshot", str(_refused("screenshot", name, exc)))
            return None
        self._settle()
        if not (widget or self.window).grab().save(path, "PNG"):
            self._fail("screenshot", f"could not save {os.path.basename(path)}")
            return None
        self.report["screenshots"].append(path)
        return path

    def _preferences_shot(self, label: str = "preferences") -> None:
        if not self.shots:  # a run with a report and no screenshot folder saves none
            return
        w = self.window
        dialog = PreferencesDialog(w, w.settings, w.store.path, **w.printer.preferences_options())
        dialog.show()
        self._settle()
        self.shot_no += 1
        name = f"{self.shot_no:02d}_{label}.png"
        try:
            path = _cli.check_output_file(
                os.path.join(self.shots or "", name),
                [],
                allow_source_dir=False,
                force=self.force,
                source_dirs=[self.folder],
            )
        except _cli.Refused as exc:
            self._fail("screenshot", str(_refused("screenshot", name, exc)))
        else:
            if dialog.grab().save(path, "PNG"):
                self.report["screenshots"].append(path)
            else:
                self._fail("screenshot", f"could not save {name}")
        dialog.close()
        dialog.deleteLater()

    def _tab_shots(self, name: str) -> list[str]:
        stem = _slug(os.path.splitext(os.path.basename(name))[0])
        tabs = self.window.details.tabs
        self.window.details.preview.set_mode(IMAGE)  # the stored image; the 3D view gets its own shot
        out = []
        for i, tab in enumerate(TABS):
            tabs.setCurrentIndex(i)
            path = self._shot(f"{stem}_{_slug(tab).lower()}")
            if path:
                out.append(path)
        tabs.setCurrentIndex(0)
        return out

    # -- report ------------------------------------------------------------------------
    def _fail(self, where: str, what: Any) -> None:
        self.report["errors"].append({"where": where, "error": what})

    def _fail_once(self, where: str, what: Any) -> None:
        """:meth:`_fail`, unless the run has already failed so."""
        if {"where": where, "error": what} not in self.report["errors"]:
            self._fail(where, what)

    def _finish(self) -> None:
        self.timer.stop()
        r = self.report
        if self.select_all:
            r["select_all"] = {
                "documents_read": self.read,
                "documents_with_errors": self.documents_with_errors,
                "per_document_s": _stats(self.doc_times),
                "per_section_s": {k: _stats(v) for k, v in self.section_times.items()},
                "error_codes": self.error_codes,
            }
        if self.view_3d:
            reader = self.window.mesh_reader
            peak = reader.peak_memory()
            r["mesh_process"] = {
                "started": reader.started,
                "in_job_object": reader.contained,
                "peak_mb": None if peak is None else round(peak / 2**20, 1),
            }
        r["total_s"] = round(time.perf_counter() - self.t0, 3)
        failed = bool(r["errors"]) or any(d["errors"] for d in r["documents"]) or bool(self.error_codes)
        r["ok"] = not failed
        if self.report_path:
            try:
                # Checked again: the file may have appeared since the run started.
                path = _cli.check_output_file(
                    self.report_path, [], allow_source_dir=False, force=self.force, source_dirs=[self.folder]
                )
                _cli._write(path, json.dumps(r, indent=2, ensure_ascii=False).encode("utf-8"))
            except (OSError, _cli.Refused) as exc:
                failed = True
                if sys.stderr is not None:
                    sys.stderr.write(f"could not write the self-test report: {exc}\n")
        QApplication.exit(1 if failed else 0)
