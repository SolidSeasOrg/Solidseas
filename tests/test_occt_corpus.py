"""The OCCT oracle over the private corpus (opt-in, ``tests/README.md``).

Runs only when ``SOLIDSEAS_OCCT_PYTHON`` names an interpreter where OCP imports and
``SOLIDSEAS_CORPUS_MANIFEST`` names the corpus manifest. It never prints, keeps or
asserts a name, a path or any text from a private file: parts are keyed by manifest
row, STEP files as ``step#N``, their index in sorted-path order among the STEP files
in the folders that hold manifest rows and below them (SolidSeas' own checkouts left
out). Every private file is opened read-only, by children at below-normal priority in
Job Objects (``occt_support``), and its size and modification time are checked after.

``test_occt_corpus_step_export``: SolidSeas exports parts as the viewer's File > Export
STEP does (the active configuration's solid bodies, or its sheet bodies when it has
only sheets; in a child of its own) to a private temporary folder; OCCT reads each file
there, and so does SolidSeas' own reader, and the file is deleted as soon as both have
read it. The parts are the rows of ``SOLIDSEAS_SW_TRUTH`` when it names SOLIDWORKS' own
measurements of the corpus (the ``sw_oracle`` job's ``corpus.json``: ``parts`` keyed
``row:N``, each with ``sha256``, ``native_mass_valid`` and ``native_active``'s ``mass``,
body counts, ``sheet_area_m2`` and ``bbox_all_bodies_m``), else
``random.Random(20261004).sample`` of ``SOLIDSEAS_OCCT_CORPUS_SAMPLE`` parts (default
175). Every file written must read in OCCT without a failure, into as many closed solids
(or, for a part of sheets, at least as many free shells) as SolidSeas wrote, valid except
on the rows of :data:`KNOWN_INVALID` and :data:`KNOWN_DEGENERATE_SHEETS`; every shell
SolidSeas' reader finds in its own file has the sign of OCCT's shell at its place (a
void written inside out would add its volume in any reader that takes the file at its
word, though OCCT turns it round by its geometry). Against SOLIDWORKS (the part's sha256
matching the truth's) the Gauss-Kronrod volume and the adaptive area, or a part of
sheets' sheet area, are within 1e-3. Hidden bodies are left out of the export, so a part
with hidden bodies is compared by volume and area like the others. One whose STEP still
holds more solids than SOLIDWORKS shows (some bodies carry no mark, and the export then
writes them all), and a part of sheets, are compared by the box of all bodies, within
1e-3 of its diagonal.

``test_occt_corpus_step_reader``: SolidSeas' STEP reader against OCCT, per face, per
shell and in total (``occt_support.reader_report``), on ``random.Random(20261004)
.sample`` of ``SOLIDSEAS_OCCT_STEP_SAMPLE`` STEP files (default 40) of at most
``SOLIDSEAS_OCCT_STEP_MAX_MB`` (default 5), plus every key of :data:`KNOWN_KEYS` and the
``step#N`` keys ``SOLIDSEAS_OCCT_STEP_KEYS`` lists. SolidSeas tessellates at 2e-5 of
OCCT's box diagonal and a face (allowed its chord error too, when it falls short on a
cylinder, sphere or torus), a shell or the total must agree within 1 % with either of
OCCT's measures. The disagreements no chord excuses
(``occt_support.SOUNDNESS``: faces larger than their surface, shells inside out,
open or folded edges, skipped faces) are also looked for as the viewer draws the file
and as 3D Print tessellates it, at their own chords. It reports what disagrees by kind
and key, and asserts that SolidSeas never crashed, raised or ran out of memory (a file
past the child's 700 s is counted) and that no file changed. The reader's defects
reproduced in ``occt_shapes.DEFECTS`` are fixed and checked by ``test_occt_oracle.py``;
the files of :data:`KNOWN_KEYS` that still disagree are reported, not asserted.

``SOLIDSEAS_CORPUS_WORKERS`` sets the parallel files (default 3).
"""

