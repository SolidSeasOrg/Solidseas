"""Entry point: ``python -m solidseas_app [FOLDER or FILE]``, or the SolidSeasViewer executable.

Options:

* ``FOLDER`` opens a folder; a document path opens its folder and selects it.
* ``--self-test-formats --screenshot-dir DIR [--3d]`` writes a synthetic file of
  every 3D format the viewer reads into a temporary folder and checks that each
  lists, previews, shows its details, draws in 3D (with ``--3d``, its view cube
  clicked and a turn about the point under the pointer checked) and exports, 3D
  Print's as 3MF, STL and STEP (:mod:`.selftest_formats`).
* ``--self-test FOLDER --screenshot-dir DIR [--select NAME]...`` runs the
  self-test (:mod:`.selftest`) and exits with its result; ``--select-all``
  and ``--report FILE`` are for robustness runs, ``--3d`` turns the
  interactive 3D view on for the run, ``--configuration NAME[,fitted]`` draws
  the assembly the ``--select`` before it names in that configuration too, after
  turning and zooming the view (``,fitted``: a fitted corner view), and checks
  that the camera is kept, ``--explode PERCENT[,LEVEL]`` explodes it and saves
  the view, ``--pick NAME`` clicks that instance in its 3D view, double-clicks
  it and goes Back,
  ``--open-component NAME`` opens a component's file from the Components tab of
  the document the ``--select`` before it names and goes Back, ``--boxes`` checks
  that every instance without a mesh that has a stored box is drawn as that box,
  ``--transparent NAME[,PERCENT]``, ``--hide NAME``, ``--isolate NAME`` and
  ``--explode-sub NAME,on|off`` change how that instance or sub-assembly looks in
  the 3D view, or whether it explodes, and check what is drawn,
  ``--rotation free`` or ``--rotation turntable`` sets how the 3D view turns for
  the run (free by default), ``--print-dry-run`` presses 3D Print twice for
  each selected document, writing next to the model in the folder under test
  (run it on a copy), checks where each file went and how it is named, and
  reports the program and arguments it would start without starting anything,
  ``--print-row NAME`` and ``--print-view NAME[,sub]`` (or ``--print-view .``)
  print through a row's or the 3D view's context menu in that dry run,
  ``--drawing-dry-run`` makes drawings of each selected part through the New Drawing
  wizard's code path, writes and checks their PDF and DXF in a temporary folder,
  and edits, signs, releases and revises them as the editor does, with stand-ins
  for the dialogs and for Email PDF that start nothing,
  ``--print-format 3mf|stl|step`` sends every print of it in that format and checks
  the format of each (a STEP with the tests' own checker), ``--export-step`` exports
  each selected part with File > Export STEP into a temporary folder and checks
  the file with that checker (an assembly, or a 3D file the STEP export does not
  write, must find the entry off with its reason),
  ``--viewcube REGION`` clicks the view cube (a face, an edge, a corner, ``all``,
  Home or one of its arrows) and checks where the view ends, ``--pivot NAME``
  turns the model about the point of NAME under the pointer and checks it kept its
  pixel (each for every document when given before any ``--select``),
  ``--input-checks`` checks the sideways scroll, Ctrl and Shift during a
  middle-drag and the roll keys on every selected document, ``--quick-filter
  TYPES`` turns the list's quick filter on for those types (``sldprt,step``)
  once the folder is listed, checks the rows shown, saves them and turns it off,
  ``--view-cube on|off`` and ``--pivot-at pointer|centre`` set those two
  settings for the run, and ``--force`` lets it replace its own earlier
  screenshots, report and settings file.

Settings come from ``SolidSeas\\Viewer.ini`` in the roaming application-data
folder (:mod:`.settings`). A self-test never touches that file: it runs with a
settings file of its own next to its report.

The packaged viewer has no console, so a usage error is shown in a message box,
and an unexpected exception in the window is shown instead of ending the program.
Exit codes: 0 success, 1 a self-test failed, 2 a usage error, 3 a self-test
output refused by a write guard (the library's code for a refusal).
"""

