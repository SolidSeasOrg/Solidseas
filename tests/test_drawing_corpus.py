"""Drawings of a folder of real parts (opt-in, docs/DRAWINGS.md 20.3 and 19.6).

Runs only when ``SOLIDSEAS_DRAWING_CORPUS`` names a folder, or else ``SOLIDSEAS_CORPUS_MANIFEST``
names the corpus manifest (an exchange ``corpus-measure`` run, its parts those the manifest
lists as ``modern`` or ``ole``, its sample ``SOLIDSEAS_CORPUS_SAMPLE``): every ``.sldprt`` below it
(links and cloud placeholders never followed or opened) is drawn in a child process of
its own (``drawing_corpus_child.py``, which runs ``solidseas drawing check PART --json``),
at below-normal priority and with a timeout, so a part that hangs or crashes is one
failed outcome and the sweep goes on. ``check`` writes nothing, and the test checks that
no part's size or modification time changed. Drawing Settings are the defaults with a
company name, from a file under pytest's temporary folder, never the user's. Each
drawing's title block is filled as a user would fill it, so check R6.title is about the
drawing: number, title and part number from the file name, drawn by and finish typed,
and the material typed only where the part names none, so a part's own material, the
weight it gives and the checks of it (R6.material) are measured.

* ``SOLIDSEAS_DRAWING_CORPUS_SAMPLE=N``: draw ``random.Random(20261007).sample`` of N.
* ``SOLIDSEAS_DRAWING_CORPUS_WORKERS=N``: children at a time (default 2).
* ``SOLIDSEAS_DRAWING_CORPUS_TIMEOUT=S``: seconds a part may take (default 300, the
  150 s of ``DrawingLimits.seconds_total`` and the child's start).
* ``SOLIDSEAS_DRAWING_CORPUS_STRICT=1``: also hold the stage 1 targets that 20.3 says
  are confirmed after the first measurement: nothing failed (no crash or hang), and no
  hard layout conflict in a drawing below 100 dimensions.

It counts outcomes: **complete**, **reduced-dimension**, **errors** (with the failing
check ids), **refused** (with the reason: the error code and its rule, limit or
parameter) and **failed** (a crash, a timeout, an internal error); hard conflicts
(``R11.collisions``); dimensions and views per drawing; seconds per stage; and the
recognised-area fraction per size band (up to 100, 100 to 500, 500 to 3,000 and over
3,000 faces). The hard conflicts are also broken down (``drawing_corpus_child.summarise``):
by the pair of item kinds that collide, or the item that found no clear place; by the
kinds of view they are in; the drawings counted by dimensions against conflicts; and the
ten drawings with the most conflicts as rows of numbers. Of the drawings made, it counts
where the title block's material came from (the part, the settings' list or typed), how
many show a calculated weight, and the R6.material findings by level. It prints numbers,
check ids and fixed words only, never a path or a part's name (18).
"""

import json
import os
import random
import statistics
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from drawing_corpus_child import SETTINGS, drawing_row, summarise, summarise_titles, title_row
from jsonschema_subset import validate

CORPUS = os.environ.get("SOLIDSEAS_DRAWING_CORPUS")
# Without a folder, the parts of the corpus manifest (an exchange corpus-measure run)
MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
pytestmark = pytest.mark.skipif(
    not (CORPUS or MANIFEST), reason="neither SOLIDSEAS_DRAWING_CORPUS nor SOLIDSEAS_CORPUS_MANIFEST is set"
)
SRC = Path(__file__).resolve().parents[1] / "src"
CHILD = Path(__file__).resolve().parent / "drawing_corpus_child.py"
BANDS = ((100, "up to 100"), (500, "100 to 500"), (3000, "500 to 3,000"), (None, "over 3,000"))
FAILED_CODES = ("internal", "worker_crashed", "timeout")
HARD_CONFLICT = "R11.collisions"


def _manifest_parts(manifest: str) -> list[str]:
    """The parts the corpus manifest lists that SolidSeas reads (format modern or ole)."""
    import csv

    with open(manifest, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("format") in ("modern", "ole")]
    return sorted(r["path"] for r in rows if r["path"].lower().endswith(".sldprt"))


def _parts(folder: str) -> list[str]:
    from solidseas.walk import Walk

    found = [e.path for e in Walk(folder, max_examined=None) if e.kind == "file"]
    return sorted(p for p in found if p.lower().endswith(".sldprt"))


def _start(argv: list[str], env: dict) -> subprocess.Popen:
    """A child at below-normal priority where the platform allows it: the priority class
    on Windows, a niceness of 10 elsewhere (set once the child exists, so no code runs
    between fork and exec)."""
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, creationflags=flags
    )
    if hasattr(os, "setpriority"):
        try:
            os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
        except OSError:
            pass  # the child already ended
    return proc


