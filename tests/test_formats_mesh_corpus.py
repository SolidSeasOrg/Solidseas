"""The mesh readers on the files beside a private corpus (opt-in, numbers only).

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names the corpus manifest. Each folder
that holds the manifest's SOLIDWORKS documents is walked with
:class:`solidseas.walk.Walk` (not recursively: no link followed, no cloud
placeholder opened), and every STL, 3MF, OBJ, PLY, OFF, glTF, GLB and AMF file in
it is read, exported, drawn and, when it stores one, its thumbnail sanitised,
each in a worker process below normal priority. Only counts, rates and times are
printed or asserted: no file name, folder or value. Every file's size and
modification time are taken before and after, and must not change.
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
FORMATS = ("stl", "3mf", "obj", "ply", "off", "gltf", "amf")


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


def _mesh_files(folder: str) -> tuple[list[str], dict[str, tuple[int, int]], Counter]:
    """The mesh files of one folder, the size and time of every file in it, and what the
    walk skipped, from its listing alone."""
    from solidseas.formats.registry import by_extension
    from solidseas.walk import Walk

    files: list[str] = []
    seen: dict[str, tuple[int, int]] = {}
    other: Counter = Counter()
    try:
        for e in Walk(folder, recursive=False):
            if e.kind != "file":
                other[e.kind] += 1
                continue
            seen[e.path] = (e.size, e.mtime_ns)
            spec = by_extension(e.name)
            if spec is not None and spec.id in FORMATS:
                files.append(e.path)
    except OSError:
        other["folder_unreadable"] += 1
    return files, seen, other


def _read_one(path: str) -> dict:
    """One file read, exported and drawn, and its thumbnail sanitised: tokens and numbers."""
    from solidseas import export
    from solidseas.errors import SolidSeasError
    from solidseas.formats import open_model
    from solidseas.formats._source import preview_png
    from solidseas.render import render_preview

    rec: dict = {"read": False}
    st = os.stat(path)
    rec["before"] = (st.st_size, st.st_mtime_ns)
    try:
        t0 = time.perf_counter()
        with open_model(path, within=os.path.dirname(path), hold_open=True) as doc:
            rec["format"] = doc.format
            rec["variant"] = doc.variant
            rec["doc_type"] = doc.doc_type
            rec["head_s"] = time.perf_counter() - t0
            rec["warnings"] = sorted({w.code for w in doc.warnings})
            pv = doc.preview()
            if pv is not None:
                rec["stored"] = True
                rec["sanitised"] = preview_png(pv, doc.limits) is not None
            t1 = time.perf_counter()
            scene = doc.scene()
            rec["read_s"] = time.perf_counter() - t1
            rec["triangles"] = scene.counts["triangles"]
            rec["objects"] = scene.counts["objects"]
            rec["items"] = scene.counts["items"]
            rec["colored"] = sum(1 for o in scene.objects if o.color is not None)
            rec["scene_warnings"] = sorted({w.code for w in scene.warnings})
            rec["skipped"] = len(scene.skipped)
            rec["truncated"] = bool(scene.truncated)
            t2 = time.perf_counter()
            doc.tree()
            rec["tree_s"] = time.perf_counter() - t2
            rec["doc_type_read"] = doc.doc_type  # what a full read settles, when the head could not
            rec["read"] = True
            t3 = time.perf_counter()
            pm = export.print_model(doc)
            rec["export_s"] = time.perf_counter() - t3
            rec["closed"] = pm.closed
            t4 = time.perf_counter()
            r = render_preview(scene)
            rec["render_s"] = time.perf_counter() - t4
            rec["render_partial"] = r.partial
    except SolidSeasError as exc:  # the code and rule only: a message can quote a path
        detail = exc.detail if isinstance(getattr(exc, "detail", None), dict) else {}
        rec["error"] = f"{exc.code}:{detail.get('rule') or detail.get('limit') or ''}"
    except Exception as exc:
        rec["error"] = type(exc).__name__
    st = os.stat(path)
    rec["after"] = (st.st_size, st.st_mtime_ns)
    return rec


def _median(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


def test_mesh_files_in_the_corpus_folders(capsys):
    folders = _folders()
    assert folders, "the manifest names no folder"
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1), initializer=_lower_priority) as pool:
        listed = list(pool.map(_mesh_files, folders))
        files = [f for got in listed for f in got[0]]
        before = {k: v for got in listed for k, v in got[1].items()}
        walked: Counter = Counter()
        for got in listed:
            walked.update(got[2])
        results = list(pool.map(_read_one, files, chunksize=1))
        after = {k: v for got in pool.map(_mesh_files, folders) for k, v in got[1].items()}
    changed = sum(1 for r in results if r["before"] != r["after"])
    changed += sum(1 for k, v in before.items() if k in after and after[k] != v)
    by_format: dict[str, list[dict]] = {}
    for r in results:
        by_format.setdefault(r.get("format", "unread"), []).append(r)
    with capsys.disabled():
        print(f"\nfolders walked: {len(folders)}; files listed: {len(before)}; not files: {dict(walked)}")
        print(f"mesh files: {len(results)}")
        for fmt, recs in sorted(by_format.items()):
            read = [r for r in recs if r["read"]]
            errors = Counter(r.get("error") for r in recs if "error" in r)
            print(f"[{fmt}] read {len(read)} of {len(recs)}; errors: {dict(errors)}")
            if not read:
                continue
            print(f"  variants: {dict(Counter(r['variant'] for r in read))}")
            print(f"  doc types: {dict(Counter(r['doc_type'] for r in read))}")
            print(f"  doc types after a full read: {dict(Counter(r['doc_type_read'] for r in read))}")
            stored = [r for r in read if r.get("stored")]
            sanitised = sum(1 for r in stored if r.get("sanitised"))
            print(f"  stored thumbnails: {len(stored)}, sanitised: {sanitised}")
            tris = sorted(r["triangles"] for r in read)
            objs = sorted(r["objects"] for r in read)
            items = sorted(r["items"] for r in read)
            print(f"  triangles placed: median {tris[len(tris) // 2]:,}, largest {tris[-1]:,}")
            print(f"  objects: median {objs[len(objs) // 2]}, largest {objs[-1]}; items: largest {items[-1]}")
            print(f"  files with coloured objects: {sum(1 for r in read if r['colored'])}")
            print(f"  closed after welding: {sum(1 for r in read if r.get('closed'))} of {len(read)}")
            warn = Counter(w for r in read for w in (*r["warnings"], *r["scene_warnings"]))
            print(f"  warnings: {dict(sorted(warn.items()))}")
            print(
                f"  items skipped: {sum(r['skipped'] for r in read)}; scenes cut short: "
                f"{sum(1 for r in read if r['truncated'])}"
            )
            for key in ("head_s", "read_s", "tree_s", "export_s", "render_s"):
                vals = [r[key] for r in read if key in r]
                if vals:
                    print(f"  {key}: median {_median(vals):.3f}, largest {max(vals):.3f}")
            print(f"  previews partial: {sum(1 for r in read if r.get('render_partial'))}")
        print(f"files snapshotted: {len(before)}; changed while read: {changed}")
    assert changed == 0
    assert all(r["read"] for r in results), "a mesh file in the corpus folders was not read"
    packages = [r for r in by_format.get("3mf", []) if r["read"]]
    assert all(r.get("sanitised") for r in packages), "a 3MF has no thumbnail SolidSeas could sanitise"