import argparse
import os
import sys
import traceback

from solidseas import __version__
from solidseas.trademarks import DISCLAIMER

from .viewmath import FREE, ROTATION_MODES, parse_region

EXIT_USAGE, EXIT_REFUSED = 2, 3


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message)


def _explode_spec(text: str) -> tuple[int, str | None]:
    """``PERCENT[,LEVEL]``: 0 to 100, at ``top`` or ``parts``; without a level, the one the
    Explode bar shows (None), as moving the slider alone does."""
    from .explode import LEVELS

    amount, _, level = text.partition(",")
    level = level.strip() or None
    try:
        percent = int(amount)
    except ValueError:
        percent = -1
    if not 0 <= percent <= 100 or (level is not None and level not in LEVELS):
        raise argparse.ArgumentTypeError(
            f"--explode takes a percentage from 0 to 100 and optionally ,top or ,parts, not {text!r}"
        )
    return percent, level


def _transparent_spec(text: str) -> tuple[str, int | None]:
    """``NAME[,PERCENT]``: a component tree id, and a transparency from 0 to 90 percent
    (None: the self-test's default)."""
    from .appearance import MAX_TRANSPARENCY

    name, comma, tail = text.rpartition(",")
    if not comma or not tail.strip().lstrip("-").isdigit():
        name, tail = text, ""
    percent = int(tail) if tail.strip() else None
    if not name.strip() or (percent is not None and not 0 <= percent <= MAX_TRANSPARENCY):
        raise argparse.ArgumentTypeError(
            f"--transparent takes a component tree id and optionally ,PERCENT from 0 to {MAX_TRANSPARENCY}, "
            f"not {text!r}"
        )
    return name, percent


def _switch_spec(text: str) -> tuple[str, str]:
    """``NAME,on`` or ``NAME,off``: a sub-assembly's component tree id, and whether it
    explodes."""
    name, _, state = text.rpartition(",")
    if not name.strip() or state.strip() not in ("on", "off"):
        raise argparse.ArgumentTypeError(
            f"--explode-sub takes a sub-assembly's id and ,on or ,off, not {text!r}"
        )
    return name, state.strip()


CUBE_ACTIONS = (
    "all",
    "home",
    "set-home",
    "reset-home",
    "roll-cw",
    "roll-ccw",
    "step-up",
    "step-down",
    "step-left",
    "step-right",
    "drag",
)


def _viewcube_spec(text: str) -> str:
    """A view cube region (``front``, ``top-front``, ``front-top-right``: its faces joined by
    hyphens, in any order) or one of :data:`CUBE_ACTIONS`."""
    word = text.strip().lower()
    if word in CUBE_ACTIONS:
        return word
    region = parse_region(word)
    if region is None:
        raise argparse.ArgumentTypeError(
            "--viewcube takes a face (front, back, left, right, top, bottom), an edge or a corner as "
            f"faces joined by hyphens (top-front, front-top-right), or one of {', '.join(CUBE_ACTIONS)}, "
            f"not {text!r}"
        )
    return word


def _configuration_spec(text: str) -> tuple[str, bool]:
    """``NAME`` or ``NAME,fitted``: a configuration, and whether the view is fitted before it
    is chosen (else turned and zoomed)."""
    name, comma, tail = text.rpartition(",")
    if comma and tail.strip() == "fitted" and name.strip():
        return name, True
    if not text.strip():
        raise argparse.ArgumentTypeError("--configuration takes a configuration's name")
    return text, False


def _quick_filter_spec(text: str) -> tuple[str, ...]:
    """``TYPES``: quick filter types or extensions, separated by commas (``sldprt,.STP``)."""
    from .filetypes import ordered, parse_key

    keys = [parse_key(t) for t in text.split(",") if t.strip()]
    if not keys or None in keys:
        raise argparse.ArgumentTypeError(
            f"--quick-filter takes types or extensions separated by commas, such as sldprt,step, not {text!r}"
        )
    return tuple(ordered(k for k in keys if k))


