"""Corpus sweep over a private folder of real SOLIDWORKS files.

Runs only when ``SOLIDSEAS_CORPUS_MANIFEST`` names a manifest CSV with at least
the columns ``path``, ``ext`` and ``format`` (``modern``, ``ole``, or anything
else for rows to skip, such as files held open by SOLIDWORKS). It reports
success rates per container format and per document type and never prints a
file name or path: failures are reported by manifest row number.

Optional settings:

* ``SOLIDSEAS_CORPUS_SAMPLE=N``: sweep ``random.Random(20260930).sample`` of N rows.
* ``SOLIDSEAS_CORPUS_WORKERS=N``: worker processes (default: up to 6).
* ``SOLIDSEAS_CORPUS_PARASOLID=0``: skip Parasolid extraction (the slowest step).
* ``SOLIDSEAS_CORPUS_MAX_MB``: Parasolid transmit cap in MiB (default 20).

Every opened document is also summarised with ``Document.summary()``, encoded
with the strict ``model.dumps`` and validated strictly against the
``document_summary`` schema; every warning must carry a known code.

``test_corpus_listing`` lists every folder that holds a manifest document with
``solidseas.scan`` (lazy reads, one held handle at a time), checks every entry
against a whole-file read of the same document, and measures the bytes the
listing read against the bytes of the files it listed (at most 5%).

``test_corpus_tessellate`` tessellates the active configuration of every part
(``solidseas.tessellate``), checks that nothing raises, that every mesh is finite
and counted consistently, and that on the parts that store no usable display
mesh at least 99.5% of the faces are done and 98% of the parts drawn.

``test_corpus_components`` builds the component tree (nested and flat) and the
references of every assembly and drawing, validates them strictly against
their schemas, checks the size limits with small caps too, and counts how many
direct virtual files map to a nested document that opens as the stored type
(at least 115 of 129 on the development corpus, the critique's floor).

``test_corpus_resolution`` resolves every assembly's and drawing's references in
three configurations: the default (the document's folder as the root, point
lookups outside it allowed), the corpus tree top with outside lookups allowed,
and the serve-like one (the tree top, nothing outside it). It asserts its
thresholds on a seeded holdout of a third of the documents, not on the
documents that chose the rules. ``SOLIDSEAS_CORPUS_TREE_DEPTH`` sets how many
path components name a tree top (default 5).

``test_corpus_bom`` builds the three bills of materials (top-level, parts only and
indented) of every assembly's active configuration, with the corpus tree top as the
one root and nothing looked up outside it (the service's rule), and checks that the
quantities add up to the component tree's instances in the BOM, that every row whose
file was not read says why, that only the sub-assemblies storing a document a row
needs are held open while the rest are read, and that the data passes its schema
strictly. It records the size and modification time of every file it opens and
checks them afterwards.

``test_corpus_path_report`` builds the path report of every document, validates
it strictly, and checks it against two independent collections: every path the
structured carriers hold (the component tree's ``swPath`` and
``swImportedPath``, ``Header2``'s reference paths and the folder at save, of the
document and of every nested document) must be in it, and so must every path the
0.1 ASCII scan finds in the document's own streams and in its nested documents.
The 0.1 scan cut a path at its first non-ASCII character and could run past the
end of a stored string into the bytes after it; those two differences are
counted, any other is a miss. Where a 0.1 hit lies in a stored string, the report
must hold that string's own path exactly, so a path that ran on past its string
in the report would be a miss too. It also counts the stored strings whose next bytes
read as letters (what a scan without the stored length would have appended) and the
paths the scan reads from counted 8-bit strings in a code page, and measures the time
per report.

``test_corpus_step`` exports ``random.Random(20261003).sample`` of 400 parts
(``SOLIDSEAS_CORPUS_STEP_SAMPLE=N`` for another size) to STEP in their active
configuration, each in a process of its own at below-normal priority, the file kept
in memory, and re-reads every file written with the tests' own Part 21 reader and
checker (``step_support``): syntax, topology, vertices on their curves and surfaces,
each face against SolidSeas' tessellation and each edge's arc. A part's export stops
at ``max_seconds`` (300 s) and its check at ``SOLIDSEAS_CORPUS_STEP_CHECK_SECONDS``
(default 600 s); both are counted, not failures. It prints the numbers
``docs/FORMAT.md`` 10.9 reports, checks that every part was written, refused with
reasons, stopped at a limit or had nothing to export, and, on the full sample, the
floors below.

``test_corpus_surfaces`` serves a seeded sample (120 parts, 60 assemblies and 20
drawings) with ``solidseas serve`` at below-normal priority, each document's
folder a root, and checks that Python, the CLI and the REST service give the same
envelope for every per-document kind, and the same preview bytes. The service
reads in its worker processes, lazily; Python and the CLI read each file whole.
It prints the time per route.
"""

import csv
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from jsonschema_subset import validate
from solidseas import model, scan
from solidseas.errors import WARNING_CODES, SolidSeasError
from solidseas.formats.solidworks import LockedFileError, open_document
from solidseas.formats.solidworks import container as container_mod

MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
pytestmark = pytest.mark.skipif(not MANIFEST, reason="SOLIDSEAS_CORPUS_MANIFEST is not set")
SEED = 20260930
EXT_TYPE = {".sldprt": "part", ".sldasm": "assembly", ".slddrw": "drawing"}


