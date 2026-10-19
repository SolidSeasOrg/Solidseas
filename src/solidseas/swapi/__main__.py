"""``python -m solidseas.swapi``: batch conversion through SolidSeas' own SOLIDWORKS, and the bridge build.

    python -m solidseas.swapi build [-o dist]
    python -m solidseas.swapi convert D:\\Jobs\\Bracket -o D:\\Exports --format step,stl,3mf --recurse

``convert`` writes ``report.tsv`` into the output folder and exits 0 when every
row is ``ok`` or ``skip``, 4 when any failed, 2 for wrong arguments and 1 when
the bridge or SOLIDWORKS could not be used at all. You started it, so it starts
SOLIDWORKS at once and runs to the end; ``--off-hours`` makes it keep to 02:00
to 07:00 local time (or the window given) instead: it waits for the window,
and when the window closes it ends SOLIDWORKS and carries on in the next one.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

from .batch import FORMATS, OffHours


def _formats(text: str) -> list[str]:
    return [f for f in (p.strip().lower() for p in text.split(",")) if f]


def _seconds(text: str) -> float:
    """A timeout the bridge accepts: more than 0 and at most a day."""
    from .bridge import MAX_TIMEOUT_S

    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number of seconds: {text!r}") from None
    if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT_S:
        raise argparse.ArgumentTypeError(f"must be more than 0 and at most {MAX_TIMEOUT_S:g} seconds")
    return value


def _window(text: str) -> OffHours:
    try:
        return OffHours.parse(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m solidseas.swapi", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="compile SolidSeas.SwBridge.exe")
    b.add_argument("-o", "--output", default=None, help="folder for the program (default: dist)")
    b.add_argument("--solidworks", default=None, help="SLDWORKS.exe of the installation to build against")

    c = sub.add_parser("convert", help="convert documents in a hidden SOLIDWORKS of SolidSeas' own")
    c.add_argument("inputs", nargs="+", help=".sldprt or .sldasm files, or folders")
    c.add_argument("-o", "--output", required=True, help="output folder")
    c.add_argument("--format", default="step,x_t,stl,3mf", help="comma-separated: " + ", ".join(FORMATS))
    c.add_argument("--recurse", action="store_true", help="look in subfolders too")
    c.add_argument("--force", action="store_true", help="replace existing outputs and report.tsv")
    c.add_argument("--allow-source-folder", action="store_true", help="allow writing next to the inputs")
    c.add_argument("--solidworks", default=None, help="path to SLDWORKS.exe")
    c.add_argument("--bridge", default=None, help="path to SolidSeas.SwBridge.exe")
    c.add_argument("--open-timeout", type=_seconds, default=None, help="seconds to open one document")
    c.add_argument("--export-timeout", type=_seconds, default=None, help="seconds to write one output")
    c.add_argument(
        "--off-hours", type=_window, nargs="?", const=OffHours(), default=None, metavar="HH:MM-HH:MM",
        help="run SOLIDWORKS only in this window of local time (default 02:00-07:00), pausing outside it",
    )
    c.add_argument("--json", action="store_true", help="print one JSON object per row")
    args = parser.parse_args(argv)

    if args.command == "build":
        from .bridge import EXE_NAME
        from .build import BridgeBuildError, build_bridge

        out = Path(args.output) if args.output else Path(__file__).resolve().parents[2] / "dist"
        try:
            exe = build_bridge(out, solidworks_exe=args.solidworks)
        except BridgeBuildError as e:
            print(f"build failed: {e}", file=sys.stderr)
            return 1
        print(f"built {exe}" if exe.name == EXE_NAME else exe)
        return 0

    from .batch import Timeouts, convert, write_report
    from .bridge import BridgeError

    defaults = Timeouts()
    timeouts = Timeouts(
        open=defaults.open if args.open_timeout is None else args.open_timeout,
        export=defaults.export if args.export_timeout is None else args.export_timeout,
    )
    report = Path(args.output) / "report.tsv"
    if report.exists() and not args.force:
        print(f"{report} exists; pass --force to replace outputs", file=sys.stderr)
        return 3
    try:
        rows = convert(
            args.inputs,
            args.output,
            _formats(args.format),
            recurse=args.recurse,
            overwrite=args.force,
            allow_source_folder=args.allow_source_folder,
            solidworks_exe=args.solidworks,
            bridge_exe=args.bridge,
            timeouts=timeouts,
            log=lambda msg: print(msg, file=sys.stderr),
            off_hours=args.off_hours,
        )
    except (ValueError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except BridgeError as e:
        print(str(e), file=sys.stderr)
        return 1
    write_report(rows, report, overwrite=args.force)
    for r in rows:
        if args.json:
            print(json.dumps(asdict(r), ensure_ascii=False))
        else:
            detail = r.output if r.status == "ok" else (r.message or r.output)
            print(f"{r.status:4}  {r.format:5}  {Path(r.input).name}  {detail}")
    print(f"report: {report}", file=sys.stderr)
    return 4 if any(r.status == "fail" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
