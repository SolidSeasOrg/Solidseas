"""SOLIDWORKS check: what SOLIDWORKS makes of the native writer's candidate parts.

Run by the PC for a ``solidworks-check`` request with ``check`` = ``native-writer``
(``docs/TWO_MACHINES.md``), from a worktree, as ``python scripts/sw-checks/native-writer.py --json``.

1. Makes the candidates with no SOLIDWORKS: ``python -m swnative.experiments``
   in a process of its own, which fails if it loaded anything that reaches SOLIDWORKS.
2. Builds the bridge into this worktree, starts it, and has it start its own SOLIDWORKS
   (``start_solidworks``: never the user's session, never a running instance).
3. For each candidate: ``open_document`` (read-only), ``native_check`` with a forced rebuild,
   a depth edit and a native copy saved into this worktree, ``close_document``; then the same
   for the saved copy, which shows whether the edit survives a save and reopen.
4. Ends its SOLIDWORKS, writes the full reports to ``build/native-writer-check/report.json``
   and prints one JSON object of numbers and fixed words: each candidate's verdict
   (``swnative.experiments.judge``, in ``research/``). The report file is a deliverable the PC may
   copy to the VM (synthetic files only: no path or name from the user's machine is in it
   but the worktree's own).

Everything it writes is in ``build/native-writer-check`` under the worktree. It reads no file
outside the worktree but SOLIDWORKS' own install, and it uses no corpus or user file.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

from solidseas.swapi.bridge import Bridge, BridgeError  # noqa: E402
from solidseas.swapi.build import build_bridge  # noqa: E402
from swnative.experiments import judge  # noqa: E402

OUT = ROOT / "build" / "native-writer-check"


def _check(bridge: Bridge, path: Path, candidate: dict, save: Path | None) -> dict:
    report: dict = {"path": path.name}
    try:
        opened = bridge.request("open_document", {"path": str(path)})
    except BridgeError as e:
        report.update(
            opened=False, open_error=getattr(e, "code", None) or str(e), details=getattr(e, "details", None)
        )
        return report
    report.update(
        opened=True,
        open_errors=opened.get("errors", 0),
        open_warnings=opened.get("warnings", 0),
        open_warning_names=opened.get("warning_names", []),
    )
    args = {"doc": opened["doc"]}
    if save is not None:
        args.update(
            dimension=candidate["edit"]["dimension"], value=candidate["edit"]["value"], save_path=str(save)
        )
    try:
        report["check"] = bridge.request("native_check", args)
    except BridgeError as e:
        report["check_error"] = getattr(e, "code", None) or str(e)
    finally:
        try:
            bridge.request("close_document", {"doc": opened["doc"]})
        except BridgeError as e:
            report["close_error"] = str(e)
    return report


def _check_attached(bridge: Bridge, path: Path, candidate: dict, save: Path | None) -> dict:
    """The same as _check, in the person's session through the test-session operations."""
    report: dict = {"path": path.name}
    try:
        opened = bridge.request("test_session_open", {"path": str(path)})
    except BridgeError as e:
        report.update(
            opened=False, open_error=getattr(e, "code", None) or str(e), details=getattr(e, "details", None)
        )
        return report
    report.update(
        opened=True,
        open_errors=opened.get("errors", 0),
        open_warnings=opened.get("warnings", 0),
        open_warning_names=opened.get("warning_names", []),
    )
    args = {"document": opened["document"]}
    if save is not None:
        args.update(
            dimension=candidate["edit"]["dimension"], value=candidate["edit"]["value"], save_path=str(save)
        )
    try:
        report["check"] = bridge.request("test_session_native_check", args)
    except BridgeError as e:
        report["check_error"] = getattr(e, "code", None) or str(e)
    finally:
        try:
            bridge.request("test_session_close", {"document": opened["document"]})
        except BridgeError as e:
            report["close_error"] = str(e)
    return report


def person_session(bridge: Bridge) -> int:
    """The PID of the one reachable SOLIDWORKS in this Windows session that SolidSeas did not start."""
    listed = bridge.request("list_sessions", {}, timeout=120)
    found = [x for x in listed["sessions"] if not x.get("solidseas") and x.get("reachable")]
    if len(found) != 1:
        raise RuntimeError(f"expected one SOLIDWORKS session of the person's, found {len(found)}")
    return int(found[0]["pid"])