import csv
import hashlib
import json
import math
import os
import random
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import occt_support as O

MANIFEST = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
TRUTH = os.environ.get("SOLIDSEAS_SW_TRUTH")
pytestmark = [
    pytest.mark.occt,
    pytest.mark.skipif(not MANIFEST, reason="SOLIDSEAS_CORPUS_MANIFEST is not set"),
    pytest.mark.skipif(O.occt_python() is None, reason=f"{O.OCCT_PYTHON_ENV} is not set"),
]
HERE = Path(__file__).parent
CHILD = HERE / "occt_solidseas_child.py"
SYS_PATH = [str(HERE.parent / "src"), str(HERE)]
SEED = 20261004
STEP_EXT = {".step", ".stp", ".p21"}
# Rows whose STEP OCCT finds invalid for a cause outside SolidSeas' mapping: SolidSeas writes
# no pcurves, and the ones OCCT projects for itself drift up to 0.16 mm off these faces
# (BRepCheck: wires wrongly nested or oriented after its healing split them; docs/FORMAT.md
# 10.9). Cutting closed faces at their seams did not clear them, and writing pcurves would not
# (OCCT's default reader computes its own; docs/OCCT.md 6.1).
KNOWN_INVALID = {1662, 2103, 2455}
# Parts of one sheet whose single face is degenerate: SOLIDWORKS measures its area as
# 3.5e-21 square metres, OCCT finds the face invalid and its box 1.4e-3 of the diagonal
# off. Exported as File > Export STEP exports them, but not compared.
KNOWN_DEGENERATE_SHEETS = {213, 234}
# step#N keys of the files where the oracle found the reader wrong, read on every run
# besides the sample, by the bead that fixes them (the OCCT evaluation's list and the
# oracle's; docs/formats/step.md section 11). The keys number the files as step_files()
# does: adding files to those folders moves them.
VOIDS_INSIDE_OUT = (32, 38, 182, 885, 889, 1022, 1098, 1099, 1104, 1245, 1249, 1269, 1270, 1389)
KNOWN_KEYS = {
    "voids inside out (bead 1)": VOIDS_INSIDE_OUT,
    "faces larger than their surface, torus faces off (bead 2)": (48, 569, 903, 1023, 1146, 1175, 1250, 1271),
    "faces whose loops run against them (bead 3)": (12, 13, 14, 15, 17, 18, 19, 20),
    "faces skipped, solids left open (no bead yet)": (239, 611, 779, 989, 1305),
    "open or folded as the viewer or 3D Print draws them (no bead yet)": (163, 412, 879, 898, 1116),
}
# The other files with voids (BREP_WITH_VOIDS, all of them ORIENTED_CLOSED_SHELL .F.) the
# reader reads right, also read on every run: bead 1 must keep them so. step#426, of 76 MB,
# is the 21st, past OCCT's memory cap.
VOIDS_READ_RIGHT = (283, 896, 898, 1033, 1076, 1100)
EXPORT_TOL = 1e-3
READER_TOL = 1e-2
CHORD_REL = 2e-5  # SolidSeas' chord, times OCCT's box diagonal
MESH_REL = 3e-5  # OCCT's own check mesh, likewise


@pytest.fixture(scope="module", autouse=True)
def _occt_ready():
    reason = O.skip_reason()
    if reason:
        pytest.skip(reason)


def _workers() -> int:
    return int(os.environ.get("SOLIDSEAS_CORPUS_WORKERS", "3"))


def _parts() -> list[tuple[int, str]]:
    """(manifest row, path) of every part the manifest lists as readable; row 1 is the header."""
    out = []
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):
            if r.get("format") in ("modern", "ole") and os.path.splitext(r["path"])[1].lower() == ".sldprt":
                out.append((i, r["path"]))
    return out