def _priority(cls: int) -> None:
    """Set this process's Windows priority class, and check that it took. Untyped ctypes
    calls pass the current-process handle as a 32-bit int, which Windows refuses, so a
    run would quietly stay at normal priority; this raises instead."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
    kernel32.GetPriorityClass.restype = ctypes.c_uint32
    me = kernel32.GetCurrentProcess()
    if not kernel32.SetPriorityClass(me, cls) or kernel32.GetPriorityClass(me) != cls:
        raise ctypes.WinError(ctypes.get_last_error())


def _lower_priority() -> None:
    _priority(0x4000)  # BELOW_NORMAL_PRIORITY_CLASS


def sweep_one(task: tuple[int, str, bool, int]) -> dict:
    row, path, do_parasolid, cap = task
    rec: dict = {"row": row}
    try:
        with open_document(path) as doc:
            rec.update(
                format=doc.format,
                doc_type=doc.doc_type,
                version=doc.saved_version.format_version,
                release_known=doc.saved_version.release is not None,
                has_preview=doc.preview() is not None,
                configurations=len(doc.configurations),
                properties=len(doc.properties),
                units=doc.units is not None,
                warnings=len(doc.warnings),
            )
            if doc.doc_type == "part" and do_parasolid:
                res = doc.parasolid(max_bytes=cap)
                rec["bodies"] = len(res.bodies)
                rec["bodies_valid"] = sum(1 for b in res.bodies if b.valid)
                rec["parasolid_capped"] = any("SldLimitError" in p.get("error", "") for p in res.problems)
                rec["parasolid_problems"] = len(res.problems)
            if doc.doc_type == "assembly":
                rec["references"] = len(doc.references())
            summary = doc.summary()
            text = model.dumps(model.envelope("document_summary", summary))
            rec["summary_bytes"] = len(text)
            rec["schema_errors"] = len(validate(summary, model.KINDS["document_summary"].schema, strict=True))
            rec["warning_codes"] = [w["code"] for w in summary["warnings"]]
            rec["preview_reason"] = summary["preview"]["reason"]
        rec["ok"] = True
    except LockedFileError:
        rec["locked"] = True
    except SolidSeasError as exc:
        rec["error"] = type(exc).__name__
    except Exception as exc:  # anything else is a bug: report it, do not hide it
        rec["unexpected"] = type(exc).__name__  # the type only: the text can quote a path
    return rec


def _rows() -> tuple[list[tuple[int, str, str, str]], int]:
    rows, skipped = [], 0
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):  # row 1 is the header
            if r.get("format") not in ("modern", "ole"):
                skipped += 1
                continue
            rows.append((i, r["path"], r["format"], (r.get("ext") or os.path.splitext(r["path"])[1]).lower()))
    sample = os.environ.get("SOLIDSEAS_CORPUS_SAMPLE")
    if sample:
        rows = sorted(random.Random(SEED).sample(rows, min(int(sample), len(rows))))
    return rows, skipped


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100.0 * a / b:.1f}%)" if b else "0/0"


def test_corpus_sweep(capsys):
    rows, skipped = _rows()
    assert rows, "the manifest lists no modern or ole rows"
    do_parasolid = os.environ.get("SOLIDSEAS_CORPUS_PARASOLID", "1") != "0"
    cap = int(float(os.environ.get("SOLIDSEAS_CORPUS_MAX_MB", "20")) * (1 << 20))
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    t0 = time.time()
    tasks = [(row, path, do_parasolid, cap) for row, path, _fmt, _ext in rows]
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        results = list(pool.map(sweep_one, tasks, chunksize=4))
    elapsed = time.time() - t0
    meta = {row: (fmt, ext) for row, _path, fmt, ext in rows}

    groups: dict[tuple[str, str], Counter] = defaultdict(Counter)
    failures: dict[str, list[int]] = defaultdict(list)
    for rec in results:
        fmt, ext = meta[rec["row"]]
        kind = EXT_TYPE.get(ext, ext)
        for key in ((fmt, "all"), ("all", kind), (fmt, kind), ("all", "all")):
            g = groups[key]
            g["files"] += 1
            if rec.get("locked"):
                g["locked"] += 1
                continue
            if not rec.get("ok"):
                g["failed"] += 1
                continue
            g["opened"] += 1
            g["format_matches_manifest"] += rec["format"] == fmt
            g["type_matches_extension"] += rec["doc_type"] == kind
            g["release_known"] += rec["release_known"]
            g["preview"] += rec["has_preview"]
            g["configurations"] += rec["configurations"] > 0
            g["properties"] += rec["properties"] > 0
            g["units"] += rec["units"]
            if "bodies" in rec:
                g["parasolid_attempted"] += 1
                g["parasolid_body"] += rec["bodies"] > 0
                g["parasolid_capped"] += rec["parasolid_capped"]
                g["bodies"] += rec["bodies"]
                g["bodies_valid"] += rec["bodies_valid"]
            if "references" in rec:
                g["assemblies"] += 1
                g["with_references"] += rec["references"] > 0
        if rec.get("error"):
            failures[rec["error"]].append(rec["row"])
        if rec.get("unexpected"):
            failures["unexpected: " + rec["unexpected"]].append(rec["row"])
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)

    sample = os.environ.get("SOLIDSEAS_CORPUS_SAMPLE")
    lines = [
        "",
        f"SolidSeas corpus sweep: {len(rows)} documents"
        + (f" (random.Random({SEED}).sample of {sample})" if sample else " (every modern and ole row)")
        + f", {skipped} manifest rows skipped, {workers} workers, {elapsed:.1f} s",
        f"Parasolid: {'on' if do_parasolid else 'off'}, cap {cap >> 20} MiB per transmit",
    ]
    for key in sorted(groups, key=lambda k: (k[0] != "all", k[0], k[1] != "all", k[1])):
        g = groups[key]
        n = g["files"] - g["locked"]
        parts = [
            f"{key[0]:>6} {key[1]:<8}",
            f"opened {_pct(g['opened'], n)}",
            f"preview {_pct(g['preview'], g['opened'])}",
            f"configurations {_pct(g['configurations'], g['opened'])}",
            f"custom props {_pct(g['properties'], g['opened'])}",
        ]
        if g["parasolid_attempted"]:
            parts.append(f"parasolid body {_pct(g['parasolid_body'], g['parasolid_attempted'])}")
            parts.append(f"capped {g['parasolid_capped']}")
            parts.append(f"valid bodies {_pct(g['bodies_valid'], g['bodies'])}")
        if g["assemblies"]:
            parts.append(f"with references {_pct(g['with_references'], g['assemblies'])}")
        if g["locked"]:
            parts.append(f"locked {g['locked']}")
        lines.append("  " + ", ".join(parts))
    for err, rws in sorted(failures.items()):
        lines.append(f"  failure {err}: {len(rws)} (manifest rows {rws[:20]})")
    opened = [rec for rec in results if rec.get("ok")]
    schema_errors = sum(rec["schema_errors"] for rec in opened)
    codes = Counter(code for rec in opened for code in rec["warning_codes"])
    unknown_codes = sorted(set(codes) - set(WARNING_CODES))
    reasons = Counter(rec["preview_reason"] for rec in opened)
    largest = max((rec["summary_bytes"] for rec in opened), default=0)
    lines.append(
        f"  summaries {len(opened)}, strict schema errors {schema_errors}, previews not stored "
        f"{reasons['not_stored']}, undecodable {reasons['undecodable']}, largest envelope {largest} bytes"
    )
    lines.append("  warning codes: " + (", ".join(f"{k} {v}" for k, v in sorted(codes.items())) or "none"))
    lines.append(f"  source files changed during the sweep: {len(changed)}")
    with capsys.disabled():
        print("\n".join(lines))

    total = groups[("all", "all")]
    assert not changed, f"source files changed during the sweep (manifest rows {changed[:20]})"
    assert not [k for k in failures if k.startswith("unexpected")], "non-SolidSeas exceptions escaped"
    assert total["opened"] == total["files"] - total["locked"], "some readable documents failed to open"
    assert total["format_matches_manifest"] == total["opened"]
    assert total["type_matches_extension"] == total["opened"]
    assert len(opened) == total["opened"] > 0
    assert schema_errors == 0, "a summary does not match the document_summary schema"
    assert not unknown_codes, f"warnings with codes missing from WARNING_CODES: {unknown_codes}"


# --------------------------------------------------------------------------- folder listing
LISTING_INCLUDE = ("properties", "configurations", "preview")
SHARED = ("file", "format", "doc_type", "saved_version", "active_configuration", "configurations", "warnings")


def _set_priority(below: bool) -> None:
    _priority(0x4000 if below else 0x20)  # below normal, or back to normal


def whole_read(task: tuple[int, str]) -> dict:
    """The fields a listing entry shares with the summary, from a whole-file read."""
    row, path = task
    try:
        with open_document(path) as doc:
            summary = doc.summary()
            props = model.build_properties(doc)["properties"]
        shared = {k: summary[k] for k in SHARED}
        return {"row": row, "shared": shared, "properties": props, "preview": summary["preview"]}
    except Exception as exc:
        return {"row": row, "error": type(exc).__name__}


class _Counted:
    """A source-file handle that counts the bytes read through it and how long it stays open."""

    def __init__(self, fh, log: dict) -> None:
        self._fh, self._log, self._t0 = fh, log, time.perf_counter()
        log["opened"] += 1

    def read(self, n=-1):
        data = self._fh.read(n)
        self._log["bytes"] += len(data)
        return data

    def close(self) -> None:
        if not self._fh.closed:
            self._log["held"].append(time.perf_counter() - self._t0)
        self._fh.close()

    def __getattr__(self, name):
        return getattr(self._fh, name)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def test_corpus_listing(capsys, monkeypatch):
    rows, _skipped = _rows()
    assert rows, "the manifest lists no modern or ole rows"
    by_key = {_key(path): row for row, path, _fmt, _ext in rows}
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    folders = sorted({os.path.dirname(_key(path)) for _row, path, _fmt, _ext in rows})
    log = {"opened": 0, "bytes": 0, "held": []}
    real = container_mod.open_readonly
    monkeypatch.setattr(container_mod, "open_readonly", lambda p, **kw: _Counted(real(p, **kw), log))

    entries: dict[str, dict] = {}
    raised: list[str] = []
    statuses: Counter = Counter()
    _set_priority(True)
    t0 = time.perf_counter()
    try:
        for folder in folders:
            try:
                for e in scan(folder, include=LISTING_INCLUDE):
                    statuses[e["status"]] += 1
                    if e["type"] == "file":
                        entries[_key(os.path.join(folder, e["path"]))] = e
            except Exception as exc:  # scan itself must never raise for a folder that exists
                raised.append(type(exc).__name__)
    finally:
        elapsed = time.perf_counter() - t0
        _set_priority(False)

    listed = {k: e for k, e in entries.items() if k in by_key}
    missing = sorted(by_key[k] for k in by_key if k not in entries)
    locked = [k for k, e in listed.items() if e["error"] and e["error"]["code"] == "locked"]
    failed = [by_key[k] for k, e in listed.items() if e["status"] != "ok" and k not in locked]
    internal = [e for e in entries.values() if e["error"] and e["error"]["code"] == "internal"]
    ok = {k: e for k, e in listed.items() if e["status"] == "ok"}
    previews = sum(1 for e in ok.values() if e["preview"]["available"])
    not_stored = sum(1 for e in ok.values() if e["preview"]["reason"] == "not_stored")
    read_files = [e for e in entries.values() if e["status"] == "ok"]
    total = sum(e["file"]["size"] for e in read_files)
    ratio = log["bytes"] / total if total else 1.0
    held = sorted(log["held"])

    # The same fields from a whole-file read of every listed manifest document.
    path_of = {row: path for row, path, _fmt, _ext in rows}
    tasks = [(by_key[k], path_of[by_key[k]]) for k in ok]
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        reference = {r["row"]: r for r in pool.map(whole_read, tasks, chunksize=8)}
    mismatched = []
    for k, e in ok.items():
        ref = reference[by_key[k]]
        same = "error" not in ref and all(e[f] == ref["shared"][f] for f in SHARED)
        same = same and e["properties"] == ref["properties"]
        same = same and {f: v for f, v in e["preview"].items() if f != "data_base64"} == ref["preview"]
        if not same:
            mismatched.append(by_key[k])
    reader_previews = sum(1 for r in reference.values() if "error" not in r and r["preview"]["available"])

    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)

    status_text = ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))
    with capsys.disabled():
        print(
            f"\nSolidSeas corpus listing: {len(folders)} folders, {sum(statuses.values())} entries "
            f"({status_text}) in {elapsed:.1f} s"
        )
        print(
            f"  manifest documents listed {len(listed)}/{len(rows)}, ok {len(ok)}, locked {len(locked)}, "
            f"previews {previews}, not stored {not_stored}, whole-read previews {reader_previews}, "
            f"entries differing from a whole read {len(mismatched)}"
        )
        print(
            f"  bytes read {log['bytes']} of {total} in {len(read_files)} documents read "
            f"({100.0 * ratio:.2f}%), {log['opened']} handles opened"
        )
        if held:
            print(
                f"  handle held open: p50 {1000 * held[len(held) // 2]:.1f} ms, "
                f"p99 {1000 * held[int(len(held) * 0.99)]:.1f} ms, max {1000 * held[-1]:.1f} ms"
            )
        print(f"  source files changed during the listing: {len(changed)}")

    assert len(entries) >= len(listed) > 0 and len(ok) > 0.9 * len(rows), "the listing found too little"
    assert not raised, f"scan raised: {raised}"
    assert not missing, f"manifest rows not listed: {missing[:20]}"
    assert not failed, f"manifest rows that did not list ok: {failed[:20]}"
    assert not internal, "an entry hit an unexpected error"
    assert not mismatched, f"entries that differ from a whole read: {mismatched[:20]}"
    assert previews == reader_previews > 0 and previews + not_stored == len(ok)
    assert ratio <= 0.05, f"the listing read {100.0 * ratio:.2f}% of the bytes"
    assert len(held) == log["opened"] >= len(read_files), "a handle was left open"
    assert not changed, f"source files changed during the listing (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- component trees
SMALL_NODES, SMALL_DEPTH = 50, 2
VIRTUAL_FLOOR = (115, 129)  # mapped of direct virtual files, as a ratio


def _strict_errors(kind: str, data: dict) -> int:
    return len(validate(data, model.KINDS[kind].schema, strict=True))


def component_one(task: tuple[int, str]) -> dict:
    row, path = task
    rec: dict = {"row": row}
    try:
        with open_document(path) as doc:
            rec["doc_type"] = doc.doc_type
            if doc.doc_type == "assembly":
                t0 = time.perf_counter()
                comps = model.build_components(doc)
                flat = model.build_components(doc, flat=True)
                refs = model.build_references(doc)
                small = doc.components(max_nodes=SMALL_NODES, max_depth=SMALL_DEPTH)
                rec["seconds"] = time.perf_counter() - t0
                rec["schema_errors"] = (
                    _strict_errors("components", comps)
                    + _strict_errors("components", flat)
                    + _strict_errors("references", refs)
                )
                model.dumps(model.envelope("components", comps))
                model.dumps(model.envelope("references", refs))
                n, depth = comps["counts"]["nodes"], comps["counts"]["depth"]
                lim = comps["limits"]
                rec.update(state=comps["children_state"], nodes=n, depth=depth, truncated=comps["truncated"])
                over = n > SMALL_NODES or depth > SMALL_DEPTH
                rec["caps_ok"] = (
                    n <= lim["max_nodes"]
                    and depth <= lim["max_depth"]
                    and small.node_count <= SMALL_NODES
                    and small.depth <= SMALL_DEPTH
                    and (comps["truncated"] or small.truncated == over)
                )
                ids, stack = [], list(reversed(comps["children"]))
                while stack:
                    node = stack.pop()
                    ids.append(node["id"])
                    stack.extend(reversed(node["children"]))
                rec["flat_ok"] = [x["id"] for x in flat["instances"]] == ids and len(ids) == n
                rec["ids_unique"] = len(set(ids)) == len(ids)
                files = refs["files"]
                rec["files"] = len(files)
                rec["configurations"] = len(refs["configurations_described"])
                direct_v = [f for f in files if f["virtual"] and f["direct"]]
                rec["virtual_direct"] = len(direct_v)
                rec["virtual_indirect"] = sum(1 for f in files if f["embedded"] == "embedded_in_subassembly")
                mapped = [f for f in direct_v if f["nested"]]
                rec["virtual_mapped"] = len(mapped)
                rec["virtual_opens_as_type"] = sum(
                    1 for f in mapped if doc.nested(f["nested"]).doc_type == f["doc_type"]
                )
                imported = [f for f in files if f["imported"]]
                rec["imported"] = len(imported)
                rec["imported_embedded"] = sum(1 for f in imported if f["embedded"] == "embedded")
                nodes = flat["instances"]
                rec["placement_null"] = sum(1 for x in nodes if x["placement"] is None)
                rec["hidden"] = sum(1 for x in nodes if x["hidden"])
                rec["suppressed_hidden"] = sum(1 for x in nodes if x["hidden"] and x["suppressed"])
                rec["nested_suppressed_hidden"] = sum(
                    1 for x in nodes if x["hidden"] and x["suppressed"] and x["depth"] > 1
                )
                # the same count from the stored attributes: the top-level suppressed instances
                # whose configuration's display state says No (swShowState)
                tree = doc.metadata.tree or {}
                cfg = next((c for c in tree.get("configs", []) if c["name"] == comps["configuration"]), None)
                shown = (cfg or {}).get("display_state") or {}
                rec["suppressed_shown_no"] = sum(
                    1
                    for r in tree.get("refs", [])
                    if cfg is not None
                    and r["parent_model"] == cfg["model_ref"]
                    and r["suppressed"]
                    and shown.get(r["sw_id"]) == "No"
                )
                rec["warning_codes"] = [w["code"] for w in comps["warnings"] + refs["warnings"]]
            elif doc.doc_type == "drawing":
                refs = model.build_references(doc)
                rec["schema_errors"] = _strict_errors("references", refs)
                views = [v for sh in refs["sheets"] for v in sh["views"]]
                rec.update(
                    files=len(refs["files"]),
                    sheets=len(refs["sheets"]),
                    views=len(views),
                    views_with_file=sum(1 for v in views if v["file"]),
                    active_none=doc.active_configuration is None,
                    warning_codes=[w["code"] for w in refs["warnings"]],
                )
        rec["ok"] = True
    except LockedFileError:
        rec["locked"] = True
    except SolidSeasError as exc:
        rec["error"] = type(exc).__name__
    except Exception as exc:  # anything else is a bug: report its type only
        rec["unexpected"] = type(exc).__name__
    return rec


def test_corpus_components(capsys):
    rows, _skipped = _rows()
    rows = [r for r in rows if r[3] in (".sldasm", ".slddrw")]
    assert rows, "the manifest lists no assemblies or drawings"
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        results = list(pool.map(component_one, [(row, path) for row, path, _f, _e in rows], chunksize=2))
    elapsed = time.time() - t0
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)

    asm = [r for r in results if r.get("ok") and r["doc_type"] == "assembly"]
    drw = [r for r in results if r.get("ok") and r["doc_type"] == "drawing"]
    failed = [r["row"] for r in results if not r.get("ok") and not r.get("locked")]
    unexpected = [r["row"] for r in results if r.get("unexpected")]
    trees = sum(1 for r in asm if r["state"] == "described")
    no_tree = sum(1 for r in asm if r["state"] == "unknown")

    def total(key: str, group: list[dict]) -> int:
        return sum(r.get(key, 0) for r in group)

    direct, mapped = total("virtual_direct", asm), total("virtual_mapped", asm)
    codes = Counter(c for r in asm + drw for c in r["warning_codes"])
    slowest = max((r["seconds"] for r in asm), default=0.0)
    with capsys.disabled():
        print(
            f"\nSolidSeas corpus components: {len(asm)} assemblies ({trees} with a component tree, "
            f"{no_tree} without), {len(drw)} drawings, {len(failed)} failed, {elapsed:.1f} s, "
            f"slowest assembly {1000 * slowest:.0f} ms"
        )
        print(
            f"  instances {total('nodes', asm)} (largest {max((r['nodes'] for r in asm), default=0)}, "
            f"deepest {max((r['depth'] for r in asm), default=0)} levels), truncated "
            f"{sum(1 for r in asm if r['truncated'])}, referenced files {total('files', asm)}, "
            f"assemblies with several configurations {sum(1 for r in asm if r['configurations'] > 1)}"
        )
        print(
            f"  direct virtual files {direct}, mapped to a nested document {mapped}, opening as the "
            f"stored type {total('virtual_opens_as_type', asm)}; virtual inside sub-assemblies "
            f"{total('virtual_indirect', asm)}; imported files {total('imported', asm)}, embedded "
            f"{total('imported_embedded', asm)}"
        )
        print(
            f"  hidden instances {total('hidden', asm)} (suppressed and hidden "
            f"{total('suppressed_hidden', asm)}), placements null {total('placement_null', asm)}"
        )
        print(
            f"  drawings: sheets {total('sheets', drw)}, views {total('views', drw)}, views naming a "
            f"referenced model {total('views_with_file', drw)}, models {total('files', drw)}"
        )
        print("  warning codes: " + (", ".join(f"{k} {v}" for k, v in sorted(codes.items())) or "none"))
        print(f"  source files changed: {len(changed)}")

    assert len(asm) > 0 and trees + no_tree == len(asm), "the sweep found no assemblies"
    assert not unexpected, f"non-SolidSeas exceptions (manifest rows {unexpected[:20]})"
    assert not failed, f"assemblies or drawings that failed (manifest rows {failed[:20]})"
    assert total("schema_errors", asm + drw) == 0, "a components or references document breaks its schema"
    assert all(r["caps_ok"] for r in asm), "a tree broke its limits"
    assert all(r["flat_ok"] and r["ids_unique"] for r in asm), "the flat form or the ids disagree"
    assert direct > 0 and mapped * VIRTUAL_FLOOR[1] >= VIRTUAL_FLOOR[0] * direct, (mapped, direct)
    assert total("virtual_opens_as_type", asm) == mapped, "a mapped nested document is not the stored type"
    # a suppressed instance is hidden only where its configuration's display state says so, and
    # display states list top-level instances only (docs/FORMAT.md 12.1)
    assert total("nested_suppressed_hidden", asm) == 0
    assert total("suppressed_hidden", asm) == total("suppressed_shown_no", asm)
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert total("hidden", asm) > 0 and total("suppressed_shown_no", asm) > 0, "nothing was compared"
    assert all(r["active_none"] for r in drw), "a drawing reports an active configuration"
    assert total("views_with_file", drw) == total("views", drw), "a drawing view names no referenced model"
    assert set(codes) <= set(WARNING_CODES)
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- display geometry
# Part instances to show that display_geometry places, as a fraction: 96.0% on the 325
# readable assemblies of the development corpus (6,508 of 6,779; 80.7%, 5,473, from the
# stored meshes alone, without the brep source), with room for drift.
GEOMETRY_PLACED_MIN = 0.75


def geometry_one(task: tuple[int, str]) -> dict:
    """``display_geometry`` of one assembly, with its own folder as the root, at the
    default limits and at small ones; numbers and codes only."""
    import math

    from solidseas.formats.solidworks import facetess
    from solidseas.geometry import display_geometry

    row, path = task
    rec: dict = {"row": row}
    try:
        with open_document(path, hold_open=True) as doc:
            rec["doc_type"] = doc.doc_type
            if doc.doc_type != "assembly":
                rec["ok"] = True
                return rec
            has_directory = facetess.DIRECTORY in doc.container
            rec["directory_unreadable"] = has_directory and facetess.read_directory(doc.container) is None
            roots = {"folder": os.path.dirname(os.path.abspath(path))}
            t0 = time.perf_counter()
            g = display_geometry(doc, roots=roots)
            rec["seconds"] = time.perf_counter() - t0
            c = g.counts
            rec.update({k: c[k] for k in ("parts", "placed", "suppressed", "hidden", "skipped")})
            rec["counts_add_up"] = c["placed"] + c["skipped"] + c["suppressed"] + c["hidden"] == c["parts"]
            rec["placements_finite"] = all(all(math.isfinite(v) for v in i.matrix()) for i in g.instances)
            rec["meshes_ok"] = all(i.mesh in g.meshes and g.meshes[i.mesh].triangles > 0 for i in g.instances)
            rec["reasons"] = [s.reason for s in g.skipped]
            rec["placeholders"] = sum(1 for s in g.skipped if g.placeholder(s) is not None)
            rec["nested_placed"] = sum(1 for i in g.instances if "/" in i.id)
            rec["nested_shown"] = rec["nested_placed"] + sum(1 for s in g.skipped if "/" in s.id)
            rec["kinds"] = [m.kind for m in g.meshes.values()]
            rec["triangles_read"] = c["triangles_read"]
            small = display_geometry(doc, roots=roots, max_triangles=1_000, max_files=1, max_bytes=1 << 20)
            sc = small.counts
            rec["small_ok"] = (
                sc["triangles_read"] <= 1_000
                and sc["files_opened"] <= 1
                and sc["bytes_read"] <= 1 << 20
                and sc["placed"] + sc["skipped"] + sc["suppressed"] + sc["hidden"] == sc["parts"]
            )
        rec["ok"] = True
    except LockedFileError:
        rec["locked"] = True
    except SolidSeasError as exc:
        rec["error"] = type(exc).__name__
    except Exception as exc:  # anything else is a bug: report it, do not hide it
        rec["unexpected"] = type(exc).__name__  # the type only: the text can quote a path
    return rec


def test_corpus_display_geometry(capsys):
    rows, _skipped = _rows()
    rows = [r for r in rows if r[3] == ".sldasm"]
    assert rows, "the manifest lists no assemblies"
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        results = list(pool.map(geometry_one, [(row, path) for row, path, _f, _e in rows], chunksize=2))
    elapsed = time.time() - t0
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)
    asm = [r for r in results if r.get("ok") and r["doc_type"] == "assembly"]
    failed = [r["row"] for r in results if not r.get("ok") and not r.get("locked")]
    unexpected = [r["row"] for r in results if r.get("unexpected")]
    shown = sum(r["parts"] - r["suppressed"] - r["hidden"] for r in asm)
    placed = sum(r["placed"] for r in asm)
    reasons = Counter(x for r in asm for x in r["reasons"])
    kinds = Counter(x for r in asm for x in r["kinds"])
    slowest = max((r["seconds"] for r in asm), default=0.0)
    with capsys.disabled():
        print(
            f"\nSolidSeas corpus display geometry: {len(asm)} assemblies, {len(failed)} failed, "
            f"{elapsed:.1f} s, slowest {slowest:.2f} s"
        )
        print(
            f"  part instances to show {shown}, placed {_pct(placed, shown)}, every one in "
            f"{sum(1 for r in asm if r['skipped'] == 0)} assemblies, none in "
            f"{sum(1 for r in asm if r['placed'] == 0 and r['skipped'])}"
        )
        print("  not placed: " + (", ".join(f"{k} {v}" for k, v in sorted(reasons.items())) or "none"))
        print(
            f"  inside sub-assemblies placed {sum(r['nested_placed'] for r in asm)} of "
            f"{sum(r['nested_shown'] for r in asm)}; not placed with a placeholder box "
            f"{sum(r['placeholders'] for r in asm)} of {sum(r['skipped'] for r in asm)}"
        )
        print("  meshes from: " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "none"))
        print(f"  most triangles read {max((r['triangles_read'] for r in asm), default=0)}")
        print(f"  source files changed: {len(changed)}")
    assert not unexpected, f"non-SolidSeas exceptions (manifest rows {unexpected[:20]})"
    assert not failed, f"assemblies that failed (manifest rows {failed[:20]})"
    unparsed = [r["row"] for r in asm if r["directory_unreadable"]]
    assert not unparsed, f"FaceTessellations directories that did not parse (manifest rows {unparsed[:20]})"
    assert all(r["counts_add_up"] and r["small_ok"] for r in asm), "counts or limits do not hold"
    assert all(r["placements_finite"] and r["meshes_ok"] for r in asm), "a placed instance has no usable mesh"
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert placed >= GEOMETRY_PLACED_MIN * shown, (placed, shown)
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- tessellation
# Floors for solidseas.tessellate on the parts that store no usable display mesh (the
# parts the brep mesh source draws), set from the development corpus's own measurement
# with room for drift (docs/API.md 3.15).
TESSELLATE_FACES_MIN = 0.995
TESSELLATE_DRAWN_MIN = 0.98


def tessellate_one(task: tuple[int, str]) -> dict:
    """The active configuration of one part tessellated; numbers and codes only."""
    import math

    from solidseas.tessellate import tessellate_document

    row, path = task
    rec: dict = {"row": row}
    try:
        with open_document(path) as doc:
            rec["doc_type"] = doc.doc_type
            if doc.doc_type != "part":
                rec["ok"] = True
                return rec
            stored = doc.mesh()
            rec["has_mesh"] = stored is not None and stored.n_triangles > 0
            t0 = time.perf_counter()
            t = tessellate_document(doc)
            rec["seconds"] = time.perf_counter() - t0
            rec.update({k: t.counts[k] for k in ("bodies", "faces", "faces_done", "triangles")})
            rec["reasons"] = dict(t.reasons)
            rec["closed"] = t.closed
            rec["truncated"] = list(t.truncated)
            rec["finite"] = all(math.isfinite(x) for x in t.mesh.positions)
            rec["consistent"] = t.mesh.n_triangles == t.counts["triangles"] and len(t.mesh.faces) == len(
                t.face_ids
            )
            rec["codes"] = [w.code for w in t.warnings]
        rec["ok"] = True
    except LockedFileError:
        rec["locked"] = True
    except SolidSeasError as exc:
        rec["error"] = type(exc).__name__
    except Exception as exc:  # anything else is a bug: report it, do not hide it
        rec["unexpected"] = type(exc).__name__
    return rec


def test_corpus_tessellate(capsys):
    rows, _skipped = _rows()
    rows = [r for r in rows if r[3] == ".sldprt"]
    assert rows, "the manifest lists no parts"
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        results = list(pool.map(tessellate_one, [(row, path) for row, path, _f, _e in rows], chunksize=2))
    elapsed = time.time() - t0
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)
    parts = [r for r in results if r.get("ok") and r["doc_type"] == "part"]
    unexpected = [r["row"] for r in results if r.get("unexpected")]
    failed = [r["row"] for r in results if not r.get("ok") and not r.get("locked")]
    bare = [r for r in parts if not r["has_mesh"] and r["bodies"]]
    faces = sum(r["faces"] for r in bare)
    done = sum(r["faces_done"] for r in bare)
    drawn = sum(1 for r in bare if r["triangles"])
    reasons = Counter()
    for r in parts:
        reasons.update(r["reasons"])
    times = sorted(r["seconds"] for r in bare)
    solids = [r["closed"] for r in bare if r["closed"] is not None]
    with capsys.disabled():
        print(f"\nSolidSeas corpus tessellation: {len(parts)} parts, {len(failed)} failed, {elapsed:.1f} s")
        print(
            f"  without a display mesh, with bodies: {len(bare)}; drawn {_pct(drawn, len(bare))}; "
            f"faces done {_pct(done, faces)}; every solid closed in {_pct(sum(solids), len(solids))}"
        )
        if times:
            print(f"  seconds a part: median {times[len(times) // 2]:.3f}, worst {times[-1]:.2f}")
        print("  faces not done: " + (", ".join(f"{k} {v}" for k, v in sorted(reasons.items())) or "none"))
        print(f"  source files changed: {len(changed)}")
    assert not unexpected, f"non-SolidSeas exceptions (manifest rows {unexpected[:20]})"
    assert not failed, f"parts that failed (manifest rows {failed[:20]})"
    assert all(r["finite"] and r["consistent"] for r in parts), "a mesh holds a bad value or miscounts"
    assert set(c for r in parts for c in r["codes"]) <= {
        "no_stored_bodies",
        "configuration_assumed",
        "bodies_unreadable",
    }
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert done >= TESSELLATE_FACES_MIN * faces, (done, faces)
        assert drawn >= TESSELLATE_DRAWN_MIN * len(bare), (drawn, len(bare))
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- reference resolution
RESOLVE_SEED = 20261001
# Path components (the drive included) that name a corpus tree top: the root of the
# serve-like configuration. A document with fewer components uses its own folder.
TREE_DEPTH = int(os.environ.get("SOLIDSEAS_CORPUS_TREE_DEPTH", "5"))
RESOLVE_CONFIGS = ("default", "tree_top", "serve_like")
# Floors and ceilings for the direct references of the seeded holdout, as fractions. They
# were set from that holdout's own measurement on the development corpus (docs/API.md
# 3.10: found with an identity match 73.2% in the default configuration and 73.1% in the
# serve-like one, ambiguous 0% and 0.06%, missing 26.2% in both, identity differing in 0
# and 1 of 1,553), with room for drift; the tuning set that chose the rules is not used.
RESOLVE_LIMITS = {
    "default": {"found_match_min": 0.70, "ambiguous_max": 0.01, "differ_max": 0.03, "missing_max": 0.30},
    "serve_like": {"found_match_min": 0.70, "ambiguous_max": 0.01, "differ_max": 0.03, "missing_max": 0.30},
}


def _tree_top(path: str) -> tuple[str, bool]:
    parts = Path(path).parts
    if len(parts) > TREE_DEPTH:
        return str(Path(*parts[:TREE_DEPTH])), True
    return os.path.dirname(path), False


def resolution_sweep(docs: list[tuple[int, str, bool]]) -> dict:
    """Resolve every document in three configurations; numbers and codes only."""
    from solidseas.resolve import Gateway, IndexCache, resolve_references
    from solidseas.roots import Root, Roots

    cache = IndexCache()
    out: dict = {"records": [], "documents": 0, "errors": Counter(), "schema_errors": 0}
    out.update(unc_refused=0, unc_touched=0)
    for _row, path, hold in docs:
        try:
            doc = open_document(path)
        except Exception as exc:  # report the type, never the text: it can quote a path
            out["errors"][type(exc).__name__] += 1
            continue
        out["documents"] += 1
        with doc:
            top, recursive = _tree_top(path)
            files = {f.key: f for f in doc.reference_set().files.values()}
            for cfg in RESOLVE_CONFIGS:
                roots = None if cfg == "default" else Roots([Root("corpus", top, recursive)])
                gw = Gateway(allow_outside_roots=cfg != "serve_like")
                try:
                    res = resolve_references(doc, roots, cache=cache, gateway=gw, max_seconds=60.0)
                except Exception as exc:
                    out["errors"][f"{cfg}:{type(exc).__name__}"] += 1
                    continue
                for op, p, outcome in gw.calls:
                    if op in ("point", "identity") and p.startswith("\\\\"):
                        out["unc_refused" if outcome.startswith("refused:") else "unc_touched"] += 1
                if cfg == "default":
                    data = model.build_references(doc, resolution=res)
                    out["schema_errors"] += _strict_errors("references", data)
                    model.dumps(model.envelope("references", data))
                for key, r in res.results.items():
                    f = files[key]
                    group = "drawing" if doc.doc_type == "drawing" else ("direct" if f.direct else "indirect")
                    mismatch = any(w.code == "identity_mismatch" for w in r.warnings)
                    out["records"].append(
                        (hold, cfg, group, f.virtual, r.status, r.identity, r.rule, r.confidence, mismatch)
                    )
    return out


def _resolution_rates(sel: list[tuple]) -> dict[str, float]:
    n = len(sel) or 1
    found = [r for r in sel if r[4] in ("resolved", "moved")]
    out = {
        s: sum(1 for r in sel if r[4] == s) / n
        for s in ("resolved", "moved", "embedded", "ambiguous", "missing")
    }
    out["n"] = len(sel)
    out["found_match"] = sum(1 for r in found if r[5] == "match") / n
    out["differ"] = sum(1 for r in found if r[5] == "differ") / n
    return out


def test_corpus_resolution(capsys):
    rows, _skipped = _rows()
    docs = sorted((row, path) for row, path, _f, ext in rows if ext in (".sldasm", ".slddrw"))
    asm = [d for d in docs if d[1].lower().endswith(".sldasm")]
    drw = [d for d in docs if d[1].lower().endswith(".slddrw")]
    assert asm, "the manifest lists no assemblies"
    rng = random.Random(RESOLVE_SEED)
    hold = {row for row, _ in rng.sample(asm, len(asm) // 3)} | {
        row for row, _ in rng.sample(drw, len(drw) // 3)
    }
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=1, initializer=_lower_priority) as pool:
        out = pool.submit(resolution_sweep, [(row, path, row in hold) for row, path in docs]).result()
    elapsed = time.time() - t0
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)

    recs = out["records"]

    def select(cfg: str, group: str, part: str) -> list[tuple]:
        wanted = part == "holdout"
        return [
            r
            for r in recs
            if r[1] == cfg and r[2] == group and not r[3] and (part == "all" or r[0] == wanted)
        ]

    table = {
        (cfg, part): _resolution_rates(select(cfg, "direct", part))
        for cfg in RESOLVE_CONFIGS
        for part in ("all", "holdout")
    }
    with capsys.disabled():
        print(
            f"\nSolidSeas corpus resolution: {out['documents']} documents ({len(hold)} in the holdout), "
            f"{elapsed:.1f} s, errors {dict(out['errors']) or 0}, schema errors {out['schema_errors']}"
        )
        for (cfg, part), r in table.items():
            print(
                f"  {cfg:<10} {part:<7} direct {r['n']}: resolved {100 * r['resolved']:.2f}%, moved "
                f"{100 * r['moved']:.2f}%, embedded {100 * r['embedded']:.2f}%, ambiguous "
                f"{100 * r['ambiguous']:.2f}%, missing {100 * r['missing']:.2f}%; found with an identity "
                f"match {100 * r['found_match']:.2f}%, identity differs {100 * r['differ']:.2f}%"
            )
        for group in ("indirect", "drawing"):
            r = _resolution_rates(select("tree_top", group, "all"))
            print(
                f"  tree_top   all     {group} {r['n']}: found with an identity match "
                f"{100 * r['found_match']:.2f}%, embedded {100 * r['embedded']:.2f}%, missing "
                f"{100 * r['missing']:.2f}%"
            )
        virtual = Counter(r[4] for r in recs if r[1] == "default" and r[3])
        conf = Counter(r[7] for r in recs if r[1] == "default" and r[2] == "direct" and not r[3])
        print(f"  virtual files (default): {dict(virtual)}; confidence, direct (default): {dict(conf)}")
        print(
            f"  UNC paths refused {out['unc_refused']}, touched {out['unc_touched']}; "
            f"source files changed {len(changed)}"
        )

    # the sweep's own size first: a sweep that found nothing would pass everything below
    direct = len(select("default", "direct", "all"))
    assert out["documents"] >= 0.9 * len(docs) > 0, "too few documents opened"
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert out["documents"] >= 300 and direct >= 3000, (out["documents"], direct)
    assert table[("default", "holdout")]["n"] >= 0.2 * direct, "the holdout is too small"
    assert not out["errors"] and out["schema_errors"] == 0
    for cfg, limits in RESOLVE_LIMITS.items():
        r = table[(cfg, "holdout")]
        assert r["found_match"] >= limits["found_match_min"], (cfg, r)
        assert r["ambiguous"] <= limits["ambiguous_max"], (cfg, r)
        assert r["differ"] <= limits["differ_max"], (cfg, r)
        assert r["missing"] <= limits["missing_max"], (cfg, r)
    # a file kept although its identity differs is only ever the low-confidence fallback
    differ = [r for r in recs if r[4] in ("resolved", "moved") and r[5] == "differ"]
    assert differ, "no reference fell back on a file whose identity differs: the veto went untested"
    assert all(r[7] == "low" and r[8] for r in differ), "a differing file was chosen as if it matched"
    assert out["unc_touched"] == 0, "a stored UNC path reached the filesystem"
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert out["unc_refused"] > 0, "no stored UNC path reached the gateway: the check above saw nothing"
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- bills of materials
def _bom_leaves(nodes, out: list) -> list:
    """In-BOM instances with no listed components under them, found independently of
    solidseas.bom."""
    for c in nodes:
        if c.suppressed or c.excluded_from_bom:
            continue
        if c.children:
            _bom_leaves(c.children, out)
        else:
            out.append(c)
    return out


def bom_sweep(docs: list[tuple[int, str]]) -> dict:
    """Every assembly's three BOMs, numbers and codes only, with the corpus tree top as
    the root and no lookups outside it. Every file opened is recorded with its size and
    modification time before it is opened."""
    from solidseas import bom as bom_mod
    from solidseas.resolve import IndexCache
    from solidseas.roots import Root, Roots

    cache = IndexCache()
    opened: dict[str, tuple[int, int] | None] = {}
    held: list = []  # the documents open now
    most = [0]

    def opener(path: str, within: str):
        if path not in opened:
            try:
                st = os.stat(path)
                opened[path] = (st.st_size, st.st_mtime_ns)
            except OSError:
                opened[path] = None
        d = open_document(path, within=within, hold_open=True)
        close = d.close

        def closing():
            if d in held:
                held.remove(d)
            close()

        d.close = closing
        held.append(d)
        most[0] = max(most[0], len(held))
        return d

    out: dict = {"records": [], "errors": Counter(), "opened": opened}
    for row, path in docs:
        rec: dict = {"row": row}
        try:
            with open_document(path) as doc:
                if doc.doc_type != "assembly":
                    continue
                top, recursive = _tree_top(path)
                roots = Roots([Root("corpus", top, recursive)])
                tree = doc.components()
                t0 = time.perf_counter()
                most[0] = 0
                boms = bom_mod.build_boms(
                    doc, roots=roots, allow_outside_roots=False, cache=cache, opener=opener
                )
                rec["seconds"] = time.perf_counter() - t0
                rec["most_open"], rec["left_open"] = most[0], len(held)
                # The sub-assemblies a document stored inside is read from, found or not: each
                # stored document's parent instance's file (one per chain of virtual ones).
                by_id = {n.id: n for n in tree.walk()}
                hosts = {
                    by_id[by_id[i].parent].file
                    for r in boms["indented"].rows
                    if r.file in tree.files and tree.files[r.file].embedded_in_subassembly
                    for i in r.instances
                    if by_id[i].parent is not None
                }
                rec["hosts"] = len(hosts)
                rec["alternate_rows"] = Counter(
                    t for t, b in boms.items() for r in b.rows if r.alternate_name is not None
                )
                in_bom = {k: f.instances_in_bom for k, f in tree.files.items() if f.instances_in_bom}
                totals: Counter = Counter()
                for r in boms["indented"].rows:
                    totals[r.file] += r.total_quantity
                parts: Counter = Counter()
                for r in boms["parts"].rows:
                    parts[r.file] += r.quantity
                top_count = sum(1 for n in tree.children if not n.suppressed and not n.excluded_from_bom)
                rec["indented_adds_up"] = dict(totals) == in_bom
                # Every leaf is in one parts row, but a sub-assembly the tree lists nothing under
                # whose own file lists nothing either: an empty assembly is no part.
                leaves = _bom_leaves(tree.children, [])
                in_rows = [i for r in boms["parts"].rows for i in r.instances]
                dropped = [n for n in leaves if n.id not in set(in_rows)]
                rec["empty_subassemblies"] = len(dropped)
                rec["parts_adds_up"] = (
                    sum(parts.values()) == len(in_rows) == len(set(in_rows)) == len(leaves) - len(dropped)
                    and all(n.doc_type == "assembly" and n.children_state == "described" for n in dropped)
                    and all(parts[k] == v for k, v in in_bom.items() if tree.files[k].doc_type == "part")
                )
                rec["top_adds_up"] = sum(r.quantity for r in boms["top"].rows) == top_count
                rec["instances_in_bom"] = sum(in_bom.values())
                rec["schema_errors"] = sum(_strict_errors("bom", model.bom_data(b)) for b in boms.values())
                ind = boms["indented"]
                rec["rows"] = {t: len(b.rows) for t, b in boms.items()}
                rec["unread"] = ind.counts["unread"]
                rec["unread_without_note"] = sum(
                    1
                    for b in boms.values()
                    for r in b.rows
                    if r.properties is None and not any(n.code == "bom_properties_unread" for n in r.notes)
                )
                rec["notes"] = Counter(n.code for r in ind.rows for n in r.notes)
                rec["resolution"] = Counter(r.resolution or "none" for r in ind.rows)
                rec["complete"] = ind.complete
                rec["truncated"] = ind.truncated
                rec["described"] = tree.children_state == "described"
                rec["files_opened"] = ind.counts["files_opened"]
                rec["with_description"] = sum(1 for r in ind.rows if r.description)
                out["records"].append(rec)
        except Exception as exc:  # report the type, never the text: it can quote a path
            out["errors"][type(exc).__name__] += 1
    return out


def _stat_or_none(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def test_corpus_bom(capsys):
    rows, _skipped = _rows()
    docs = sorted((row, path) for row, path, _f, ext in rows if ext == ".sldasm")
    assert docs, "the manifest lists no assemblies"
    before = {row: _stat_or_none(path) for row, path, _fmt, _ext in rows}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=1, initializer=_lower_priority) as pool:
        out = pool.submit(bom_sweep, docs).result()
    elapsed = time.time() - t0
    changed = [row for row, path, _fmt, _ext in rows if _stat_or_none(path) != before[row]]
    opened_changed = sum(1 for path, was in out["opened"].items() if _stat_or_none(path) != was)
    recs = out["records"]
    seconds = sorted(r["seconds"] for r in recs) or [0.0]
    notes: Counter = Counter()
    status: Counter = Counter()
    for r in recs:
        notes.update(r["notes"])
        status.update(r["resolution"])
    rows_total = {t: sum(r["rows"][t] for r in recs) for t in ("top", "parts", "indented")}
    unread = sum(r["unread"] for r in recs)
    with capsys.disabled():
        print(
            f"\nSolidSeas corpus BOM: {len(recs)} assemblies, {elapsed:.1f} s, errors "
            f"{dict(out['errors']) or 0}, per assembly median {seconds[len(seconds) // 2]:.3f} s, "
            f"slowest {seconds[-1]:.2f} s"
        )
        print(
            f"  rows: top {rows_total['top']}, parts {rows_total['parts']}, indented "
            f"{rows_total['indented']}; instances in the BOM {sum(r['instances_in_bom'] for r in recs)}"
        )
        print(
            "  quantities add up: indented "
            f"{sum(r['indented_adds_up'] for r in recs)}, parts {sum(r['parts_adds_up'] for r in recs)}, "
            f"top {sum(r['top_adds_up'] for r in recs)} of {len(recs)}"
        )
        print(
            f"  indented rows read {rows_total['indented'] - unread}, unread {unread} (without a note: "
            f"{sum(r['unread_without_note'] for r in recs)}); with a description "
            f"{sum(r['with_description'] for r in recs)}"
        )
        print(
            f"  row files: {dict(sorted(status.items()))}; empty sub-assemblies left out of parts only "
            f"{sum(r['empty_subassemblies'] for r in recs)}"
        )
        print(f"  notes: {dict(sorted(notes.items())) or 0}")
        print(
            f"  complete {sum(r['complete'] for r in recs)}, truncated {sum(r['truncated'] for r in recs)}, "
            f"without a tree {sum(not r['described'] for r in recs)}; schema errors "
            f"{sum(r['schema_errors'] for r in recs)}"
        )
        print(
            f"  open at once at most {max((r['most_open'] for r in recs), default=0)} (an assembly's "
            f"hosts of stored documents at most {max((r['hosts'] for r in recs), default=0)}), left open "
            f"{sum(r['left_open'] for r in recs)}; rows with an alternate name "
            f"{dict(sum((r['alternate_rows'] for r in recs), Counter())) or 0}"
        )
        print(
            f"  files opened {len(out['opened'])} (changed {opened_changed}); "
            f"source files changed {len(changed)}"
        )
    assert not out["errors"], f"BOMs that raised: {dict(out['errors'])}"
    if not os.environ.get("SOLIDSEAS_CORPUS_SAMPLE"):
        assert len(recs) >= 300, len(recs)
    assert all(r["indented_adds_up"] and r["parts_adds_up"] and r["top_adds_up"] for r in recs)
    assert sum(r["unread_without_note"] for r in recs) == 0
    assert sum(r["schema_errors"] for r in recs) == 0
    # Held open at once: the file being read and the sub-assemblies that store documents.
    assert all(r["most_open"] <= r["hosts"] + 1 and r["left_open"] == 0 for r in recs)
    assert opened_changed == 0 and not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- path report
_OLD_U16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
_OLD_A8 = re.compile(rb"[\x20-\x7e]{4,}")
_OLD_ABS = re.compile(r"(?:[A-Za-z]:\\|\\\\[^\\\s]+\\)[^\x00-\x1f\"<>|*?]*")
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\|//[^/]+/)")
SCAN_CAP = 16 << 20


def _old_hits(data: bytes) -> dict[str, set]:
    """The 0.1 byte scan (ASCII-only runs, UTF-16LE and 8-bit) with what each hit is:
    ``("string", path)`` for a UTF-16 hit that starts on a path a stored string holds,
    else ``("cut",)`` when the next character (after any spaces the 0.1 scan stripped)
    is not ASCII, else ``("plain",)``."""
    from solidseas.formats.solidworks.metadata import read_cstring
    from solidseas.formats.solidworks.paths import _is_text, _paths_in

    held = []  # (first byte, last byte + 1, path) of each path a stored string holds
    done = 0
    for m in re.finditer(rb"\xff\xfe\xff", data):
        if m.start() < done:
            continue
        text, end = read_cstring(data, m.start())
        if text is None or not _is_text(text):
            continue
        found = _paths_in(text, cstring=True)
        if not found:
            continue
        done = end
        base = end - len(text.encode("utf-16-le", "surrogatepass"))
        for path, at in found:
            a = base + len(text[:at].encode("utf-16-le", "surrogatepass"))
            held.append((a, a + len(path.encode("utf-16-le", "surrogatepass")), path))
    out: dict[str, set] = {}
    for rx, width in ((_OLD_U16, 2), (_OLD_A8, 1)):
        for m in rx.finditer(data):
            text = m.group().decode("utf-16-le" if width == 2 else "ascii")
            for p in _OLD_ABS.finditer(text):
                q = p.group().rstrip()
                if len(q) < 4:
                    continue
                start = m.start() + width * p.start()
                end = start + width * len(q)
                kind: tuple = ("plain",)
                inside = [path for a, b, path in held if a <= start < b] if width == 2 else []
                if inside:
                    kind = ("string", inside[0])
                else:
                    while data[end : end + width] == b" " + b"\x00" * (width - 1):
                        end += width
                    nxt = data[end : end + width]
                    if len(nxt) == width and (nxt[0] >= 0x80 or (width == 2 and nxt[1] != 0)):
                        kind = ("cut",)
                out.setdefault(q, set()).add(kind)
    return out


def _pkey(path: str) -> str:
    from solidseas.formats.solidworks.pathreport import _key

    return _key(path)


def _compare(old: str, kinds: set, keys: set[str], by_prefix: list[str]) -> str:
    """How a path the 0.1 scan found appears in the report. Where the hit lies in a stored
    string, the report must hold that string's own path, whole: the 0.1 hit is then the
    same, cut short at a non-ASCII character, or run past the string's end."""
    k = _pkey(old)
    if k in keys:
        return "same"
    for kind in kinds:
        if kind[0] == "string" and _pkey(kind[1]) in keys:
            held = _pkey(kind[1])
            if held.startswith(k):
                return "old_cut_at_non_ascii"
            if k.startswith(held):
                return "old_ran_past_the_string"
    if ("cut",) in kinds and any(q.startswith(k) and len(q) > len(k) for q in by_prefix):
        return "old_cut_at_non_ascii"
    return "missed"