def main(argv: list[str] | None = None, *, attached: bool = False) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--json", action="store_true", help="print one JSON object (the request runs it this way)"
    )
    ap.parse_args(argv)
    t0 = time.monotonic()
    name = "native-writer-attached" if attached else "native-writer"
    result: dict = {"check": name}
    if OUT.exists():
        result["error"] = f"{OUT.relative_to(ROOT)} exists; run from a fresh worktree"
        print(json.dumps(result))
        return 2
    candidates_dir = OUT / "candidates"
    copies = OUT / "copies"
    gen = subprocess.run(
        [sys.executable, "-m", "swnative.experiments", "--out", str(candidates_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**_env(), "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "research")])},
    )
    result["generation"] = {
        "exit": gen.returncode,
        "stdout": gen.stdout.strip()[-2000:],
        "stderr": gen.stderr[-2000:],
    }
    if gen.returncode != 0:
        print(json.dumps(result))
        return 3
    manifest = json.loads((candidates_dir / "manifest.json").read_text(encoding="utf-8"))
    copies.mkdir(parents=True)
    exe = build_bridge(OUT / "bridge")
    verdicts, reports = [], []
    with Bridge(exe, test_session=attached) as bridge:
        try:
            if attached:
                # The person's own session, as agreed on 2026-10-19: attach, never start or end it.
                pid = person_session(bridge)
                result["solidworks"] = bridge.request("live_attach", {"pid": pid}, timeout=120)
                # A candidate may make SOLIDWORKS fail; never with the person's own work open.
                open_docs = bridge.request("live_documents", {}, timeout=120).get("documents") or []
                if open_docs:
                    bridge.request("live_detach", {})
                    n = len(open_docs)
                    raise RuntimeError(f"the session has {n} document(s) open; run when none are")
            else:
                result["solidworks"] = bridge.request("start_solidworks", {})
        except (BridgeError, RuntimeError) as e:
            result["error"] = getattr(e, "code", None) or str(e)
            (OUT / "report.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "check": name,
                        "error": str(result["error"])[:80],
                        "generation_exit": gen.returncode,
                    }
                )
            )
            return 4
        one = _check_attached if attached else _check
        for cand in manifest["candidates"]:
            path = candidates_dir / cand["file"]
            first = one(bridge, path, cand, copies / cand["file"])
            saved = copies / cand["file"]
            if saved.is_file():
                first["reopened"] = one(bridge, saved, cand, None)
            reports.append(first)
            verdicts.append(judge(cand, first))
        try:
            if attached:
                result["detach"] = bridge.request("live_detach", {})  # closes anything of ours still open
            else:
                result["exit"] = bridge.request("exit_solidworks", {})
        except BridgeError as e:
            result["exit_error"] = str(e)
    result["verdicts"] = verdicts
    result["reports"] = reports
    result["seconds"] = round(time.monotonic() - t0, 1)
    report_file = OUT / "report.json"
    report_file.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(_summary(result, report_file, name)))
    return 0


def _summary(result: dict, report_file: Path, name: str = "native-writer") -> dict:
    """Numbers and fixed words only: the candidates' names come from this commit."""
    keep = (
        "verdict",
        "native",
        "rebuilds_to_features",
        "edit_found",
        "edit_rebuilds",
        "saved",
        "reopen_keeps_edit",
        "volume_as_opened",
        "volume_after_rebuild",
        "reopened_volume",
        "depth_after_rebuild",
        "whats_wrong",
        "open_warnings",
    )
    out = {
        "check": name,
        "generation_exit": result["generation"]["exit"],
        "solidworks_revision": (result.get("solidworks") or {}).get("revision"),
        "seconds": result.get("seconds"),
        "report_file": str(report_file.relative_to(ROOT)).replace("\\", "/"),
        "candidates": {},
    }
    for v in result["verdicts"]:
        row = {k: v[k] for k in keep if k in v}
        row["feature_errors"] = len(v.get("feature_errors") or [])
        if "open_error" in v:
            row["open_error"] = str(v["open_error"])[:80]
        out["candidates"][v["name"]] = row
    out["editable"] = sum(1 for v in result["verdicts"] if v.get("verdict") == "editable")
    return out


def _env() -> dict:
    return dict(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