def _is_checkout(folder: str) -> bool:
    return os.path.isfile(os.path.join(folder, "src", "solidseas", "__init__.py")) and os.path.isfile(
        os.path.join(folder, "pyproject.toml")
    )


def _inside_checkout(folder: str) -> bool:
    while True:
        if _is_checkout(folder):
            return True
        up = os.path.dirname(folder)
        if up == folder:
            return False
        folder = up


def step_files() -> list[str]:
    """The STEP files in the folders that hold manifest rows and below them, SolidSeas'
    own checkouts left out, in sorted order of their normalised paths: ``step#N`` is the
    N-th (from 0)."""
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        folders = sorted({os.path.normcase(os.path.dirname(r["path"])) for r in csv.DictReader(fh)})
    seen: set[str] = set()
    for top in folders:
        if _inside_checkout(top):
            continue
        for dp, dn, fs in os.walk(top):
            dn[:] = [d for d in dn if not _is_checkout(os.path.join(dp, d))]
            for name in fs:
                path = os.path.normcase(os.path.join(dp, name))
                if (
                    os.path.splitext(name)[1].lower() in STEP_EXT
                    and path not in seen
                    and os.path.isfile(path)
                ):
                    seen.add(path)
    return sorted(seen)


def _stamp(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _q(values, f):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    return values[min(len(values) - 1, int(f * len(values)))] if values else float("nan")


def _priority_below_normal() -> int | None:
    """This process below normal priority while it reads private files (its children are
    already, by their job); the class it had, to restore."""
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
        k32.GetPriorityClass.restype = ctypes.c_uint32
        me = k32.GetCurrentProcess()
        old = k32.GetPriorityClass(me)
        k32.SetPriorityClass(me, 0x4000)
        return old
    return None


def _priority_restore(old) -> None:
    if sys.platform == "win32" and old:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k32.SetPriorityClass(k32.GetCurrentProcess(), old)


def _read(path: str, **how) -> O.ChildResult:
    """SolidSeas' reading of a STEP file in its own child (``occt_solidseas_child``), at
    ``chord_m`` or as ``drawn``."""
    return O.run_child(
        {"op": "read", "path": path, "max_seconds": 600, "sys_path": SYS_PATH, **how},
        python=sys.executable, script=CHILD, timeout_s=700.0, memory_mb=4096,
    )  # fmt: skip


def _ours(reply: dict) -> dict:
    out = dict(reply)
    out["faces"] = [O.FaceMeasure(f[0], (f[1], f[2], f[3])) for f in reply["faces"]]
    return out


def _diag(box) -> float:
    return math.dist(box[:3], box[3:]) if box else 0.0


# --------------------------------------------------------------------------- STEP export
def export_one(task) -> dict:
    row, path, folder, truth_sha = task
    rec: dict = {"row": row}
    before = _stamp(path)
    if truth_sha is not None:
        rec["sha_ok"] = _sha256(path) == truth_sha
    out = os.path.join(folder, f"r{row}.step")
    try:
        got = O.run_child(
            {"op": "export", "path": path, "out": out, "name": f"r{row}", "sys_path": SYS_PATH},
            python=sys.executable, script=CHILD, timeout_s=600.0, memory_mb=4096,
        )  # fmt: skip
        rec["export"] = got.status if not got.ok else got.reply.get("status", "error")
        rec["export_detail"] = (got.reply or {}).get("code") or got.exception or got.crash
        if got.ok and got.reply.get("status") == "written":
            rec["written_solids"] = got.reply["solids"]
            rec["written_sheets"] = got.reply["sheets"]
            rec["sheets_fallback"] = got.reply["sheets_fallback"]
            rec["exact"] = got.reply["exact"]
            occ = O.run_child({"op": "step", "path": out}, timeout_s=900.0, memory_mb=4096)
            rec["occt"] = occ.status
            rec["occt_detail"] = occ.exception or occ.crash
            rec["r"] = occ.reply
            shells = [s for s in (occ.reply or {}).get("shells") or [] if s.get("volume") is not None]
            if occ.ok and shells:
                # SolidSeas' reader on its own file: a void's sign as written
                ss = _read(out, drawn="print")
                if ss.ok and not ss.reply.get("refused"):
                    m = O.match_shells(
                        shells,
                        [p for p in ss.reply["pieces"] if p["solid"]],
                        tol=READER_TOL,
                        near=0.05 * _diag(occ.reply.get("box")),
                    )
                    rec["reread"] = {
                        "voids": sum(1 for s in shells if s["volume"] < 0),
                        "shells": list(m["shells"]),
                        "pairs": m["pairs"],
                        "inverted": len(m["inverted"]),
                    }
                else:
                    rec["reread"] = {"status": ss.status, "refused": (ss.reply or {}).get("refused")}
    finally:
        if os.path.exists(out):
            os.remove(out)  # a file made from a private part leaves this folder at once
    rec["changed"] = _stamp(path) != before
    return rec


def _against_truth(rec: dict, t: dict) -> dict:
    """OCCT's measures of a part's STEP against SOLIDWORKS' measures of the part."""
    r, nat = rec["r"], t.get("native_active") or {}
    mass = nat.get("mass") or {}
    visible = (nat.get("solid_bodies") or 0) - (nat.get("hidden_solid_bodies") or 0)
    out: dict = {}
    if rec.get("sheets_fallback"):  # a part of surfaces, sent as its sheets
        area = nat.get("sheet_area_m2")
        if area and rec["written_sheets"] == nat.get("sheet_bodies") and not nat.get("hidden_sheet_bodies"):
            out["sheet_area"] = O.rel(r.get("sheet_area"), area)
        box = nat.get("bbox_all_bodies_m")
        out["box_all"] = O.box_deviation(r.get("box"), box) if box else None
    elif (
        rec["written_solids"] == visible
        and t.get("native_mass_valid") is True
        and (mass.get("volume_m3") or 0) > 0
    ):
        out["volume"] = O.rel(r.get("volume"), mass["volume_m3"])
        out["area"] = O.rel(r.get("area"), mass.get("surface_area_m2"))
    elif nat.get("hidden_solid_bodies"):  # the STEP holds more solids than SOLIDWORKS shows
        box = nat.get("bbox_all_bodies_m")
        out["box_all"] = O.box_deviation(r.get("box_solids"), box) if box else None
    return out


def _unsound(rec: dict) -> bool:
    """OCCT read the file as something other than SolidSeas wrote."""
    x = rec["r"]
    c = x["counts"]
    return bool(
        x.get("null_shape")
        or x["roots_transferred"] != x["roots"]
        or x["transfer_checks"]["fails"]
        or c["solids"] != rec["written_solids"]
        or x["open_solid_shells"]
        or x["solid_free_edges"]
        or (rec.get("sheets_fallback") and (c["free_shells"] < rec["written_sheets"] or c["free_faces"]))
    )


def test_occt_corpus_step_export(capsys):
    """SolidSeas' STEP of private parts, read by OCCT (see the module notes)."""
    parts = dict(_parts())
    truth = None
    if TRUTH:
        with open(TRUTH, encoding="utf-8") as fh:
            truth = {int(v["row"]): v for v in json.load(fh)["parts"].values()}
        rows = sorted(r for r in truth if r in parts)
    else:
        n = int(os.environ.get("SOLIDSEAS_OCCT_CORPUS_SAMPLE", "175"))
        rows = sorted(random.Random(SEED).sample(sorted(parts), min(n, len(parts))))
    old = _priority_below_normal()
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory(prefix="solidseas-occt-") as folder:
            tasks = [(row, parts[row], folder, truth[row]["sha256"] if truth else None) for row in rows]
            with ThreadPoolExecutor(max_workers=_workers()) as pool:
                results = list(pool.map(export_one, tasks))
            left = os.listdir(folder)
    finally:
        _priority_restore(old)
    elapsed = time.time() - t0
    written = [r for r in results if r["export"] == "written"]
    refused = Counter(r["export_detail"] for r in results if r["export"] == "refused")
    export_failed = [r["row"] for r in results if r["export"] not in ("written", "refused", "not_a_part")]
    read = [r for r in written if r.get("occt") == "ok" and r["r"].get("read_status") == "RetDone"]
    occt_failed = [(r["row"], r.get("occt"), r.get("occt_detail")) for r in written if r not in read]
    unsound, invalid, healing = [], [], Counter()
    for r in read:
        healing.update(r["r"]["transfer_checks"]["warnings"])
        if _unsound(r):
            unsound.append(r["row"])
        if r["r"].get("valid") is not True:
            invalid.append(r["row"])
    known = KNOWN_INVALID | KNOWN_DEGENERATE_SHEETS
    rereads = [r for r in read if "reread" in r]
    reread_failed = [(r["row"], r["reread"]) for r in rereads if "inverted" not in r["reread"]]
    inverted = [r["row"] for r in rereads if r["reread"].get("inverted")]
    with_voids = [r["row"] for r in rereads if r["reread"].get("voids")]
    compared: dict[str, list] = {"volume": [], "area": [], "sheet_area": [], "box_all": []}
    beyond = []
    if truth:
        for r in read:
            t = truth[r["row"]]
            if not r.get("sha_ok") or r["row"] in known:
                continue
            got = _against_truth(r, t)
            for k, v in got.items():
                if v is not None:
                    compared[k].append(v)
                    if v > EXPORT_TOL:
                        beyond.append((r["row"], k, f"{v:.2g}"))
    changed = [r["row"] for r in results if r["changed"]]
    versions = O.versions()
    with capsys.disabled():
        exact = sum(1 for r in written if r["exact"])
        sheets = sum(1 for r in written if r.get("sheets_fallback"))
        print(
            f"\nOCCT corpus STEP export (OCP {versions.get('cadquery-ocp')}, OCCT {versions.get('occt')}): "
            f"{len(rows)} parts in {elapsed:.0f} s, written {len(written)} ({exact} exact, {sheets} parts "
            f"of sheets), refused {sum(refused.values())} {dict(refused)}"
        )
        print(
            f"  read by OCCT {len(read)}, failed {len(occt_failed)}, unsound {len(unsound)}, "
            f"invalid {len(invalid)} (rows {sorted(invalid)})"
        )
        print("  healing: " + (", ".join(f"{k} {v}" for k, v in healing.most_common()) or "none"))
        print(
            f"  read back by SolidSeas {len(rereads) - len(reread_failed)} of {len(rereads)}, "
            f"{len(with_voids)} with voids (rows {sorted(with_voids)[:20]}), "
            f"shells inside out in {len(inverted)}"
        )
        for k, v in compared.items():
            if v:
                print(
                    f"  against SOLIDWORKS, {k}: {len(v)} parts, p50 {_q(v, 0.5):.2g}, "
                    f"p90 {_q(v, 0.9):.2g}, max {max(v):.2g}"
                )
        print(
            f"  beyond {EXPORT_TOL:g}: {beyond[:20]}; files left behind {len(left)}; "
            f"source files changed {len(changed)}"
        )
    assert not changed, f"source files changed (manifest rows {changed[:20]})"
    assert not left
    assert not export_failed, f"exports that failed (manifest rows {export_failed[:20]})"
    assert not occt_failed, f"files OCCT could not read (row, status, detail): {occt_failed[:20]}"
    assert not unsound, f"files OCCT read unsoundly (manifest rows {unsound[:20]})"
    assert set(invalid) <= known, f"files OCCT finds invalid (manifest rows {sorted(set(invalid) - known)})"
    assert not inverted, f"files whose shells SolidSeas reads inside out (manifest rows {inverted[:20]})"
    crashed = [x for x in reread_failed if x[1].get("status") != "timeout"]  # a refusal included
    assert not crashed, f"SolidSeas failed to read its own file (row, what): {crashed[:20]}"
    assert not beyond, f"parts beyond {EXPORT_TOL:g} of SOLIDWORKS (row, measure, value): {beyond[:20]}"


# --------------------------------------------------------------------------- the STEP reader
def read_one(task) -> dict:
    key, path = task
    rec: dict = {"key": key}
    before = _stamp(path)
    occ = O.run_child({"op": "step", "path": path, "faces": True, "mesh_rel": MESH_REL, "mesh_min_mm": 1e-3},
                      timeout_s=900.0, memory_mb=4096)  # fmt: skip
    rec["occt"] = occ.status
    r = occ.reply if occ.ok else None
    box = (r or {}).get("box")
    if not r or r.get("read_status") != "RetDone" or not box:
        rec["kinds"] = ["occt_failed"]
        rec["changed"] = _stamp(path) != before
        return rec
    rec["voids"] = sum(1 for s in r.get("shells") or [] if (s.get("volume") or 0.0) < 0.0)
    chord = max(_diag(box) * CHORD_REL, 1e-7)
    ss = _read(path, chord_m=chord)
    rec["solidseas"] = ss.status
    if not ss.ok:
        rec["kinds"] = ["solidseas_" + ss.status]
        rec["detail"] = ss.exception or ss.crash
    elif ss.reply.get("refused"):
        rec["kinds"] = ["refused"]
        rec["detail"] = ss.reply["refused"]
    else:
        report = O.reader_report(r, _ours(ss.reply), tol=READER_TOL, self_tol=READER_TOL)
        rec["kinds"] = O.reader_kinds(report, READER_TOL)
        rec["occt_unsure"] = report["occt_unsure"]
        rec["volume_rel"] = report["volume_rel"]
        rec["inverted"] = [(i["occt"], i["ours"]) for i in report["shells"]["inverted"]]
        rec["seconds"] = ss.reply.get("seconds")
        # what the user sees and prints: the chord-independent disagreements at their chords
        for drawn in O.DRAWN:
            got = _read(path, drawn=drawn)
            if not got.ok:
                rec[drawn] = {"kinds": ["solidseas_" + got.status], "detail": got.exception or got.crash}
                continue
            if got.reply.get("refused"):
                rec[drawn] = {"kinds": ["refused"], "detail": got.reply["refused"]}
                continue
            rep = O.reader_report(r, _ours(got.reply), tol=READER_TOL, self_tol=READER_TOL)
            kinds = [k for k in O.reader_kinds(rep, READER_TOL) if k in O.SOUNDNESS]
            rec[drawn] = {
                "kinds": kinds or ["agree"],
                "chord_m": got.reply.get("chord_m"),
                "open_edges": rep["open_edges"],
                "inverted": [(i["occt"], i["ours"]) for i in rep["shells"]["inverted"]],
            }
    rec["changed"] = _stamp(path) != before
    return rec


def _failed(kinds) -> bool:
    return kinds[0].startswith("solidseas_") and kinds[0] != "solidseas_timeout"


def _readings(rec: dict) -> list[dict]:
    """A file's record at the oracle's chord, then as each of :data:`occt_support.DRAWN`."""
    return [rec, *(rec.get(d) or {"kinds": ["agree"]} for d in O.DRAWN)]


def _agrees(rec: dict) -> bool:
    """Agrees with OCCT at the oracle's chord, and sound as the viewer and 3D Print draw it."""
    return all(x["kinds"] == ["agree"] for x in _readings(rec))


def test_occt_corpus_step_reader(capsys):
    """SolidSeas' STEP reader against OCCT on private STEP files (see the module notes)."""
    files = step_files()
    cap = float(os.environ.get("SOLIDSEAS_OCCT_STEP_MAX_MB", "5")) * (1 << 20)
    eligible = [i for i, p in enumerate(files) if os.path.getsize(p) <= cap]
    n = int(os.environ.get("SOLIDSEAS_OCCT_STEP_SAMPLE", "40"))
    sample = set(random.Random(SEED).sample(eligible, min(n, len(eligible))))
    known = {k for ks in KNOWN_KEYS.values() for k in ks}
    keys = sample | known | set(VOIDS_READ_RIGHT)
    keys |= {int(k) for k in os.environ.get("SOLIDSEAS_OCCT_STEP_KEYS", "").split(",") if k.strip()}
    keys = sorted(k for k in keys if 0 <= k < len(files))
    old = _priority_below_normal()
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=_workers()) as pool:
            results = list(pool.map(read_one, [(k, files[k]) for k in keys]))
    finally:
        _priority_restore(old)
    elapsed = time.time() - t0
    by_kind: dict[str, dict[str, list[int]]] = {"oracle": {}}
    for r in results:
        for k in r["kinds"]:
            by_kind["oracle"].setdefault(k, []).append(r["key"])
        for drawn in O.DRAWN:
            for k in (r.get(drawn) or {}).get("kinds", ()):
                by_kind.setdefault(drawn, {}).setdefault(k, []).append(r["key"])
    changed = [r["key"] for r in results if r["changed"]]
    crashed = [  # a file past the child's time is counted, as the other corpus tests count limits
        (r["key"], how, kinds[0], detail)
        for r in results
        for how, kinds, detail in [("oracle", r["kinds"], r.get("detail"))]
        + [(d, (r.get(d) or {}).get("kinds", ["agree"]), (r.get(d) or {}).get("detail")) for d in O.DRAWN]
        if _failed(kinds)
    ]
    versions = O.versions()
    titles = {
        "oracle": f"at the oracle's chord ({CHORD_REL:g} of the box diagonal), every kind",
        "viewer": "as the viewer draws them, the kinds no chord excuses",
        "print": "as 3D Print tessellates them, the kinds no chord excuses",
    }
    with capsys.disabled():
        agree = by_kind["oracle"].get("agree", [])
        print(
            f"\nOCCT corpus STEP reader (OCP {versions.get('cadquery-ocp')}): {len(keys)} of {len(files)} "
            f"STEP files ({len(sample)} sampled, {len(known)} known) in {elapsed:.0f} s, agree {len(agree)}"
        )
        for how, kinds in by_kind.items():
            print(f"  {titles[how]}:")
            for kind, ks in sorted(kinds.items()):
                if kind != "agree":
                    print(f"    {kind}: {len(ks)} (step#{', step#'.join(map(str, ks[:20]))})")
        whole = {r["key"] for r in results if _agrees(r)}
        for what, ks in KNOWN_KEYS.items():
            fixed = [k for k in ks if k in whole]
            print(f"  known, {what}: {len(ks) - len(fixed)} of {len(ks)} disagree, agreeing now step#{fixed}")
        new = sorted(k for k in sample - known - set(VOIDS_READ_RIGHT) if k not in whole)
        print(f"  sampled files that disagree somewhere and are not known: {len(new)} (step#{new})")
        voids = [r for r in results if r.get("voids")]
        flipped = [r["key"] for r in voids if any(x.get("inverted") for x in _readings(r))]
        print(f"  files with voids {len(voids)}, a void inside out in {len(flipped)} (step#{flipped})")
        unsure = sum(r.get("occt_unsure", 0) for r in results)
        print(f"  OCCT failed its own self-check on {unsure} faces or volumes")
        print(f"  source files changed {len(changed)}")
    assert not changed, f"source files changed (step#{changed[:20]})"
    assert not crashed, f"SolidSeas failed on (key, how, status, class): {crashed[:20]}"