def _structured_paths(doc) -> list[str]:
    md = doc.metadata
    out = [p for p in (md.header2 or {}).get("ext_paths", [])]
    for f in (md.tree.get("files") or {}).values():
        if isinstance(f.get("path"), str) and _ABSOLUTE.match(f["path"]):
            out.append(f["path"])
        if isinstance(f.get("imported_path"), str) and f["imported_path"].strip():
            out.append(f["imported_path"])
    out += [i["value"] for i in md.identity if i["field"] == "folder_at_save"]
    return out


def _own_streams_old(doc) -> dict[str, set]:
    from solidseas.formats.solidworks.paths import is_noise

    nested = set(doc.nested_documents())
    out: dict[str, set] = {}
    for info in doc.streams():
        if info.size <= SCAN_CAP and info.name not in nested:
            try:
                hits = _old_hits(doc.container.read(info.name))
            except SolidSeasError:
                continue
            for p, kinds in hits.items():
                if not is_noise(p):
                    out.setdefault(p, set()).update(kinds)
    return out


def _walk_nested(doc, acc: dict) -> None:
    for name in doc.nested_documents():
        try:
            nd = doc.open_nested(name)
        except SolidSeasError:
            continue
        try:
            acc["documents"] += 1
            acc["structured"] += _structured_paths(nd)
            for p, kinds in _own_streams_old(nd).items():
                acc["old"].setdefault(p, set()).update(kinds)
            _walk_nested(nd, acc)
        finally:
            nd.close()


