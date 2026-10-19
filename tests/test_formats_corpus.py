"""Model files in the folders of a private corpus (opt-in, numbers only).

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names the corpus manifest. The
folders that hold the manifest's SOLIDWORKS documents are listed with
``formats="all"``, one folder at a time and not recursively, and every STL file
in them is read, exported and drawn, each in a worker process below normal
priority. Nothing but counts, rates and times is printed or asserted: no file
name, folder or value. Every file's size and modification time are taken
before and after, and must not change.
"""

import csv
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import pytest

MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
pytestmark = pytest.mark.skipif(not MANIFEST, reason="SOLIDSEAS_CORPUS_MANIFEST is not set")


def _lower_priority() -> None:
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        os.nice(10)


def _folders() -> list[str]:
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        return sorted({os.path.dirname(r["path"]) for r in csv.DictReader(fh) if r.get("path")})


def _snapshot(folders: list[str]) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file in the folders, from their listings
    (no file is opened, and no placeholder recalled)."""
    out = {}
    for folder in folders:
        try:
            with os.scandir(folder) as it:
                for e in it:
                    if e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        out[e.path] = (st.st_size, st.st_mtime_ns)
        except OSError:
            continue
    return out


def _list_one(folder: str) -> dict:
    """Statuses and formats of one folder's listing, as counts."""
    from solidseas import scan

    out: Counter = Counter()
    stl: list[str] = []
    try:
        for e in scan(folder, formats="all", include=()):
            if e["type"] != "file":
                continue
            fmt = (e["model"] or {}).get("format") or ("solidworks" if e["format"] else "other")
            out[f"{e['status']}:{fmt}"] += 1
            if fmt == "stl" and e["status"] == "ok":
                stl.append(os.path.join(folder, *e["path"].split("/")))
    except OSError:
        out["folder_unreadable"] += 1
    return {"counts": dict(out), "stl": stl}


def _read_one(path: str) -> dict:
    """One STL read, exported and drawn: what happened, as tokens and numbers."""
    from solidseas import export
    from solidseas.formats import open_model
    from solidseas.render import render_preview

    rec: dict = {"read": False}
    try:
        st = os.stat(path)
        rec["before"] = (st.st_size, st.st_mtime_ns)
        t0 = time.perf_counter()
        with open_model(path, within=os.path.dirname(path)) as doc:
            rec["variant"] = doc.variant
            scene = doc.scene()
            rec["read_s"] = time.perf_counter() - t0
            rec["triangles"] = scene.counts["triangles"]
            rec["read"] = True
            t1 = time.perf_counter()
            pm = export.print_model(doc)
            rec["export_s"] = time.perf_counter() - t1
            rec["closed"] = pm.closed
            t2 = time.perf_counter()
            r = render_preview(scene)
            rec["render_s"] = time.perf_counter() - t2
            rec["render_partial"] = r.partial
    except Exception as exc:  # the type only: a message can quote a path
        rec["error"] = type(exc).__name__
    st = os.stat(path)
    rec["after"] = (st.st_size, st.st_mtime_ns)
    return rec


def test_model_files_in_the_corpus_folders(capsys):
    folders = _folders()
    assert folders, "the manifest names no folder"
    before = _snapshot(folders)
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1), initializer=_lower_priority) as pool:
        listings = list(pool.map(_list_one, folders))
        statuses: Counter = Counter()
        stl = []
        for got in listings:
            statuses.update(got["counts"])
            stl.extend(got["stl"])
        results = list(pool.map(_read_one, stl))
    read = [r for r in results if r["read"]]
    errors = Counter(r.get("error") for r in results if "error" in r)
    changed = sum(1 for r in results if "before" in r and r["before"] != r["after"])
    after = _snapshot(folders)
    changed += sum(1 for k, v in before.items() if k in after and after[k] != v)
    with capsys.disabled():
        print(f"\nfolders listed: {len(folders)}")
        for key, n in sorted(statuses.items()):
            print(f"  {key}: {n}")
        print(f"STL read: {len(read)} of {len(results)}; errors by type: {dict(errors)}")
        if read:
            variants = Counter(r["variant"] for r in read)
            exported = [r for r in read if "closed" in r]
            print(f"  variants: {dict(variants)}")
            closed = sum(1 for r in exported if r["closed"])
            print(f"  exported: {len(exported)}, closed after welding: {closed}")
            tris = sorted(r["triangles"] for r in read)
            print(f"  triangles: median {tris[len(tris) // 2]:,}, largest {tris[-1]:,}")
            for key in ("read_s", "export_s", "render_s"):
                vals = sorted(r[key] for r in read if key in r)
                if vals:
                    print(f"  {key}: median {vals[len(vals) // 2]:.3f}, largest {vals[-1]:.3f}")
            print(f"  previews partial: {sum(1 for r in read if r.get('render_partial'))}")
        print(f"files snapshotted: {len(before)}; changed while read: {changed}")
    assert changed == 0
    assert len(read) == len(results)
