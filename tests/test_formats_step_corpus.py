"""STEP files in the folders of a private corpus (opt-in, numbers only).

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names the corpus manifest. Every
``.step``, ``.stp`` and ``.p21`` file in the folders that hold the manifest's
SOLIDWORKS documents (listed with :mod:`solidseas.walk`, one folder at a time, no
link followed, no placeholder opened) is read in a worker process below normal
priority: opened, its tree built and its scene tessellated, each object's mesh
checked for closure and each closed solid's shells for how they face
(:mod:`solidseas.tessellate.checks`), and the scene's self-check and repair warnings
counted. Nothing but counts, rates, tokens and times is printed or asserted: no file
name, folder or value. Every file's size and modification time are taken before and
after, and must not change.

``SOLIDSEAS_STEP_SECONDS`` (default 300) bounds each file's scene.
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
EXTENSIONS = (".step", ".stp", ".p21")


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


def _listing(folders: list[str]) -> tuple[list[tuple[str, str]], dict[str, tuple[int, int]]]:
    """The STEP files of the folders, and the size and modification time of every file in
    them, from their listings alone."""
    from solidseas.walk import Walk

    steps, every = [], {}
    for folder in folders:
        try:
            for e in Walk(folder, recursive=False):
                if e.kind != "file":
                    continue
                every[e.path] = (e.size, e.mtime_ns)
                if e.name.lower().endswith(EXTENSIONS):
                    steps.append((e.path, folder))
        except OSError:
            continue
    return steps, every


def _inside_out(pos, tris) -> bool:
    """Whether a closed mesh has a shell whose signed volume disagrees with how it nests
    (``solidseas.tessellate.checks``): a solid inside out, or a void facing out."""
    from solidseas.tessellate import checks

    points = checks.Flat(pos)
    found = checks.shells(points, tris, checks.pieces(tris, len(pos) // 3), closed=True)
    depth = checks.nesting(points, tris, found) if len(found) > 1 else [0] * len(found)
    return bool(checks.inside_out(found, depth))


def _read_one(job: tuple[str, str, float]) -> dict:
    """One file read: what happened, as tokens and numbers."""
    from solidseas import export
    from solidseas.formats import Limits, open_model

    path, folder, seconds = job
    rec: dict = {"read": False}
    st = os.stat(path)
    rec["before"] = (st.st_size, st.st_mtime_ns)
    try:
        t0 = time.perf_counter()
        with open_model(path, within=folder, limits=Limits(seconds=seconds)) as doc:
            rec["variant"] = doc.variant
            doc.tree()
            rec["tree_s"] = time.perf_counter() - t0
            rec["doc_type"] = doc.doc_type
            rec["units"] = doc.units.get("length")
            rec["warnings"] = sorted({w.code for w in doc.warnings})
            m = doc._model
            rec["occurrences"] = len(m.structure.occurrences)
            rec["unresolved"] = m.structure.unresolved
            rec["styled"] = m.colours.styled
            rec["coloured"] = sum(1 for o in m.plan.objects if o.color is not None)
            t1 = time.perf_counter()
            scene = doc.scene(prefer="bodies", max_seconds=seconds)
            rec["scene_s"] = time.perf_counter() - t1
            rec["read"] = True
            rec["faces"] = scene.counts.get("faces") or 0
            rec["faces_done"] = scene.counts.get("faces_done") or 0
            rec["objects"] = len(scene.objects)
            rec["items"] = len(scene.items)
            rec["timed_out"] = "faces_left_out" in {w.code for w in scene.warnings}
            fails: Counter = Counter()
            for s in scene.skipped:
                fails[f"{getattr(s, 'reason', '?')}:{getattr(s, 'surface', None) or 'item'}"] += 1
            rec["fails"] = dict(fails)
            rec["scene_warnings"] = sorted({w.code for w in scene.warnings})
            closed: Counter = Counter()
            edges = [0, 0]  # over the file's solids: open directed edges, edges used twice one way
            for k, o in enumerate(scene.objects):
                kind = m.plan.objects[k].item.kind  # solid, sheet, faceted or tessellated
                if not o.n_triangles:
                    closed[f"{kind}:empty"] += 1
                    continue
                pos, tris = export.weld(o)
                whole = export.oriented_closed(tris, len(pos) // 3)
                closed[f"{kind}:{'closed' if whole else 'open'}"] += 1
                if kind == "solid" and not whole:
                    from solidseas.tessellate import checks

                    got = checks.edge_use(tris)
                    edges[0] += got[0]
                    edges[1] += got[1]
                if whole and kind == "solid" and _inside_out(pos, tris):
                    closed["solid:inside_out"] += 1
            rec["closed"] = dict(closed)
            rec["edges"] = edges
    except Exception as exc:  # the type only: a message can quote the file
        rec["error"] = type(exc).__name__
        rec["limit"] = (getattr(exc, "detail", None) or {}).get("limit")
    st = os.stat(path)
    rec["after"] = (st.st_size, st.st_mtime_ns)
    return rec


def _quantiles(values: list[float]) -> str:
    v = sorted(values)
    return f"median {v[len(v) // 2]:.2f}, 90th percentile {v[int(len(v) * 0.9)]:.2f}, largest {v[-1]:.1f}"


def test_step_files_in_the_corpus_folders(capsys):
    folders = _folders()
    assert folders, "the manifest names no folder"
    seconds = float(os.environ.get("SOLIDSEAS_STEP_SECONDS", "300"))
    _lower_priority()
    steps, before = _listing(folders)
    jobs = sorted(((p, f, seconds) for p, f in steps), key=lambda j: before.get(j[0], (0, 0))[0])
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1), initializer=_lower_priority) as pool:
        results = list(pool.map(_read_one, jobs))
    _steps, after = _listing(folders)
    changed = sum(1 for k, v in before.items() if after.get(k, v) != v)
    changed += sum(1 for r in results if r["before"] != r["after"])
    read = [r for r in results if r["read"]]
    errors = Counter(
        r["error"] + (f"/{r['limit']}" if r.get("limit") else "") for r in results if "error" in r
    )
    faces = sum(r["faces"] for r in read)
    done = sum(r["faces_done"] for r in read)
    assemblies = [r for r in read if r["doc_type"] == "assembly"]
    occurrences = sum(r["occurrences"] for r in assemblies)
    unresolved = sum(r["unresolved"] for r in assemblies)
    styled = [r for r in read if r["styled"]]
    coloured = sum(1 for r in styled if r["coloured"])
    empty = [r for r in read if not r["objects"]]
    closed: Counter = Counter()
    fails: Counter = Counter()
    for r in read:
        closed.update(r["closed"])
        fails.update(r["fails"])
    with capsys.disabled():
        print(f"\nSTEP files: {len(results)}; read {len(read)}; errors by type: {dict(errors)}")
        print(f"  variants: {dict(Counter(r['variant'] for r in read))}")
        print(f"  units: {dict(Counter(r['units'] for r in read))}")
        print(f"  faces done: {done} of {faces} ({100.0 * done / max(faces, 1):.2f} percent)")
        print(f"  files with every face done: {sum(1 for r in read if r['faces'] == r['faces_done'])}")
        print(f"  objects by kind and closure: {dict(closed)}")
        # Per file, not per solid: a file whose solids were open already can still get worse.
        edges = [r["edges"] for r in read]
        most = max((e[1] for e in edges), default=0)
        print(
            f"  open solids' directed edges: {sum(e[0] for e in edges)} with no partner, in "
            f"{sum(1 for e in edges if e[0])} files; {sum(e[1] for e in edges)} used twice the same way, "
            f"in {sum(1 for e in edges if e[1])} files (most in one file {most})"
        )
        print(f"  faces left out, by reason and surface: {dict(fails.most_common(20))}")
        print(f"  assemblies: {len(assemblies)}; occurrences {occurrences}, without a placement {unresolved}")
        print(f"  styled files: {len(styled)}, with a coloured object: {coloured}")
        timed_out = sum(r["timed_out"] for r in read)
        print(f"  files with no geometry: {len(empty)}; stopped by the time bound: {timed_out}")
        print(f"  warnings: {dict(Counter(w for r in read for w in r['warnings']))}")
        print(f"  scene warnings (files): {dict(Counter(w for r in read for w in r['scene_warnings']))}")
        print(f"  tree seconds: {_quantiles([r['tree_s'] for r in read])}")
        print(f"  scene seconds: {_quantiles([r['scene_s'] for r in read])}")
        print(f"files snapshotted: {len(before)}; changed while read: {changed}")
    assert changed == 0
    assert len(read) >= 0.95 * len(results)
    assert done >= 0.99 * faces
    assert unresolved <= 0.05 * max(occurrences, 1)
    assert coloured >= 0.95 * len(styled)