def _name_spec(text: str) -> tuple[str, None]:
    if not text.strip():
        raise argparse.ArgumentTypeError("a component tree id is needed")
    return text, None


class _Look(argparse.Action):
    """``--transparent``, ``--hide``, ``--isolate`` and ``--explode-sub``, kept in the order
    given with the ``--select`` before them, as ``{document: [(action, name, value)]}``;
    the action is the option's ``const``."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        plan = dict(getattr(namespace, self.dest, None) or {})
        selected = getattr(namespace, "select", None) or []
        name, value = values
        plan.setdefault(selected[-1] if selected else None, []).append((self.const, name, value))
        setattr(namespace, self.dest, plan)


def _print_row_spec(text: str) -> tuple[str, str, str]:
    if not text.strip():
        raise argparse.ArgumentTypeError("--print-row takes the name of a row of the Components or BOM tab")
    return "row", text, ""


def _print_view_spec(text: str) -> tuple[str, str, str]:
    """``NAME``, ``NAME,part`` or ``NAME,sub``: an instance's component tree id, and whether
    its part or the nearest sub-assembly it is in is printed; ``.``: the empty space."""
    if text.strip() == ".":
        return "view", "", "space"
    name, comma, which = text.rpartition(",")
    if not comma:
        name, which = text, "part"
    which = which.strip()
    if not name.strip() or which not in ("part", "sub"):
        raise argparse.ArgumentTypeError(
            f"--print-view takes a component tree id and optionally ,part or ,sub, or ., not {text!r}"
        )
    return "view", name, which


class _OpenComponent(argparse.Action):
    """``--open-component NAME``: kept with the ``--select`` before it, as
    ``{document: [names]}``; the key None holds the names given before any ``--select``,
    which apply to every document."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        plan = dict(getattr(namespace, self.dest, None) or {})
        selected = getattr(namespace, "select", None) or []
        plan.setdefault(selected[-1] if selected else None, []).append(values)
        setattr(namespace, self.dest, plan)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="SolidSeasViewer", description=f"SolidSeas Viewer, preview {__version__}", epilog=DISCLAIMER
    )
    p.add_argument("path", nargs="?", help="a folder to open, or a document to select in its folder")
    p.add_argument("--self-test", metavar="FOLDER", help="open FOLDER, capture each details tab and exit")
    p.add_argument(
        "--self-test-formats",
        action="store_true",
        help="write a synthetic file of every 3D format the viewer reads into a temporary folder, check "
        "that each lists, previews, draws in 3D (with --3d) and exports, and exit",
    )
    p.add_argument("--screenshot-dir", metavar="DIR", help="where the self-test saves screenshots")
    p.add_argument("--select", metavar="NAME", action="append", help="a document to select (repeatable)")
    p.add_argument("--select-all", action="store_true", help="read every document, no screenshots or names")
    p.add_argument("--report", metavar="FILE", help="the self-test report (default: DIR/selftest.json)")
    p.add_argument("--force", action="store_true", help="let the self-test replace its earlier outputs")
    p.add_argument(
        "--3d",
        dest="view_3d",
        action="store_true",
        help="with --self-test: turn the interactive 3D view on for the run (never in your settings)",
    )
    p.add_argument(
        "--rotation",
        choices=tuple(ROTATION_MODES),
        help="with --self-test: how the 3D view turns for the run, freely as SOLIDWORKS does (the "
        "default) or as a turntable (never in your settings)",
    )
    p.add_argument(
        "--configuration",
        metavar="NAME[,fitted]",
        type=_configuration_spec,
        action=_OpenComponent,
        help="with --self-test and --3d: draw the assembly the --select before it names in this "
        "configuration too, after turning and zooming the view (with ,fitted: a fitted corner view), and "
        "check that the camera stays, or is fitted again only where it had lost the model (repeatable)",
    )
    p.add_argument(
        "--explode",
        metavar="PERCENT[,LEVEL]",
        type=_explode_spec,
        action=_OpenComponent,
        help="with --self-test and --3d: explode the assembly the --select before it names to PERCENT, "
        "each top-level component (top) or each part (parts), by default as the Explode bar shows, and "
        "save the view (repeatable)",
    )
    p.add_argument(
        "--pick",
        metavar="NAME",
        action=_OpenComponent,
        help="with --self-test and --3d: click the instance NAME (its component tree id) in the 3D view of "
        "the assembly the --select before it names, double-click it and go Back, saving each (repeatable)",
    )
    p.add_argument(
        "--viewcube",
        metavar="REGION",
        type=_viewcube_spec,
        action=_OpenComponent,
        help="with --self-test and --3d: click the view cube of the document the --select before it names "
        "on REGION (a face, an edge or a corner: front, top-front, front-top-right; all for the 26 in "
        "turn; reaching the hidden half through what is drawn), or on home, an arrow (step-up, step-down, "
        "step-left, step-right, roll-cw, roll-ccw), drag it, or set-home and reset-home from its menu, "
        "and check where the view ends (every document's, before any --select; repeatable)",
    )
    p.add_argument(
        "--pivot",
        metavar="NAME",
        action=_OpenComponent,
        help="with --self-test and --3d: turn the model with a drag of the rotate button from where the "
        "instance NAME is drawn (for a part, any NAME: where the part is), or with . from empty space, "
        "and check what it turned about: the point under the pointer, or with --pivot-at centre not it "
        "(every document, before any --select; repeatable)",
    )
    p.add_argument(
        "--input-checks",
        action="store_true",
        help="with --self-test and --3d: check on every selected document's 3D view that a sideways "
        "scroll turns the model as the arrow keys do, that Ctrl and Shift pressed during a SOLIDWORKS "
        "middle-drag switch it, and that Page Up and Page Down roll the view",
    )
    p.add_argument(
        "--view-cube",
        dest="view_cube",
        choices=("on", "off"),
        help="with --self-test: show the 3D view's view cube for the run or not (on by default; never in "
        "your settings)",
    )
    p.add_argument(
        "--pivot-at",
        choices=("pointer", "centre"),
        help="with --self-test: turn the 3D view about the point under the pointer (the default) or about "
        "the middle of the view, for the run (never in your settings)",
    )
    p.add_argument(
        "--boxes",
        action="store_true",
        help="with --self-test and --3d: fail when an instance of an assembly that has no mesh but a stored "
        "box is not drawn as that box, and save the view with the boxes picked and turned off",
    )
    for option, kind, spec, text in (
        (
            "--transparent",
            "transparent",
            _transparent_spec,
            "make the instance or sub-assembly NAME (its component tree id) PERCENT transparent (75 by "
            "default, 0 opaque again) in the 3D view of the assembly the --select before it names, check "
            "what is drawn and save it",
        ),
        ("--hide", "hide", _name_spec, "hide NAME in that 3D view, check that none of it is drawn, save it"),
        (
            "--isolate",
            "isolate",
            _name_spec,
            "hide everything but NAME in that 3D view, check that only it is drawn, save it",
        ),
        (
            "--explode-sub",
            "explode-sub",
            _switch_spec,
            "explode the sub-assembly NAME (on) or keep it together (off) whatever the Explode bar's level, "
            "explode the view, check where its parts are drawn and save it",
        ),
    ):
        metavar = {"--transparent": "NAME[,PERCENT]", "--explode-sub": "NAME,on|off"}.get(option, "NAME")
        p.add_argument(
            option,
            dest="looks",
            metavar=metavar,
            type=spec,
            const=kind,
            action=_Look,
            help=f"with --self-test and --3d: {text}; after the picks, in the order given, then Reset "
            "appearance must give the first picture back (repeatable)",
        )
    p.add_argument(
        "--print-dry-run",
        action="store_true",
        help="with --self-test: press 3D Print twice for each selected part or assembly, export it as the "
        "button does and report the program and arguments it would start, without starting anything; it "
        "writes both print files next to each model in FOLDER, so point it at a copy (a model outside FOLDER "
        "gets them in the temporary folder)",
    )
    p.add_argument(
        "--drawing-dry-run",
        action="store_true",
        help="with --self-test: make a drawing of each selected part through the New Drawing wizard's code "
        "path, write and check its PDF and DXF in a temporary folder, and edit, sign, release and revise it "
        "as the drawing editor does, with stand-ins for the dialogs and Email PDF that start nothing",
    )
    p.add_argument(
        "--print-row",
        dest="print_menus",
        metavar="NAME",
        type=_print_row_spec,
        action=_OpenComponent,
        help="with --print-dry-run: print, twice, the file of the row NAME of the Components or BOM tab of "
        "the document the --select before it names, through the row's context menu, and check both; the "
        "files are written next to the model in FOLDER, or in the temporary folder for a model outside "
        "it (repeatable)",
    )
    p.add_argument(
        "--print-view",
        dest="print_menus",
        metavar="NAME[,sub]",
        type=_print_view_spec,
        action=_OpenComponent,
        help="with --print-dry-run: print, twice, through the 3D view's context menu, the part of the "
        "instance NAME, or with ,sub the nearest sub-assembly it is in, or with . the document shown, and "
        "check both; with --3d the view is right-clicked; the files are written next to the model in "
        "FOLDER, or in the temporary folder for a model outside it (repeatable)",
    )
    p.add_argument(
        "--print-format",
        choices=("3mf", "stl", "step"),
        help="with --print-dry-run: send every print of the run in this format, chosen for the program as "
        "Settings > 3D Print Program chooses it (in the run's own settings), and check each print's format; "
        "a STEP is checked with the tests' own STEP checker, and an assembly must go as 3MF with the reason; "
        "the run fails when no 3D print program is found, as nothing is then sent",
    )
    p.add_argument(
        "--export-step",
        action="store_true",
        help="with --self-test: export each selected part with File > Export STEP into a folder the run "
        "makes in the system's temporary folder, check the file with the tests' own STEP checker and remove "
        "the folder; a drawing must find the entry off, and an assembly or a part of a 3D file the STEP "
        "export does not write (an STL, a STEP, an Alibre Design part...) off with its tooltip saying why",
    )
    p.add_argument(
        "--quick-filter",
        metavar="TYPES",
        action="append",
        type=_quick_filter_spec,
        help="with --self-test: once the folder is listed, turn the list's quick filter on for these "
        "types or extensions (sldprt,step), check the rows shown, save them and turn it off (repeatable)",
    )
    p.add_argument(
        "--open-component",
        metavar="NAME",
        action=_OpenComponent,
        help="with --self-test: open the file of this row of the Components tab of the document the "
        "--select before it names (every document, before any --select), then go Back (repeatable)",
    )
    return p