def _draw(part: str, settings: str, timeout: float) -> tuple[str, dict, dict | None, dict | None]:
    """One part in a child of its own: ("ok" or "error", the envelope, the hard conflicts
    broken down or None, the title measures or None), or ("failed", {"reason"}, None,
    None) when the child hung, crashed or printed no JSON document."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    argv = [sys.executable, str(CHILD), part, settings]
    proc = _start(argv, env)
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return "failed", {"reason": "timeout"}, None, None
    try:
        got = json.loads(out.decode("utf-8"))
        doc = got["envelope"]
        conflicts = got["conflicts"]
        title = got["title"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return "failed", {"reason": f"no result (exit {proc.returncode})"}, None, None
    return ("ok" if doc.get("ok") else "error"), doc, conflicts, title


def _band(faces: int) -> str:
    for top, name in BANDS:
        if top is None or faces <= top:
            return name
    return BANDS[-1][1]


def _stat(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 3),
        "mean": round(statistics.fmean(values), 3),
        "max": round(max(values), 3),
    }


def _stat_all(paths: list[str]) -> dict[str, tuple[int, int] | None]:
    out = {}
    for p in paths:
        try:
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
        except OSError:
            out[p] = None
    return out


def test_drawing_corpus(tmp_path, capsys):
    from solidseas import model

    parts = _parts(CORPUS) if CORPUS else _manifest_parts(MANIFEST)
    sample = os.environ.get("SOLIDSEAS_DRAWING_CORPUS_SAMPLE") or os.environ.get("SOLIDSEAS_CORPUS_SAMPLE")
    if sample:
        parts = sorted(random.Random(20261007).sample(parts, min(int(sample), len(parts))))
    assert parts, "the folder holds no .sldprt"
    workers = max(1, int(os.environ.get("SOLIDSEAS_DRAWING_CORPUS_WORKERS", "2")))
    timeout = float(os.environ.get("SOLIDSEAS_DRAWING_CORPUS_TIMEOUT", "300"))
    strict = os.environ.get("SOLIDSEAS_DRAWING_CORPUS_STRICT") == "1"
    settings = tmp_path / "Drawing.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    schema = {k: model.envelope_schema(k) for k in ("drawing_result", "error")}
    before = _stat_all(parts)

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda p: _draw(p, str(settings), timeout), parts))

    outcomes: Counter = Counter()
    failing_checks: Counter = Counter()
    refused: Counter = Counter()
    failed: Counter = Counter()
    dimensions: list[float] = []
    views: list[float] = []
    stages: dict[str, list[float]] = {}
    bands: dict[str, list[float]] = {}
    conflicts = conflicted = conflicted_small = 0
    rows: list[dict] = []
    titles: list[dict] = []
    for status, doc, broken_down, title in results:
        if status == "failed":
            outcomes["failed"] += 1
            failed[doc["reason"]] += 1
            continue
        kind = "drawing_result" if status == "ok" else "error"
        assert validate(doc, schema[kind], strict=True) == []
        if status == "error":
            err = doc["error"]
            detail = err["detail"]
            if err["code"] in FAILED_CODES:
                outcomes["failed"] += 1
                failed[err["code"]] += 1
            else:
                outcomes["refused"] += 1
                why = detail.get("rule") or detail.get("limit") or detail.get("parameter")
                refused[err["code"] + (f" ({why})" if isinstance(why, str) else "")] += 1
            continue
        data = doc["data"]
        errors = [c["code"] for c in data["checks"] if c["level"] == "error"]
        hard = sum(1 for c in data["checks"] if c["code"] == HARD_CONFLICT)
        counts = data["drawing"]["counts"]
        coverage = data["coverage"]
        if errors:
            outcomes["errors"] += 1
            failing_checks.update(set(errors))
        elif coverage["complete"]:
            outcomes["complete"] += 1
        else:
            outcomes["reduced-dimension"] += 1
        conflicts += hard
        conflicted += bool(hard)
        conflicted_small += bool(hard) and counts["shown"] < 100
        rows.append(drawing_row(counts, hard, broken_down))
        titles.append(title_row(data, title))
        dimensions.append(counts["shown"])
        views.append(counts["views"])
        for stage, seconds in data["seconds"].items():
            stages.setdefault(stage, []).append(seconds)
        if coverage["area_fraction"] is not None:
            bands.setdefault(_band(coverage["faces"]), []).append(coverage["area_fraction"])

    numbers = {
        "parts": len(parts),
        "outcomes": dict(sorted(outcomes.items())),
        "failing_checks": dict(failing_checks.most_common()),
        "refused": dict(refused.most_common()),
        "failed": dict(failed.most_common()),
        "hard_conflicts": conflicts,
        "drawings_with_hard_conflicts": conflicted,
        "of_them_below_100_dimensions": conflicted_small,
        "dimensions_per_drawing": _stat(dimensions),
        "views_per_drawing": _stat(views),
        "seconds_per_stage": {stage: _stat(v) for stage, v in stages.items()},
        "recognised_area_by_faces": {name: _stat(bands[name]) for _top, name in BANDS if name in bands},
        **summarise(rows),
        "title_blocks": summarise_titles(titles),
    }
    with capsys.disabled():
        print(f"\ndrawing corpus: {json.dumps(numbers)}")
    assert sum(outcomes.values()) == len(parts)  # one outcome a part
    assert _stat_all(parts) == before  # the sweep never writes a part
    if strict:
        assert outcomes["failed"] == 0, numbers["failed"]
        assert conflicted_small == 0
