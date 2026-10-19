"""Parasolid transmit files in the folders of a private corpus (opt-in, numbers only).

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names the corpus manifest. The
folders that hold the manifest's SOLIDWORKS documents are listed one at a time,
not recursively, with :class:`solidseas.walk.Walk` (no link followed, no cloud
placeholder opened), and every ``.x_t``, ``.x_b``, ``.xmt_txt`` and ``.xmt_bin``
file in them is read, tessellated and exported, each in a worker process below
normal priority (this process lowers its own priority too). Nothing but counts,
rates and times is printed or asserted: no file name, folder or value. The size
and modification time of the manifest and of every file read are taken before and
after, and must not change.

What it expects (``docs/formats/parasolid.md``): every file either read or refused
with a documented rule or bound, never another error.
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
EXTENSIONS = (".x_t", ".x_b", ".xmt_txt", ".xmt_bin")
SCENE_SECONDS = 600.0


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


def _files(folders: list[str]) -> dict[str, tuple[int, int]]:
    """Every Parasolid file directly in the folders, with its size and modification time
    from the listing (nothing opened)."""
    from solidseas.walk import Walk

    out = {}
    for folder in folders:
        try:
            for e in Walk(folder, recursive=False):
                if e.kind == "file" and os.path.splitext(e.name)[1].lower() in EXTENSIONS:
                    out[e.path] = (e.size, e.mtime_ns)
        except OSError:
            continue
    return out


def _stat(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _error(exc: BaseException) -> str:
    """An error as tokens only: its code and the rule or limit it names (a message can
    quote a path or a value)."""
    detail = getattr(exc, "detail", None) or {}
    extra = detail.get("rule") or detail.get("limit") or ""
    return f"{getattr(exc, 'code', type(exc).__name__)}:{extra}"


def _turned(rotation) -> bool:
    return any(abs(rotation[i][j] - (1.0 if i == j else 0.0)) > 1e-9 for i in range(3) for j in range(3))


def _read_one(path: str) -> dict:
    """One file: its head, its scene, its export and its bodies, as tokens and numbers."""
    from solidseas import export
    from solidseas.formats import open_model
    from solidseas.formats.solidworks.parasolid import validate
    from solidseas.render import render_preview

    rec: dict = {"before": _stat(path), "size": os.path.getsize(path)}
    folder = os.path.dirname(path)
    try:
        t0 = time.perf_counter()
        with open_model(path, within=folder, hold_open=True) as doc:
            doc.summary(include=("properties",))
            rec["head_s"] = time.perf_counter() - t0
            rec["head"] = True
            rec["variant"] = doc.variant
            rec["doc_type"] = doc.doc_type
            rec["header"] = bool(doc.keywords)
            t1 = time.perf_counter()
            scene = doc.scene(max_seconds=SCENE_SECONDS)
            rec["scene_s"] = time.perf_counter() - t1
            rec["read"] = True
            for k in ("bodies", "faces", "faces_done", "triangles", "items", "objects", "components"):
                rec[k] = scene.counts.get(k) or 0
            rec["reasons"] = dict(Counter(getattr(s, "reason", "") for s in scene.skipped))
            rec["turned"] = sum(1 for it in scene.items if _turned(it.placement.rotation))
            rec["warnings"] = sorted({w.code for w in (*doc.warnings, *scene.warnings)})
            t2 = time.perf_counter()
            bodies = doc.bodies()
            rec["bodies_valid"] = sum(1 for b in bodies if validate(b.transmit)["ok"])
            rec["bodies_s"] = time.perf_counter() - t2
            t3 = time.perf_counter()
            try:
                pm = export.print_model(doc, max_seconds=SCENE_SECONDS)
                rec["export_closed"] = pm.closed
                rec["export_objects_closed"] = sum(1 for o in pm.objects if o.closed)
                rec["export_objects"] = len(pm.objects)
            except Exception as exc:  # tokens only
                rec["export_error"] = _error(exc)
            rec["export_s"] = time.perf_counter() - t3
        with open_model(path, within=folder, hold_open=True) as doc:  # a thumbnail, as a listing draws one
            t4 = time.perf_counter()
            try:
                rec["render_partial"] = render_preview(doc).partial
            except Exception as exc:  # tokens only
                rec["render_error"] = _error(exc)
            rec["render_s"] = time.perf_counter() - t4
    except Exception as exc:  # tokens only
        rec["error"] = _error(exc)
    rec["after"] = _stat(path)
    return rec


def test_parasolid_files_in_the_corpus_folders(capsys):
    _lower_priority()
    manifest_before = _stat(MANIFEST)
    folders = _folders()
    assert folders, "the manifest names no folder"
    listed = _files(folders)
    with ProcessPoolExecutor(max_workers=2, initializer=_lower_priority) as pool:
        results = list(pool.map(_read_one, sorted(listed)))
    changed = sum(1 for r in results if r["before"] != r["after"])
    changed += sum(1 for p, v in _files(folders).items() if p in listed and listed[p] != v)
    changed += _stat(MANIFEST) != manifest_before
    read = [r for r in results if r.get("read")]
    errors = Counter(r["error"] for r in results if "error" in r)
    with capsys.disabled():
        print(f"\nfolders: {len(folders)}; Parasolid files: {len(results)}")
        print(f"  by extension and variant: {dict(Counter(r.get('variant') for r in results))}")
        heads = [r for r in results if r.get("head")]
        types = dict(Counter(r["doc_type"] for r in heads))
        print(
            f"  heads read: {len(heads)}; with a common header: "
            f"{sum(1 for r in heads if r['header'])}; doc types {types}"
        )
        print(f"  read and tessellated: {len(read)}; refused or failed: {dict(errors)}")
        if read:
            faces = sum(r["faces"] for r in read)
            done = sum(r["faces_done"] for r in read)
            print(f"  faces done: {done:,} of {faces:,}; triangles {sum(r['triangles'] for r in read):,}")
            valid = sum(r["bodies_valid"] for r in read)
            print(f"  bodies {sum(r['bodies'] for r in read)}, extracted and valid {valid}")
            print(f"  items {sum(r['items'] for r in read)}, components {sum(r['components'] for r in read)}")
            print(f"  items with a rotation other than the identity: {sum(r['turned'] for r in read)}")
            reasons: Counter = Counter()
            for r in read:
                reasons.update(r["reasons"])
            print(f"  faces left out by reason: {dict(reasons)}")
            print(f"  warnings: {dict(Counter(c for r in read for c in r['warnings']))}")
            exported = [r for r in read if "export_closed" in r]
            print(
                f"  exported: {len(exported)}, closed {sum(1 for r in exported if r['export_closed'])}; "
                f"export errors {dict(Counter(r['export_error'] for r in read if 'export_error' in r))}"
            )
            rendered = [r for r in read if "render_s" in r]
            failed = Counter(r["render_error"] for r in rendered if "render_error" in r)
            print(
                f"  thumbnails: {len(rendered) - sum(failed.values())} of {len(rendered)} drawn, "
                f"{sum(1 for r in rendered if r.get('render_partial'))} partial; errors {dict(failed)}"
            )
            for key in ("head_s", "scene_s", "bodies_s", "export_s", "render_s"):
                vals = sorted(r[key] for r in read if key in r)
                print(f"  {key}: median {vals[len(vals) // 2]:.2f}, largest {vals[-1]:.2f}")
            for k, r in enumerate(sorted(read, key=lambda r: r["size"]), 1):  # smallest first, no size
                print(
                    f"    file {k}: {r['variant']} {r['doc_type']}, bodies {r['bodies']}, "
                    f"faces {r['faces_done']}/{r['faces']}, scene {r['scene_s']:.2f} s"
                )
        print(f"  files changed: {changed}")
    assert changed == 0
    allowed = ("format_not_supported:", "limit_exceeded:")
    assert all(e.startswith(allowed) for e in errors), dict(errors)