def _show_error(text: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    box = QMessageBox(QMessageBox.Icon.Critical, "SolidSeas Viewer", text)
    box.setTextFormat(Qt.TextFormat.PlainText)  # it quotes paths from the command line
    box.exec()


def _fail(text: str, code: int) -> int:
    if sys.stderr is not None:
        sys.stderr.write(f"SolidSeasViewer: {text}\n")
    if not os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        _show_error(text)  # offscreen, nobody could close the box
    return code


def use_system_fonts() -> None:
    """Qt's offscreen platform finds no fonts on Windows unless told where they are;
    without this, self-test screenshots show boxes instead of text."""
    if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        windows = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
        os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(windows, "Fonts"))


def window_icon():
    from PySide6.QtGui import QIcon, QPixmap

    from .icon import draw

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(draw(size)))
    return icon


def _formats_self_test(args) -> int:
    """``--self-test-formats``: only ``--screenshot-dir``, ``--report``, ``--3d`` and
    ``--force`` go with it."""
    if not (args.screenshot_dir or args.report):
        raise UsageError("--self-test-formats needs --screenshot-dir or --report")
    others = (
        args.self_test or args.path or args.select or args.select_all or args.rotation or args.configuration
    )
    others = others or args.explode or args.pick or args.boxes or args.looks or args.print_dry_run
    others = others or args.viewcube or args.pivot or args.input_checks or args.view_cube or args.pivot_at
    others = others or args.print_format or args.export_step or args.quick_filter or args.drawing_dry_run
    if others or args.print_menus or args.open_component:
        raise UsageError(
            "--self-test-formats makes its own folder of files: only --screenshot-dir, --report, --3d and "
            "--force go with it"
        )
    from .selftest_formats import run

    return run(args)