def _letter_tails(doc) -> tuple[int, int, int]:
    """Stored strings that end with a path, how many are followed by a unit a scan of
    any letter would have appended, and how many paths the scan reads from counted 8-bit
    strings in a code page (encoding ``ansi``)."""
    from solidseas.formats.solidworks.metadata import read_cstring
    from solidseas.formats.solidworks.paths import _path_char, _paths_in, scan_bytes

    ended = tails = code_page = 0
    nested = set(doc.nested_documents())
    for info in doc.streams():
        if info.size > SCAN_CAP or info.name in nested:
            continue
        try:
            d = doc.container.read(info.name)
        except SolidSeasError:
            continue
        code_page += sum(1 for _p, enc in scan_bytes(d) if enc == "ansi")
        done = 0
        for m in re.finditer(rb"\xff\xfe\xff", d):
            if m.start() < done:
                continue
            text, end = read_cstring(d, m.start())
            if text is None:
                continue
            done = end
            paths = _paths_in(text, cstring=True)
            if not paths or not text.rstrip().endswith(paths[-1][0]):
                continue
            ended += 1
            if end + 1 < len(d):
                u = d[end] | d[end + 1] << 8
                tails += u >= 0x80 and not 0xD800 <= u <= 0xDFFF and _path_char(chr(u))
    return ended, tails, code_page


def path_report_one(task: tuple[int, str]) -> dict:
    row, path = task
    rec: dict = {"row": row}
    try:
        with open_document(path) as doc:
            t0 = time.perf_counter()
            data = model.build_path_report(doc)
            rec["seconds"] = time.perf_counter() - t0
            rec["schema_errors"] = _strict_errors("path_report", data)
            model.dumps(model.envelope("path_report", data))
            rec["complete"] = data["complete"]
            rec["incomplete"] = [g["reason"] for g in data["incomplete"]]
            rec["paths"] = len(data["paths"])
            rec["non_ascii"] = sum(1 for p in data["paths"] if not p["path"].isascii())
            rec["documents"] = len(data["documents"])
            rec["inherited"] = sum(1 for a in data["accounts"] if a["inherited_likely"])
            rec["by_category"] = data["counts"]["by_category"]
            keys = {_pkey(p["path"]) for p in data["paths"]}
            by_prefix = sorted(keys)
            acc: dict = {"documents": 0, "structured": _structured_paths(doc), "old": {}}
            _walk_nested(doc, acc)
            rec["nested_documents"] = acc["documents"]
            rec["structured"] = len(acc["structured"])
            rec["structured_missing"] = sum(1 for p in acc["structured"] if _pkey(p) not in keys)
            top = _own_streams_old(doc)
            top_keys = {_pkey(p) for p in top}
            rec["old"] = Counter(_compare(p, kinds, keys, by_prefix) for p, kinds in top.items())
            only = {p: kinds for p, kinds in acc["old"].items() if _pkey(p) not in top_keys}
            rec["nested_only"] = Counter(_compare(p, kinds, keys, by_prefix) for p, kinds in only.items())
            rec["strings_ending_in_a_path"], rec["letter_tails"], rec["code_page"] = _letter_tails(doc)
        rec["ok"] = True
    except LockedFileError:
        rec["locked"] = True
    except SolidSeasError as exc:
        rec["error"] = type(exc).__name__
    except Exception as exc:  # anything else is a bug: report its type only
        rec["unexpected"] = type(exc).__name__
    return rec