def _add_packages_beside() -> None:
    """Add, on a thread of its own, the extension packages that came beside the viewer
    (:func:`solidseas_app.extensions.add_beside`), so a first start lists them as added;
    never in the way of the window, and silent when there are none."""
    import threading

    def work() -> None:
        try:
            from .. import extensions

            extensions.add_beside()
        except Exception:  # a package that cannot be added is added by hand from the page
            pass

    threading.Thread(target=work, name="extensions-beside", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
        if args.self_test_formats:
            return _formats_self_test(args)
        if args.self_test and not (args.screenshot_dir or args.report):
            raise UsageError("--self-test needs --screenshot-dir or --report")
        if args.self_test and not os.path.isdir(args.self_test):
            # otherwise the run waits out the whole listing time for a folder never listed
            raise UsageError(f"--self-test: there is no folder at {args.self_test}")
        if not args.self_test and (
            args.screenshot_dir
            or args.report
            or args.select_all
            or args.force
            or args.view_3d
            or args.rotation
            or args.open_component
            or args.configuration
            or args.explode
            or args.pick
            or args.boxes
            or args.looks
            or args.print_dry_run
            or args.drawing_dry_run
            or args.print_menus
            or args.viewcube
            or args.pivot
            or args.input_checks
            or args.view_cube
            or args.pivot_at
            or args.print_format
            or args.export_step
            or args.quick_filter
        ):
            raise UsageError(
                "--screenshot-dir, --report, --select-all, --3d, --rotation, --configuration, --explode, "
                "--pick, --boxes, --transparent, --hide, --isolate, --explode-sub, --open-component, "
                "--print-dry-run, --drawing-dry-run, --print-row, --print-view, --viewcube, --pivot, "
                "--input-checks, "
                "--quick-filter, --view-cube, --pivot-at, --print-format, --export-step and --force go "
                "with --self-test"
            )
        if args.select_all and args.print_dry_run:
            raise UsageError("--print-dry-run goes with --select, not --select-all")
        if args.select_all and args.drawing_dry_run:
            raise UsageError("--drawing-dry-run goes with --select, not --select-all")
        if args.print_menus and not args.print_dry_run:
            raise UsageError("--print-row and --print-view go with --print-dry-run")
        if args.print_format and not args.print_dry_run:
            raise UsageError("--print-format goes with --print-dry-run")
        if args.select_all and args.export_step:
            raise UsageError("--export-step goes with --select, not --select-all")
        navigation = args.viewcube or args.pivot or args.input_checks
        if args.select_all and (
            args.open_component
            or args.configuration
            or args.explode
            or args.pick
            or args.boxes
            or args.looks
            or navigation
        ):
            raise UsageError(
                "--open-component, --configuration, --explode, --pick, --boxes, --transparent, --hide, "
                "--isolate, --explode-sub, --viewcube, --pivot and --input-checks go with --select, not "
                "--select-all"
            )
        if args.select_all and args.quick_filter:
            raise UsageError(
                "--quick-filter does not go with --select-all, whose report names no documents: it runs "
                "once the folder is listed, with or without --select"
            )
        if (
            args.configuration or args.explode or args.pick or args.boxes or args.looks or navigation
        ) and not args.view_3d:
            raise UsageError(
                "--configuration, --explode, --pick, --boxes, --transparent, --hide, --isolate, "
                "--explode-sub, --viewcube, --pivot and --input-checks go with --3d"
            )
    except UsageError as exc:
        return _fail(f"{exc}\n\n{build_parser().format_usage()}", EXIT_USAGE)

    from .settings import Settings, SettingsStore, default_path

    if args.self_test:
        # The outputs pass the write guards before anything is opened or shown.
        from solidseas.errors import OutputRefusedError

        from .selftest import outputs, settings_output

        try:
            _shots, report = outputs(
                args.self_test, args.screenshot_dir, args.report, select_all=args.select_all, force=args.force
            )
            assert report is not None  # --self-test needs --screenshot-dir or --report
            store = SettingsStore(settings_output(args.self_test, report, force=args.force))
        except OutputRefusedError as exc:
            return _fail(str(exc), EXIT_REFUSED)
        own = Settings(
            view_3d=args.view_3d,
            rotation_mode=args.rotation or FREE,
            view_cube=args.view_cube != "off",
            turn_about_pointer=args.pivot_at != "centre",
            remember_session=False,
        )
        if not store.save(own):
            store = SettingsStore(None)  # the run still gets its own settings, in memory
            store.save(own)
    else:
        store = SettingsStore(default_path())

    use_system_fonts()
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .window import TITLE, MainWindow, show_message

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SolidSeas Viewer")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(window_icon())
    window = MainWindow(store)
    selftest = None

    def excepthook(kind, value, tb) -> None:  # shown, never fatal
        text = "".join(traceback.format_exception(kind, value, tb))
        if sys.stderr is not None:
            sys.stderr.write(text)
        if selftest is not None:
            selftest.report["errors"].append({"where": "exception", "error": f"{kind.__name__}: {value}"})
        else:
            show_message(
                window,
                QMessageBox.Icon.Critical,
                TITLE,
                f"Something went wrong; the viewer keeps running.\n\n{text[-2000:]}",
            )

    sys.excepthook = excepthook
    if args.self_test:
        from PySide6.QtCore import QTimer

        from .selftest import SelfTest

        window.resize(1440, 900)
        if window.settings.view_3d:
            window.details.preview.prepare_view()  # see PreviewPane.prepare_view
        window.show()
        selftest = SelfTest(
            window,
            args.self_test,
            screenshot_dir=args.screenshot_dir,
            select=args.select,
            select_all=args.select_all,
            report=args.report,
            force=args.force,
            view_3d=args.view_3d,
            open_components=args.open_component,
            configurations=args.configuration,
            explodes=args.explode,
            picks=args.pick,
            boxes=args.boxes,
            looks=args.looks,
            print_dry_run=args.print_dry_run,
            drawing_dry_run=args.drawing_dry_run,
            print_menus=args.print_menus,
            viewcubes=args.viewcube,
            pivots=args.pivot,
            input_checks=args.input_checks,
            print_format=args.print_format,
            export_step=args.export_step,
            quick_filters=args.quick_filter,
        )
        QTimer.singleShot(0, selftest.start)
    else:
        last = window.restore_session()
        if window.settings.view_3d:
            window.details.preview.prepare_view()  # see PreviewPane.prepare_view
        window.show()
        _add_packages_beside()
        if args.path:
            window.open_path(os.path.abspath(args.path))
        elif last:
            window.reopen(last)
    code = app.exec()
    if not window.shutdown():
        # A read past its deadline is still running in a worker. Nothing is being
        # written to a document, so leave without waiting for it.
        os._exit(code)
    return code