def test_corpus_path_report(capsys):
    rows, _skipped = _rows()
    assert rows, "the manifest lists no modern or ole rows"
    before = {}
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            before[row] = (st.st_size, st.st_mtime_ns)
        except OSError:
            before[row] = None
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", str(min(6, os.cpu_count() or 1))))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
        results = list(pool.map(path_report_one, [(row, path) for row, path, _f, _e in rows], chunksize=4))
    elapsed = time.time() - t0
    changed = []
    for row, path, _fmt, _ext in rows:
        try:
            st = os.stat(path)
            now = (st.st_size, st.st_mtime_ns)
        except OSError:
            now = None
        if now != before[row]:
            changed.append(row)
    ok = [r for r in results if r.get("ok")]
    unexpected = [r["row"] for r in results if r.get("unexpected")]
    failed = [r["row"] for r in results if r.get("error")]

    def total(key: str) -> int:
        return sum(r.get(key, 0) for r in ok)

    old: Counter = Counter()
    nested_only: Counter = Counter()
    categories: Counter = Counter()
    for r in ok:
        old.update(r["old"])
        nested_only.update(r["nested_only"])
        categories.update(r["by_category"])
    reasons = Counter(x for r in ok for x in r["incomplete"])
    times = sorted(r["seconds"] for r in ok)

    def pct(q: float) -> float:
        return times[min(len(times) - 1, int(q * len(times)))]

    ended, tails = total("strings_ending_in_a_path"), total("letter_tails")
    with capsys.disabled():
        print()
        print(
            f"SolidSeas corpus path report: {len(rows)} documents, {len(ok)} reported, "
            f"{workers} workers, {elapsed:.1f} s"
        )
        print(
            f"  per report: p50 {pct(0.5):.3f} s, p95 {pct(0.95):.3f} s, p99 {pct(0.99):.3f} s, "
            f"max {times[-1]:.3f} s, {sum(times):.1f} s in all"
        )
        print(
            f"  complete {sum(1 for r in ok if r['complete'])}; incomplete reasons: "
            + (", ".join(f"{k} {v}" for k, v in sorted(reasons.items())) or "none")
        )
        print(
            f"  paths {total('paths')} ({total('non_ascii')} non-ASCII); documents read "
            f"{total('documents')}, nested {total('nested_documents')}; accounts only in history "
            f"{total('inherited')} in {sum(1 for r in ok if r['inherited'])} files"
        )
        print("  by category: " + ", ".join(f"{k} {v}" for k, v in categories.items()))
        print(f"  structured paths {total('structured')}, missing {total('structured_missing')}")
        print("  0.1 scan, own streams: " + ", ".join(f"{k} {v}" for k, v in sorted(old.items())))
        only = ", ".join(f"{k} {v}" for k, v in sorted(nested_only.items()))
        print("  0.1 scan, only in nested documents: " + only)
        print(
            f"  stored strings ending in a path {ended}, followed by a letter a scan without the "
            f"stored length would append {tails} ({100.0 * tails / max(ended, 1):.1f}%)"
        )
        print(
            f"  paths read from counted 8-bit strings in a code page {total('code_page')}, "
            f"in {sum(1 for r in ok if r['code_page'])} files"
        )
        print(f"  source files changed: {len(changed)}")

    assert len(ok) > 0 and total("structured") > 0 and sum(old.values()) > 0, "the sweep collected nothing"
    assert not unexpected, f"non-SolidSeas exceptions (manifest rows {unexpected[:20]})"
    assert not failed, f"documents that failed (manifest rows {failed[:20]})"
    assert total("schema_errors") == 0, "a path report breaks its schema"
    assert total("structured_missing") == 0, "a structured path is missing from the report"
    assert old["missed"] == 0, "a path the 0.1 scan finds is missing from the report"
    assert nested_only["missed"] == 0, "a path only a nested document holds is missing"
    assert set(reasons) <= {"stream_over_cap"}, reasons
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- three surfaces
SURFACES_SEED = 20261002
SURFACES_SAMPLE = {".sldprt": 120, ".sldasm": 60, ".slddrw": 20}
SURFACE_KINDS = (
    ("document_summary", "info", "document"),
    ("properties", "props", "properties"),
    ("configurations", "configurations", "configurations"),
    ("components", "components", "components"),
    ("references", "references", "references"),
    ("path_report", "paths", "path-report"),
)


def _python_envelope(path: str, kind: str) -> dict:
    builders = {
        "document_summary": model.build_document_summary,
        "properties": model.build_properties,
        "configurations": model.build_configurations,
        "components": model.build_components,
        "references": model.build_references,
        "path_report": model.build_path_report,
    }
    try:
        with open_document(path) as doc:
            return model.envelope(kind, builders[kind](doc))
    except Exception as exc:
        return model.error_envelope(exc)


def _comparable(env: dict) -> dict:
    """An envelope without ``source`` (where the document is) and, for an error, without
    ``reader_message``, which the REST service never sends."""
    out = {k: v for k, v in env.items() if k != "source"}
    if not env.get("ok"):
        out["error"] = {k: v for k, v in env["error"].items() if k != "reader_message"}
    return out


def test_corpus_surfaces(capsys):
    """Python, the CLI and the REST service give the same JSON for a seeded sample of the
    corpus, the service reading every document in its worker processes with lazy reads
    while Python and the CLI read each file whole; and the preview image is the same
    bytes. Numbers only: rows, counts and times."""
    import hashlib
    import io
    import json
    from contextlib import redirect_stdout

    from serve_support import Running
    from solidseas import cli
    from solidseas.roots import Root, Roots

    rows, _skipped = _rows()
    rng = random.Random(SURFACES_SEED)
    sample = []
    for ext, n in SURFACES_SAMPLE.items():
        group = [r for r in rows if r[3] == ext]
        sample += rng.sample(group, min(n, len(group)))
    sample.sort()
    assert len(sample) >= 50, f"the sample holds only {len(sample)} documents"
    before = {}
    for row, path, _fmt, _ext in sample:
        st = os.stat(path)
        before[row] = (st.st_size, st.st_mtime_ns)
    folders = sorted({os.path.dirname(path) for _row, path, _f, _e in sample})
    root_of = {folder: f"f{i}" for i, folder in enumerate(folders)}
    roots = Roots([Root(root_of[f], f, recursive=False) for f in folders])
    counts: Counter = Counter()
    differ: list[tuple[int, str]] = []
    times: dict[str, list[float]] = defaultdict(list)
    _set_priority(True)  # the workers the service starts inherit it
    try:
        running = Running(roots, workers=min(4, os.cpu_count() or 1))
        try:
            for row, path, _fmt, _ext in sample:
                root, name = root_of[os.path.dirname(path)], os.path.basename(path)
                for kind, command, route in SURFACE_KINDS:
                    python = _python_envelope(path, kind)
                    out = io.StringIO()
                    with redirect_stdout(out):
                        cli.main([command, path, "--json"])
                    cli_env = json.loads(out.getvalue())
                    t0 = time.perf_counter()
                    r = running.get(route, root=root, path=name)
                    times[route].append(time.perf_counter() - t0)
                    rest_env = r.json()
                    counts["comparisons"] += 2
                    counts["errors" if not python["ok"] else "ok"] += 1
                    if r.status == 422 and rest_env["error"]["code"] == "response_too_large":
                        counts["response_too_large"] += 1
                        continue
                    if not _comparable(python) == _comparable(cli_env) == _comparable(rest_env):
                        differ.append((row, kind))
                with open_document(path) as doc:
                    pv = doc.preview()
                t0 = time.perf_counter()
                r = running.get("preview", root=root, path=name)
                times["preview"].append(time.perf_counter() - t0)
                counts["preview_comparisons"] += 1
                if pv is None:
                    same = r.status == 404 and r.json()["error"]["code"] == "no_preview"
                else:
                    counts["previews"] += 1
                    digest = hashlib.sha256(pv.data).digest()
                    same = r.status == 200 and hashlib.sha256(r.body).digest() == digest
                if not same:
                    differ.append((row, "preview"))
            log_lines = len(running.log.lines)
        finally:
            running.close()
    finally:
        _set_priority(False)
    changed = []
    for row, path, _fmt, _ext in sample:
        st = os.stat(path)
        if (st.st_size, st.st_mtime_ns) != before[row]:
            changed.append(row)

    def pct(values: list[float], q: float) -> float:
        values = sorted(values)
        return values[min(len(values) - 1, int(q * len(values)))] if values else 0.0

    with capsys.disabled():
        print(
            f"\nSolidSeas corpus surfaces: {len(sample)} documents in {len(folders)} folders, "
            f"{counts['comparisons']} comparisons of {len(SURFACE_KINDS)} kinds ({counts['ok']} data, "
            f"{counts['errors']} errors), {counts['preview_comparisons']} previews "
            f"({counts['previews']} stored), {len(differ)} differences, "
            f"{counts['response_too_large']} over a size cap, {log_lines} log lines"
        )
        for route, values in sorted(times.items()):
            print(
                f"  /v1/{route}: p50 {1000 * pct(values, 0.5):.0f} ms, "
                f"p99 {1000 * pct(values, 0.99):.0f} ms, max {1000 * max(values):.0f} ms"
            )
        print(f"  source files changed: {len(changed)}")
    assert counts["comparisons"] == 2 * len(SURFACE_KINDS) * len(sample)
    assert counts["previews"] > 0 and counts["ok"] > 0
    assert not differ, f"the surfaces differ (manifest row, kind): {differ[:20]}"
    assert counts["response_too_large"] == 0
    assert not changed, f"source files changed (manifest rows {changed[:20]})"


# --------------------------------------------------------------------------- STEP export
STEP_SEED = 20261003
STEP_SAMPLE = 400
# Floors for the full 400-part sample (docs/FORMAT.md 10.9), with room for drift.
STEP_WRITTEN_MIN = 350
STEP_EXACT_MIN = 240

_STEP_CHILD = r"""
import json, sys, time
sys.path[:0] = sys.argv[3:5]
from test_corpus import _lower_priority
_lower_priority()
from solidseas import open_document
from solidseas.errors import SolidSeasError
import solidseas.step as S

rec = {}
t0 = time.perf_counter()
try:
    with open_document(sys.argv[1]) as doc:
        if doc.doc_type != "part":
            rec["skip"] = 1
        else:
            try:
                m = S.step_model(doc)
            except SolidSeasError as exc:
                rec["error"] = exc.code
                if exc.code == "not_representable":
                    rec["reasons"] = sorted({b.reason for b in exc.bodies})
                if exc.code == "limit_exceeded":
                    rec["limit"] = (exc.detail or {}).get("limit")
            else:
                data = S.step_bytes(m, time_stamp="2026-10-03T00:00:00Z")
                from solidseas.step.mapper import FACTS

                rec["facts"] = dict(FACTS)
                rec.update(
                    written=1,
                    exact=int(m.exact),
                    approximated=m.approximated,
                    deviation_nm=(m.max_deviation_m or 0.0) * 1e9,
                    gap_nm=(m.max_gap_m or 0.0) * 1e9,
                    uncertainty_nm=m.uncertainty_m * 1e9,
                    faces=m.counts["faces"],
                    bytes=len(data),
                    map_s=m.seconds,
                )
                print(json.dumps(rec), flush=True)
                if sys.argv[2] == "check":
                    import step_support as T

                    t1 = time.perf_counter()
                    rec.update(T.corpus_report(data, doc, m))
                    rec["check_s"] = time.perf_counter() - t1
except SolidSeasError as exc:
    rec["error"] = exc.code
except Exception as exc:  # a bug: its type only, the text can quote a path
    rec["unexpected"] = type(exc).__name__
rec["s"] = time.perf_counter() - t0
print(json.dumps(rec), flush=True)
"""


def step_one(task: tuple[int, str, float]) -> dict:
    """One part through the STEP export and the checker, in a child process stopped at
    ``limit`` seconds: numbers and codes only."""
    import json
    import subprocess

    row, path, limit = task
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(os.path.dirname(here), "src")
    cmd = [sys.executable, "-c", _STEP_CHILD, path, "check", here, src]
    flags = 0x4000 if sys.platform == "win32" else 0  # BELOW_NORMAL_PRIORITY_CLASS
    rec: dict = {}
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=limit, creationflags=flags).stdout
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        timed_out = True
    for line in out.splitlines():
        if line.startswith("{"):
            rec.update(json.loads(line))
    if timed_out:
        rec["check_timeout" if rec.get("written") else "timeout"] = 1
    elif not rec:
        rec["child_failed"] = 1
    rec["row"] = row
    return rec


def test_corpus_step(capsys):
    """The STEP export over a seeded sample of parts, every file written re-read and
    checked; the source files unchanged."""
    from concurrent.futures import ThreadPoolExecutor

    rows, _skipped = _rows()
    parts = [r for r in rows if r[3] == ".sldprt"]
    n = int(os.environ.get("SOLIDSEAS_CORPUS_STEP_SAMPLE", str(STEP_SAMPLE)))
    sample = random.Random(STEP_SEED).sample(parts, min(n, len(parts)))
    check_limit = float(os.environ.get("SOLIDSEAS_CORPUS_STEP_CHECK_SECONDS", "600"))
    before = {}
    for row, path, _fmt, _ext in sample:
        st = os.stat(path)
        before[row] = (st.st_size, st.st_mtime_ns)
    workers = int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", "3"))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(step_one, [(row, path, 300.0 + check_limit) for row, path, _f, _e in sample]))
    elapsed = time.time() - t0
    changed = [
        row
        for row, path, _f, _e in sample
        if (os.stat(path).st_size, os.stat(path).st_mtime_ns) != before[row]
    ]
    written = [r for r in results if r.get("written")]
    refused = [r for r in results if r.get("error") == "not_representable"]
    limited = [r for r in results if r.get("error") == "limit_exceeded" or r.get("timeout")]
    nothing = [r for r in results if r.get("error") == "nothing_to_export"]
    skipped = [r for r in results if r.get("skip")]
    other = [r["row"] for r in results if r.get("unexpected") or r.get("child_failed")]
    failed = [
        r["row"]
        for r in results
        if r.get("error") not in (None, "not_representable", "limit_exceeded", "nothing_to_export")
    ]
    checked = [r for r in written if "syntax_problems" in r]
    reasons = Counter(x for r in refused for x in r.get("reasons", []))
    approximated = Counter(k for r in written for k in r.get("approximated", {}))
    facts = Counter()
    for r in written:
        facts.update(r.get("facts", {}))
    problems = Counter()
    for r in checked:
        for k in (
            "syntax_problems",
            "topology_problems",
            "beyond_allowance",
            "faces_disagree",
            "edges_wrong",
            "edges_far",
            "edges_cut_wrong",
        ):
            problems[k] += r[k]

    def q(values, f):
        values = sorted(values)
        return values[min(len(values) - 1, int(f * len(values)))] if values else 0.0

    with capsys.disabled():
        print(f"\nSolidSeas corpus STEP export: {len(sample)} parts in {elapsed:.0f} s")
        print(
            f"  written {len(written)} ({sum(r['exact'] for r in written)} exact), refused {len(refused)} "
            f"({', '.join(f'{k} {v}' for k, v in sorted(reasons.items())) or 'none'}), at a limit "
            f"{len(limited)}, nothing to export {len(nothing)}, not parts {len(skipped)}"
        )
        print(
            "  approximated: " + (", ".join(f"{k} in {v}" for k, v in sorted(approximated.items())) or "none")
        )
        print("  facts: " + (", ".join(f"{k} {v}" for k, v in sorted(facts.items())) or "none"))
        if written:
            print(
                f"  deviation at most {max(r['deviation_nm'] for r in written):.0f} nm, gap at most "
                f"{max(r['gap_nm'] for r in written):.0f} nm, uncertainty at most "
                f"{max(r['uncertainty_nm'] for r in written):.0f} nm"
            )
            maps = [r["map_s"] for r in written]
            sizes = [r["bytes"] for r in written]
            print(
                f"  mapping s: median {q(maps, 0.5):.2f}, 90th {q(maps, 0.9):.1f}, max {max(maps):.0f}; "
                f"bytes: median {q(sizes, 0.5):,.0f}, max {max(sizes):,}"
            )
        late = sum(1 for r in written if r.get("check_timeout"))
        faces = sum(r["faces_oracle"] for r in checked)
        agree = sum(r["faces_agree"] for r in checked)
        arcs = sum(r["edges_checked"] for r in checked)
        right = sum(r["edges_right"] for r in checked)
        on = max((r["edge_surface_max_nm"] for r in checked), default=0)
        print(
            f"  checked {len(checked)} of {len(written)} ({late} past the check limit): faces {faces:,} "
            f"compared, {agree:,} agree; curved edges {arcs:,} checked, {right:,} on their arc; edges at "
            f"most {on} nm off their faces; problems {dict(problems)}"
        )
        print(f"  source files changed: {len(changed)}")
    assert not other, f"exports that crashed (manifest rows {other[:20]})"
    assert not failed, f"exports that failed otherwise (manifest rows {failed[:20]})"
    assert len(written) + len(refused) + len(limited) + len(nothing) + len(skipped) == len(sample)
    assert all(r.get("reasons") for r in refused)
    assert not any(problems.values()), dict(problems)
    if n == STEP_SAMPLE:
        assert len(written) >= STEP_WRITTEN_MIN and sum(r["exact"] for r in written) >= STEP_EXACT_MIN
    assert not changed, f"source files changed (manifest rows {changed[:20]})"
